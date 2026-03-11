from __future__ import annotations

from math import sqrt
from typing import Any, Dict

import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def vwap(df: pd.DataFrame) -> pd.Series:
    cumulative_value = (df["close"] * df["volume"]).cumsum()
    cumulative_volume = df["volume"].replace(0, np.nan).cumsum()
    return cumulative_value / cumulative_volume


def max_consecutive_losses(pl_values: pd.Series) -> int:
    longest = current = 0
    for value in pl_values.fillna(0.0):
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _cagr(equity_curve: pd.Series, start_capital: float) -> float:
    if equity_curve.empty:
        return 0.0
    days = max((equity_curve.index[-1] - equity_curve.index[0]).days, 1)
    if days < 30:
        return 0.0
    ending = equity_curve.iloc[-1]
    if start_capital <= 0 or ending <= 0:
        return 0.0
    years = days / 365.25
    return ((ending / start_capital) ** (1 / max(years, 1 / 365.25)) - 1) * 100


def calculate_performance_metrics(
    equity_curve: pd.Series,
    trades: pd.DataFrame,
    start_capital: float,
) -> Dict[str, Any]:
    if equity_curve.empty:
        equity_curve = pd.Series([start_capital], index=[pd.Timestamp.utcnow()])
    trades = trades.copy()
    if trades.empty:
        daily_pnl = pd.Series(dtype=float)
    else:
        trades["closed_at"] = pd.to_datetime(trades["closed_at"])
        daily_pnl = trades.groupby(trades["closed_at"].dt.date)["pl"].sum()

    total_return = ((equity_curve.iloc[-1] / start_capital) - 1) * 100 if start_capital else 0.0
    returns = equity_curve.pct_change().dropna()
    sharpe = 0.0
    sortino = 0.0
    if not returns.empty and returns.std(ddof=0) > 0:
        sharpe = float((returns.mean() / returns.std(ddof=0)) * sqrt(252))
        downside = returns[returns < 0]
        if not downside.empty and downside.std(ddof=0) > 0:
            sortino = float((returns.mean() / downside.std(ddof=0)) * sqrt(252))

    running_peak = equity_curve.cummax()
    drawdowns = (equity_curve - running_peak) / running_peak.replace(0, np.nan)
    max_drawdown = float(drawdowns.min() * 100) if not drawdowns.empty else 0.0

    gross_profit = float(trades.loc[trades["pl"] > 0, "pl"].sum()) if not trades.empty else 0.0
    gross_loss = float(trades.loc[trades["pl"] < 0, "pl"].sum()) if not trades.empty else 0.0
    win_rate = float((trades["pl"] > 0).mean() * 100) if not trades.empty else 0.0
    profit_factor = float(gross_profit / abs(gross_loss)) if gross_loss < 0 else float("inf" if gross_profit > 0 else 0.0)

    return {
        "total_return_pct": round(total_return, 2),
        "cagr_pct": round(_cagr(equity_curve, start_capital), 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "max_drawdown_pct": round(max_drawdown, 2),
        "win_rate_pct": round(win_rate, 2),
        "profit_factor": round(profit_factor, 3) if np.isfinite(profit_factor) else "inf",
        "max_consecutive_losses": int(max_consecutive_losses(trades["pl"])) if not trades.empty else 0,
        "daily_pnl_distribution": [round(value, 2) for value in daily_pnl.tolist()],
        "trade_count": int(len(trades)),
    }


def json_ready_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    ready: Dict[str, Any] = {}
    for key, value in metrics.items():
        if isinstance(value, (np.floating, np.integer)):
            ready[key] = value.item()
        else:
            ready[key] = value
    return ready
