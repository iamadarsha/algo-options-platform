from __future__ import annotations

import numpy as np
import pandas as pd

from app.utils.metrics import ema, rsi


def generate_signals(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """EMA crossover with RSI confirmation and volume-spike filtering."""

    data = df.copy()
    data["ema_fast"] = ema(data["close"], int(config.get("ema_fast", 20)))
    data["ema_slow"] = ema(data["close"], int(config.get("ema_slow", 50)))
    data["rsi"] = rsi(data["close"], int(config.get("rsi_period", 14))).fillna(50)
    volume_window = int(config.get("volume_window", 20))
    data["volume_avg"] = data["volume"].rolling(volume_window).mean().bfill()
    data["range_high"] = data["high"].rolling(int(config.get("breakout_lookback", 12))).max().shift(1)
    data["range_low"] = data["low"].rolling(int(config.get("breakout_lookback", 12))).min().shift(1)

    volume_spike = data["volume"] >= (data["volume_avg"] * float(config.get("volume_spike_mult", 1.4)))
    cross_up = (data["ema_fast"] > data["ema_slow"]) & (data["ema_fast"].shift(1) <= data["ema_slow"].shift(1))
    cross_down = (data["ema_fast"] < data["ema_slow"]) & (data["ema_fast"].shift(1) >= data["ema_slow"].shift(1))
    trend_up = data["ema_fast"] > data["ema_slow"]
    trend_down = data["ema_fast"] < data["ema_slow"]
    breakout = data["close"] >= (data["range_high"].fillna(data["close"]) * 0.998)
    breakdown = data["close"] <= (data["range_low"].fillna(data["close"]) * 1.002)

    long_signal = volume_spike & trend_up & (data["ema_fast"].diff() > 0) & (
        (cross_up | breakout) & (data["rsi"] >= float(config.get("rsi_long", 58)))
    )
    short_signal = volume_spike & trend_down & (data["ema_fast"].diff() < 0) & (
        (cross_down | breakdown) & (data["rsi"] <= float(config.get("rsi_short", 42)))
    )

    data["signal"] = np.where(long_signal, 1, np.where(short_signal, -1, 0))
    data["reason"] = np.where(
        long_signal,
        "ema_breakout_long",
        np.where(short_signal, "ema_breakout_short", ""),
    )
    return data
