from __future__ import annotations

import numpy as np
import pandas as pd

from app.utils.metrics import rsi


def generate_signals(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Opening-range fade by default, with optional breakout mode."""

    data = df.copy()
    style = str(config.get("style", "fade")).lower()
    minutes = int(config.get("opening_range_minutes", 15))
    data["rsi"] = rsi(data["close"], int(config.get("rsi_period", 14))).fillna(50)
    data["volume_avg"] = data["volume"].rolling(10).mean().bfill()

    session_start = data.index[0]
    opening_cutoff = session_start + pd.Timedelta(minutes=minutes)
    opening_slice = data[data.index < opening_cutoff]
    opening_high = float(opening_slice["high"].max())
    opening_low = float(opening_slice["low"].min())

    sweep_high = data["high"] > opening_high
    sweep_low = data["low"] < opening_low
    volume_spike = data["volume"] >= data["volume_avg"] * float(config.get("volume_spike_mult", 1.2))

    if style == "breakout":
        long_signal = (data["close"] > opening_high) & volume_spike
        short_signal = (data["close"] < opening_low) & volume_spike
        long_reason = "opening_range_breakout_long"
        short_reason = "opening_range_breakout_short"
    else:
        long_signal = sweep_low & (data["close"] > opening_low) & (
            data["rsi"] <= float(config.get("rsi_oversold", 35))
        )
        short_signal = sweep_high & (data["close"] < opening_high) & (
            data["rsi"] >= float(config.get("rsi_overbought", 65))
        )
        long_reason = "opening_range_fade_long"
        short_reason = "opening_range_fade_short"

    data["signal"] = np.where(long_signal, 1, np.where(short_signal, -1, 0))
    data["opening_high"] = opening_high
    data["opening_low"] = opening_low
    data["reason"] = np.where(long_signal, long_reason, np.where(short_signal, short_reason, ""))
    return data
