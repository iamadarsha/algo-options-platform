from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Optional

from app.storage.sqlite_store import SQLiteStore


@dataclass
class RiskState:
    trading_day: str
    capital: float
    realized_pnl: float
    daily_loss_limit: float
    per_trade_loss_limit: float
    trading_halted: bool = False

    @property
    def available_capital(self) -> float:
        return self.capital + self.realized_pnl

    @property
    def daily_loss_remaining(self) -> float:
        losses = max(0.0, -self.realized_pnl)
        return max(0.0, self.daily_loss_limit - losses)


class RiskManager:
    """Maintain capital and stop-trading rules with SQLite persistence."""

    def __init__(
        self,
        store: SQLiteStore,
        capital: float = 20000.0,
        daily_loss_limit: float = 1000.0,
        per_trade_loss_limit: float = 500.0,
        trading_day: Optional[str] = None,
    ) -> None:
        self.store = store
        trading_day = trading_day or date.today().isoformat()
        saved = self.store.load_risk_state(trading_day)
        if saved:
            self.state = RiskState(
                trading_day=saved["trading_day"],
                capital=float(saved["capital"]),
                realized_pnl=float(saved["realized_pnl"]),
                daily_loss_limit=float(saved["daily_loss_limit"]),
                per_trade_loss_limit=float(saved["per_trade_loss_limit"]),
                trading_halted=bool(saved["trading_halted"]),
            )
        else:
            self.state = RiskState(
                trading_day=trading_day,
                capital=float(capital),
                realized_pnl=0.0,
                daily_loss_limit=float(daily_loss_limit),
                per_trade_loss_limit=float(per_trade_loss_limit),
            )
            self._persist()

    def can_open_trade(self, amount: float, rupee_risk: Optional[float] = None) -> bool:
        """Reject trades when available capital or loss headroom is exhausted."""

        if self.state.trading_halted:
            return False
        if amount > self.state.available_capital:
            return False
        if self.state.daily_loss_remaining <= 0:
            return False
        if rupee_risk is not None:
            if rupee_risk > self.state.per_trade_loss_limit:
                return False
            if rupee_risk > self.state.daily_loss_remaining:
                return False
        return True

    def register_fill(self, trade: dict[str, Any]) -> RiskState:
        """Persist realized PnL after each completed trade and halt when limits are breached."""

        self.state.realized_pnl += float(trade.get("pl", 0.0))
        if self.state.daily_loss_remaining <= 0:
            self.enforce_stop()
        else:
            self._persist()
        return self.state

    def enforce_stop(self) -> None:
        self.state.trading_halted = True
        self._persist()

    def resume(self) -> None:
        if self.state.daily_loss_remaining > 0:
            self.state.trading_halted = False
            self._persist()

    def snapshot(self) -> dict[str, Any]:
        payload = asdict(self.state)
        payload["available_capital"] = round(self.state.available_capital, 2)
        payload["daily_loss_remaining"] = round(self.state.daily_loss_remaining, 2)
        return payload

    def _persist(self) -> None:
        self.store.save_risk_state(self.snapshot())
