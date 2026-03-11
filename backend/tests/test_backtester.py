from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from app.backtest.backtester import Backtester
from app.config import load_config
from app.controllers.strategy_runner import create_strategy


class BacktesterTests(unittest.TestCase):
    def _sample_bars(self) -> pd.DataFrame:
        index = pd.date_range("2026-03-10 09:15", periods=60, freq="5min")
        close = np.concatenate(
            [
                np.linspace(100, 95, 15),
                np.linspace(95, 126, 25),
                np.linspace(126, 118, 20),
            ]
        )
        open_prices = np.concatenate([[100], close[:-1]])
        high = np.maximum(open_prices, close) + 1.5
        low = np.minimum(open_prices, close) - 1.5
        volume = np.concatenate([np.full(15, 900), np.full(25, 2800), np.full(20, 1200)])
        return pd.DataFrame(
            {
                "open": open_prices,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            },
            index=index,
        )

    def test_backtester_generates_trades_and_exports_csv(self) -> None:
        config = load_config(None)
        config.strategy_params["momentum"].update(
            {
                "ema_fast": 5,
                "ema_slow": 12,
                "volume_spike_mult": 1.0,
                "breakout_lookback": 4,
                "rsi_long": 50,
                "rsi_short": 50,
            }
        )
        strategy = create_strategy("momentum", config)
        backtester = Backtester(config)
        result = backtester.run(self._sample_bars(), strategy, underlying="NIFTY", capital=20000)

        self.assertFalse(result.trades.empty)
        self.assertIn("max_drawdown_pct", result.metrics)
        self.assertGreaterEqual(result.metrics["trade_count"], 1)

        walk_forward = backtester.walk_forward(self._sample_bars(), strategy, underlying="NIFTY")
        self.assertGreaterEqual(len(walk_forward), 1)

        monte_carlo = backtester.monte_carlo(result.trades, iterations=25)
        self.assertIn("median_total_pl", monte_carlo)

        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = Path(temp_dir) / "trades.csv"
            backtester.export_trade_log(result.trades, str(export_path))
            self.assertTrue(export_path.exists())
            content = export_path.read_text(encoding="utf-8")
            self.assertIn("instrument", content)


if __name__ == "__main__":
    unittest.main()
