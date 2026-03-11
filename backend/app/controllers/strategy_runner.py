from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional
from uuid import uuid4

import pandas as pd

from app.config import AppConfig
from app.controllers.order_manager import OrderManager
from app.controllers.risk_manager import RiskManager
from app.storage.sqlite_store import SQLiteStore
from app.strategies import mean_reversion, momentum, opening_range_fade
from app.utils.lot_size import calc_sl_tp_percent
from app.utils.option_utils import project_option_price, select_option_contract


STRATEGY_REGISTRY: dict[str, Callable[[pd.DataFrame, dict[str, Any]], pd.DataFrame]] = {
    "momentum": momentum.generate_signals,
    "opening_range_fade": opening_range_fade.generate_signals,
    "mean_reversion": mean_reversion.generate_signals,
}


@dataclass
class Strategy:
    name: str
    config: dict[str, Any]
    app_config: AppConfig

    def evaluate(self, df: pd.DataFrame) -> pd.DataFrame:
        generator = STRATEGY_REGISTRY[self.name]
        return generator(df, self.config)

    def enter_trade(
        self,
        timestamp: pd.Timestamp,
        signal_row: pd.Series,
        underlying: str,
        capital: float,
        chain: Optional[list[dict[str, Any]]] = None,
    ) -> Optional[dict[str, Any]]:
        """Create a trade candidate with option selection and rupee-based stop/target math."""

        signal = int(signal_row["signal"])
        if signal == 0:
            return None

        contract = select_option_contract(
            underlying=underlying,
            underlying_price=float(signal_row["open"]),
            capital=capital,
            direction=signal,
            chain=chain,
            max_exposure_pct=self.app_config.max_exposure_pct,
        )
        if not contract:
            return None

        qty = int(contract["qty"])
        rupee_stop = min(self.app_config.per_trade_loss_limit, self.app_config.daily_loss_limit)
        rupee_target = rupee_stop * float(self.config.get("reward_multiple", 1.5))
        sl_tp = calc_sl_tp_percent(
            rupee_stop=rupee_stop,
            rupee_take=rupee_target,
            premium=float(contract["premium"]),
            lot_size=int(contract["lot_size"]),
            qty=qty,
        )

        entry_price = round(float(contract["premium"]) * (1 + self.app_config.backtest.slippage_pct / 100), 2)
        return {
            "trade_id": str(uuid4()),
            "strategy": self.name,
            "instrument": contract["symbol"],
            "side": "BUY",
            "signal": signal,
            "qty": qty,
            "lot_size": int(contract["lot_size"]),
            "strike": int(contract["strike"]),
            "option_type": contract["option_type"],
            "entry_price": entry_price,
            "entry_underlying": float(signal_row["open"]),
            "capital_required": round(contract["premium"] * contract["lot_size"] * qty, 2),
            "rupee_stop": round(rupee_stop, 2),
            "rupee_target": round(rupee_target, 2),
            "sl_pct": round(sl_tp["sl_pct"], 2),
            "tp_pct": round(sl_tp["tp_pct"], 2),
            "stop_price": round(entry_price * (1 - (sl_tp["sl_pct"] / 100)), 2),
            "target_price": round(entry_price * (1 + (sl_tp["tp_pct"] / 100)), 2),
            "opened_at": timestamp.isoformat(),
            "status": "open",
            "reason": signal_row.get("reason", ""),
        }

    def exit_trade(
        self,
        trade: dict[str, Any],
        timestamp: pd.Timestamp,
        exit_price: float,
        reason: str,
    ) -> dict[str, Any]:
        """Close a trade and compute final PnL including round-trip commissions."""

        exit_fill = round(exit_price * (1 - self.app_config.backtest.slippage_pct / 100), 2)
        gross_pnl = (exit_fill - trade["entry_price"]) * trade["lot_size"] * trade["qty"]
        fees = self.app_config.backtest.commission_per_order * 2
        closed_trade = dict(trade)
        closed_trade.update(
            {
                "exit_price": round(exit_fill, 2),
                "pl": round(gross_pnl - fees, 2),
                "sl": trade["stop_price"],
                "tp": trade["target_price"],
                "reason": reason,
                "status": "closed",
                "closed_at": timestamp.isoformat(),
            }
        )
        return closed_trade

    def simulate_session(
        self,
        df: pd.DataFrame,
        underlying: str,
        capital: Optional[float] = None,
        allow_trade_fn: Optional[Callable[[float, float], bool]] = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
        """Simulate one intraday session using option premiums derived from the underlying bars."""

        signals = self.evaluate(df)
        start_capital = float(capital if capital is not None else self.app_config.capital)
        realized_pnl = 0.0
        active_trade: Optional[dict[str, Any]] = None
        trades: list[dict[str, Any]] = []
        equity_points: list[tuple[pd.Timestamp, float]] = []

        for index in range(len(signals)):
            timestamp = signals.index[index]
            row = signals.iloc[index]

            if active_trade is not None:
                option_high = project_option_price(
                    entry_premium=active_trade["entry_price"],
                    entry_underlying=active_trade["entry_underlying"],
                    current_underlying=float(row["high"]),
                    option_type=active_trade["option_type"],
                    strike=active_trade["strike"],
                )
                option_low = project_option_price(
                    entry_premium=active_trade["entry_price"],
                    entry_underlying=active_trade["entry_underlying"],
                    current_underlying=float(row["low"]),
                    option_type=active_trade["option_type"],
                    strike=active_trade["strike"],
                )
                option_close = project_option_price(
                    entry_premium=active_trade["entry_price"],
                    entry_underlying=active_trade["entry_underlying"],
                    current_underlying=float(row["close"]),
                    option_type=active_trade["option_type"],
                    strike=active_trade["strike"],
                )
                reason = None
                exit_reference = option_close
                if option_low <= active_trade["stop_price"]:
                    reason = "stop_loss"
                    exit_reference = active_trade["stop_price"]
                elif option_high >= active_trade["target_price"]:
                    reason = "take_profit"
                    exit_reference = active_trade["target_price"]
                elif timestamp.strftime("%H:%M") >= self.app_config.square_off_time:
                    reason = "square_off"
                elif int(row["signal"]) == -int(active_trade["signal"]):
                    reason = "reverse_signal"

                if reason is not None:
                    closed = self.exit_trade(active_trade, timestamp, exit_reference, reason)
                    trades.append(closed)
                    realized_pnl += closed["pl"]
                    active_trade = None

            mark_to_market = 0.0
            if active_trade is not None:
                option_close = project_option_price(
                    entry_premium=active_trade["entry_price"],
                    entry_underlying=active_trade["entry_underlying"],
                    current_underlying=float(row["close"]),
                    option_type=active_trade["option_type"],
                    strike=active_trade["strike"],
                )
                mark_to_market = (option_close - active_trade["entry_price"]) * active_trade["lot_size"] * active_trade["qty"]
            equity_points.append((timestamp, start_capital + realized_pnl + mark_to_market))

            if active_trade is None and index + 1 < len(signals):
                signal = int(row["signal"])
                if signal != 0:
                    entry_timestamp = signals.index[index + 1]
                    entry_row = signals.iloc[index + 1]
                    candidate = self.enter_trade(
                        timestamp=entry_timestamp,
                        signal_row=entry_row,
                        underlying=underlying,
                        capital=start_capital + realized_pnl,
                    )
                    if candidate:
                        allow_trade = True
                        if allow_trade_fn is not None:
                            allow_trade = allow_trade_fn(candidate["capital_required"], candidate["rupee_stop"])
                        if allow_trade:
                            active_trade = candidate

        if active_trade is not None:
            last_timestamp = signals.index[-1]
            last_row = signals.iloc[-1]
            option_close = project_option_price(
                entry_premium=active_trade["entry_price"],
                entry_underlying=active_trade["entry_underlying"],
                current_underlying=float(last_row["close"]),
                option_type=active_trade["option_type"],
                strike=active_trade["strike"],
            )
            closed = self.exit_trade(active_trade, last_timestamp, option_close, "session_end")
            trades.append(closed)
            realized_pnl += closed["pl"]
            equity_points[-1] = (last_timestamp, start_capital + realized_pnl)

        trades_df = pd.DataFrame(trades)
        equity_curve = pd.Series(
            [value for _, value in equity_points],
            index=[timestamp for timestamp, _ in equity_points],
            dtype=float,
        )
        return trades_df, signals, equity_curve

    def run_intraday_session(
        self,
        df: pd.DataFrame,
        underlying: str,
        risk_manager: Optional[RiskManager] = None,
        order_manager: Optional[OrderManager] = None,
        store: Optional[SQLiteStore] = None,
    ) -> dict[str, Any]:
        trades_df, signals, equity_curve = self.simulate_session(
            df,
            underlying=underlying,
            capital=self.app_config.capital,
            allow_trade_fn=risk_manager.can_open_trade if risk_manager else None,
        )

        if not trades_df.empty:
            for trade in trades_df.to_dict(orient="records"):
                if order_manager is not None:
                    entry_order = order_manager.place_order(
                        instrument=trade["instrument"],
                        qty=trade["qty"],
                        order_type="MARKET",
                        price=trade["entry_price"],
                        side="BUY",
                        stop_loss=trade["sl"],
                        take_profit=trade["tp"],
                        idempotency_key=f"{trade['instrument']}:{trade['opened_at']}:entry",
                        meta={"ltp": trade["entry_price"], "strategy": self.name},
                    )
                    exit_order = order_manager.place_order(
                        instrument=trade["instrument"],
                        qty=trade["qty"],
                        order_type="MARKET",
                        price=trade["exit_price"],
                        side="SELL",
                        idempotency_key=f"{trade['instrument']}:{trade['closed_at']}:exit",
                        meta={"ltp": trade["exit_price"], "strategy": self.name, "reason": trade["reason"]},
                    )
                    trade["order_id"] = entry_order["order_id"]
                    trade["exit_order_id"] = exit_order["order_id"]
                if store is not None:
                    store.save_trade(trade)
                if risk_manager is not None:
                    risk_manager.register_fill(trade)
                    if risk_manager.state.trading_halted and order_manager is not None:
                        order_manager.square_off_all()
                        break

        return {"trades": trades_df, "signals": signals, "equity_curve": equity_curve}


def create_strategy(name: str, app_config: AppConfig) -> Strategy:
    if name not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy '{name}'. Available: {sorted(STRATEGY_REGISTRY)}")
    return Strategy(
        name=name,
        config=app_config.strategy_params.get(name, {}),
        app_config=app_config,
    )
