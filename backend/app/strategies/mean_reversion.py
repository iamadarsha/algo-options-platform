from __future__ import annotations

import numpy as np
import pandas as pd

from app.utils.metrics import rsi, vwap


def generate_signals(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """RSI plus VWAP-distance based mean-reversion scalp."""

    data = df.copy()
    data["rsi"] = rsi(data["close"], int(config.get("rsi_period", 14))).fillna(50)
    data["vwap"] = vwap(data).bfill()
    band = float(config.get("vwap_band_pct", 0.003))

    long_signal = (data["close"] <= data["vwap"] * (1 - band)) & (
        data["rsi"] <= float(config.get("rsi_oversold", 30))
    )
    short_signal = (data["close"] >= data["vwap"] * (1 + band)) & (
        data["rsi"] >= float(config.get("rsi_overbought", 70))
    )

    data["signal"] = np.where(long_signal, 1, np.where(short_signal, -1, 0))
    data["reason"] = np.where(
        long_signal,
        "mean_reversion_long",
        np.where(short_signal, "mean_reversion_short", ""),
    )
    return data
