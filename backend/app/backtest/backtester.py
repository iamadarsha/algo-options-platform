from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd

from app.config import AppConfig
from app.controllers.strategy_runner import Strategy
from app.utils.metrics import calculate_performance_metrics, json_ready_metrics


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    signals: pd.DataFrame
    equity_curve: pd.Series
    metrics: dict[str, Any]


class Backtester:
    """Vectorized signal generation with realistic fill helpers and analytics."""

    def __init__(self, app_config: AppConfig) -> None:
        self.app_config = app_config

    def fill_order(
        self,
        bar: pd.Series,
        order_type: str,
        side: str,
        requested_price: Optional[float] = None,
    ) -> Optional[float]:
        slippage = self.app_config.backtest.slippage_pct / 100.0
        order_type = order_type.upper()
        side = side.upper()

        if order_type == "MARKET":
            fill = float(bar["open"])
        elif order_type == "LIMIT":
            if requested_price is None:
                return None
            if side == "BUY" and float(bar["low"]) <= requested_price:
                fill = requested_price
            elif side == "SELL" and float(bar["high"]) >= requested_price:
                fill = requested_price
            else:
                return None
        elif order_type == "STOP":
            if requested_price is None:
                return None
            if side == "BUY" and float(bar["high"]) >= requested_price:
                fill = requested_price
            elif side == "SELL" and float(bar["low"]) <= requested_price:
                fill = requested_price
            else:
                return None
        else:
            raise ValueError(f"Unsupported order type: {order_type}")

        adjusted = fill * (1 + slippage) if side == "BUY" else fill * (1 - slippage)
        return round(adjusted, 2)

    def run(
        self,
        df: pd.DataFrame,
        strategy: Strategy,
        underlying: str = "NIFTY",
        capital: Optional[float] = None,
    ) -> BacktestResult:
        trades, signals, equity_curve = strategy.simulate_session(df, underlying=underlying, capital=capital)
        metrics = calculate_performance_metrics(
            equity_curve=equity_curve,
            trades=trades if not trades.empty else pd.DataFrame(columns=["pl", "closed_at"]),
            start_capital=float(capital if capital is not None else self.app_config.capital),
        )
        return BacktestResult(trades=trades, signals=signals, equity_curve=equity_curve, metrics=metrics)

    def walk_forward(
        self,
        df: pd.DataFrame,
        strategy: Strategy,
        underlying: str = "NIFTY",
    ) -> list[dict[str, Any]]:
        if len(df) < 40:
            result = self.run(df, strategy, underlying=underlying)
            return [{"window": "single", "metrics": json_ready_metrics(result.metrics)}]

        split_point = int(len(df) * 0.7)
        train = df.iloc[:split_point]
        test = df.iloc[split_point:]
        train_result = self.run(train, strategy, underlying=underlying)
        test_result = self.run(test, strategy, underlying=underlying)
        return [
            {
                "window": "train",
                "start": train.index[0].isoformat(),
                "end": train.index[-1].isoformat(),
                "metrics": json_ready_metrics(train_result.metrics),
            },
            {
                "window": "test",
                "start": test.index[0].isoformat(),
                "end": test.index[-1].isoformat(),
                "metrics": json_ready_metrics(test_result.metrics),
            },
        ]

    def monte_carlo(self, trades: pd.DataFrame, iterations: int = 250, seed: int = 42) -> dict[str, Any]:
        if trades.empty:
            return {"iterations": iterations, "median_total_pl": 0.0, "p05_total_pl": 0.0, "p95_total_pl": 0.0}
        rng = np.random.default_rng(seed)
        pl_values = trades["pl"].to_numpy(dtype=float)
        samples = []
        for _ in range(iterations):
            resample = rng.choice(pl_values, size=len(pl_values), replace=True)
            samples.append(float(resample.sum()))
        return {
            "iterations": iterations,
            "median_total_pl": round(float(np.median(samples)), 2),
            "p05_total_pl": round(float(np.percentile(samples, 5)), 2),
            "p95_total_pl": round(float(np.percentile(samples, 95)), 2),
        }

    def export_trade_log(self, trades: pd.DataFrame, path: str) -> None:
        export = trades.copy()
        if export.empty:
            export = pd.DataFrame(
                columns=["timestamp", "instrument", "side", "qty", "entry_price", "exit_price", "pl", "sl", "tp", "reason"]
            )
        else:
            export = export.rename(columns={"opened_at": "timestamp"})[
                ["timestamp", "instrument", "side", "qty", "entry_price", "exit_price", "pl", "sl", "tp", "reason"]
            ]
        export.to_csv(path, index=False)
