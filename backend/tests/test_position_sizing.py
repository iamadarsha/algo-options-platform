from __future__ import annotations

import unittest

from app.utils.lot_size import calc_max_qty, calc_sl_tp_percent, detect_lot_size


class PositionSizingTests(unittest.TestCase):
    def test_calc_max_qty_conservative_default(self) -> None:
        self.assertEqual(calc_max_qty(premium=100, lot_size=75, capital=20000), 2)

    def test_calc_max_qty_insufficient_capital(self) -> None:
        self.assertEqual(calc_max_qty(premium=300, lot_size=75, capital=20000), 0)

    def test_calc_sl_tp_percent_matches_formula(self) -> None:
        values = calc_sl_tp_percent(rupee_stop=500, rupee_take=1000, premium=100, lot_size=75, qty=2)
        self.assertAlmostEqual(values["sl_pct"], 3.3333333333, places=4)
        self.assertAlmostEqual(values["tp_pct"], 6.6666666666, places=4)

    def test_detect_lot_size_for_index_options(self) -> None:
        self.assertEqual(detect_lot_size("NIFTYWK22100CE"), 75)
        self.assertEqual(detect_lot_size("BANKNIFTYWK48000PE"), 30)


if __name__ == "__main__":
    unittest.main()
