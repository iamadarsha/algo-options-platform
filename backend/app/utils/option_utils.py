from __future__ import annotations

from dataclasses import dataclass
from math import floor
from random import Random
from typing import Any, Iterable, Optional

from app.utils.lot_size import calc_max_qty, detect_lot_size


@dataclass
class OptionContract:
    symbol: str
    underlying: str
    strike: int
    option_type: str
    premium: float
    lot_size: int
    open_interest: int
    volume: int

    @property
    def liquidity(self) -> int:
        return max(self.open_interest, self.volume)


def strike_step_for_symbol(symbol: str) -> int:
    upper = symbol.upper()
    if "BANKNIFTY" in upper:
        return 100
    if "NIFTY" in upper:
        return 50
    return 10


def nearest_strike(underlying_price: float, symbol: str) -> int:
    step = strike_step_for_symbol(symbol)
    return int(round(underlying_price / step) * step)


def estimate_option_premium(underlying_price: float, strike: int, option_type: str, days_to_expiry: int = 3) -> float:
    """A deterministic synthetic premium model for paper trading and backtests."""

    intrinsic = max(0.0, underlying_price - strike) if option_type == "CALL" else max(0.0, strike - underlying_price)
    distance = abs(underlying_price - strike)
    decay = max(days_to_expiry, 1) / 3.0
    extrinsic = max(8.0, (28.0 * decay) - (distance * 0.08))
    return round((intrinsic * 0.55) + extrinsic, 2)


def build_option_symbol(underlying: str, strike: int, option_type: str, expiry_code: str = "WK") -> str:
    suffix = "CE" if option_type == "CALL" else "PE"
    return f"{underlying.upper()}{expiry_code}{strike}{suffix}"


def synthetic_option_chain(
    underlying: str,
    underlying_price: float,
    instrument_meta: Optional[dict[str, Any]] = None,
    seed: int = 42,
) -> list[dict[str, Any]]:
    rng = Random(seed + int(underlying_price))
    atm = nearest_strike(underlying_price, underlying)
    step = strike_step_for_symbol(underlying)
    lot_size = detect_lot_size(underlying, instrument_meta)
    chain: list[dict[str, Any]] = []
    for offset in range(-3, 4):
        strike = atm + offset * step
        for option_type in ("CALL", "PUT"):
            premium = estimate_option_premium(underlying_price, strike, option_type)
            chain.append(
                {
                    "symbol": build_option_symbol(underlying, strike, option_type),
                    "underlying": underlying,
                    "strike": strike,
                    "option_type": option_type,
                    "premium": premium,
                    "lot_size": lot_size,
                    "open_interest": 1400 + rng.randint(0, 2500) - abs(offset) * 150,
                    "volume": 1500 + rng.randint(0, 4000) - abs(offset) * 180,
                }
            )
    return chain


def select_option_contract(
    underlying: str,
    underlying_price: float,
    capital: float,
    direction: int,
    chain: Optional[Iterable[dict[str, Any]]] = None,
    liquidity_threshold: int = 1500,
    max_strikes_otm: int = 3,
    instrument_meta: Optional[dict[str, Any]] = None,
    max_exposure_pct: float = 0.9,
    preferred_lots: int = 1,
) -> Optional[dict[str, Any]]:
    """Pick the cheapest liquid ATM or near-OTM option contract that fits capital."""

    chain_items = list(chain or synthetic_option_chain(underlying, underlying_price, instrument_meta))
    option_type = "CALL" if direction > 0 else "PUT"
    atm = nearest_strike(underlying_price, underlying)
    step = strike_step_for_symbol(underlying)
    desired_strikes = [atm]

    for distance in range(1, max_strikes_otm + 1):
        desired_strikes.append(atm + (distance * step if option_type == "CALL" else -distance * step))

    ranked = []
    for row in chain_items:
        if row["option_type"] != option_type:
            continue
        if row["strike"] not in desired_strikes:
            continue
        liquidity = max(int(row["open_interest"]), int(row["volume"]))
        rank = desired_strikes.index(row["strike"])
        ranked.append((rank, -liquidity, row))
    ranked.sort(key=lambda item: (item[0], item[1]))

    for _, _, contract in ranked:
        liquidity = max(int(contract["open_interest"]), int(contract["volume"]))
        if liquidity < liquidity_threshold:
            continue
        lot_size = detect_lot_size(contract["symbol"], contract)
        max_qty = calc_max_qty(contract["premium"], lot_size, capital, max_exposure_pct)
        if max_qty >= 1:
            contract["qty"] = min(max_qty, max(preferred_lots, 1))
            contract["cost_per_lot"] = round(contract["premium"] * lot_size, 2)
            return contract
    return None


def project_option_price(
    entry_premium: float,
    entry_underlying: float,
    current_underlying: float,
    option_type: str,
    strike: int,
) -> float:
    """Project a synthetic option premium from the underlying move."""

    moneyness_distance = abs(entry_underlying - strike)
    delta = 0.34 if moneyness_distance <= strike_step_for_symbol("NIFTY") else 0.22
    signed_move = current_underlying - entry_underlying
    if option_type == "PUT":
        signed_move *= -1
    projected = max(1.0, entry_premium + (signed_move * delta))
    return round(projected, 2)


def round_notional(value: float) -> float:
    return round(value, 2)
