from __future__ import annotations

import re
from typing import Any, Optional


DEFAULT_LOT_SIZES = {
    "BANKNIFTY": 30,
    "MIDCPNIFTY": 75,
    "FINNIFTY": 65,
    "SENSEX": 10,
    "NIFTY": 75,
}


def detect_lot_size(symbol: str, instrument_meta: Optional[dict[str, Any]] = None) -> int:
    """Resolve lot size from live metadata when present, else use a safe fallback map."""

    if instrument_meta and instrument_meta.get("lot_size"):
        return int(instrument_meta["lot_size"])

    upper_symbol = symbol.upper()
    for known_symbol, lot_size in DEFAULT_LOT_SIZES.items():
        if known_symbol in upper_symbol:
            return lot_size

    option_match = re.match(r"([A-Z]+)", upper_symbol)
    if option_match:
        root = option_match.group(1)
        return DEFAULT_LOT_SIZES.get(root, 1)
    return 1


def calc_max_qty(premium: float, lot_size: int, capital: float, max_exposure_pct: float = 0.9) -> int:
    """Return the maximum lots affordable under the exposure cap."""

    if premium <= 0 or lot_size <= 0 or capital <= 0 or max_exposure_pct <= 0:
        return 0
    max_notional = capital * max_exposure_pct
    return max(int(max_notional // (premium * lot_size)), 0)


def calc_sl_tp_percent(
    rupee_stop: float,
    premium: float,
    lot_size: int,
    qty: int,
    rupee_take: Optional[float] = None,
    reward_multiple: float = 1.5,
) -> dict[str, float]:
    """Convert rupee stop and target amounts into percentage thresholds."""

    notional = premium * lot_size * qty
    if notional <= 0:
        return {"sl_pct": 0.0, "tp_pct": 0.0}
    rupee_take = rupee_take if rupee_take is not None else rupee_stop * reward_multiple
    return {
        "sl_pct": (rupee_stop / notional) * 100.0,
        "tp_pct": (rupee_take / notional) * 100.0,
    }
