from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.controllers.risk_manager import RiskManager
from app.storage.sqlite_store import SQLiteStore


class RiskManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "risk.db"
        self.store = SQLiteStore(db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_can_open_trade_respects_capital_and_risk(self) -> None:
        manager = RiskManager(self.store, capital=20000, daily_loss_limit=1000, per_trade_loss_limit=500, trading_day="2026-03-10")
        self.assertTrue(manager.can_open_trade(12000, 500))
        self.assertFalse(manager.can_open_trade(25000, 500))
        self.assertFalse(manager.can_open_trade(5000, 700))

    def test_register_fill_persists_and_halts(self) -> None:
        manager = RiskManager(self.store, capital=20000, daily_loss_limit=1000, per_trade_loss_limit=500, trading_day="2026-03-10")
        manager.register_fill({"pl": -500})
        manager.register_fill({"pl": -500})

        self.assertTrue(manager.state.trading_halted)
        self.assertEqual(manager.state.daily_loss_remaining, 0.0)

        restored = RiskManager(self.store, capital=9999, daily_loss_limit=1000, per_trade_loss_limit=500, trading_day="2026-03-10")
        self.assertTrue(restored.state.trading_halted)
        self.assertEqual(restored.state.realized_pnl, -1000.0)


if __name__ == "__main__":
    unittest.main()
