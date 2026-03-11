from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Generator, Optional

import numpy as np
import pandas as pd
import requests

from app.config import AppConfig
from app.storage.sqlite_store import SQLiteStore
from app.utils.option_utils import synthetic_option_chain


LOGGER = logging.getLogger(__name__)


class DataIngestController:
    """Market-data ingestion with broker-first fetches, local caching, and offline fallbacks."""

    def __init__(self, config: AppConfig, store: SQLiteStore) -> None:
        self.config = config
        self.store = store
        self.session = requests.Session()

    def _request_json(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        params: Optional[dict[str, Any]] = None,
        retries: int = 3,
    ) -> Optional[dict[str, Any]]:
        for attempt in range(retries):
            try:
                response = self.session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=self.config.request_timeout,
                )
                response.raise_for_status()
                return response.json()
            except Exception as exc:  # pragma: no cover - network path
                wait_seconds = 0.5 * (2**attempt)
                LOGGER.warning("Data request failed for %s (%s). retry=%s", url, exc, attempt + 1)
                time.sleep(wait_seconds)
        return None

    def _cache_key(self, prefix: str, *parts: Any) -> str:
        joined = ":".join(str(part) for part in parts if part is not None)
        return f"{prefix}:{joined}"

    def get_realtime_quote(self, symbol: str, force_refresh: bool = False) -> dict[str, Any]:
        cache_key = self._cache_key("ltp", symbol)
        if not force_refresh:
            cached = self.store.cache_get(cache_key)
            if cached:
                return cached

        quote = self._fetch_upstox_ltp(symbol)
        if quote is None:
            quote = self._synthetic_quote(symbol)
        self.store.cache_set(cache_key, quote, self.config.options_cache_ttl_seconds)
        return quote

    def poll_quotes(
        self,
        symbols: list[str],
        interval_seconds: float = 1.0,
        iterations: Optional[int] = None,
    ) -> Generator[list[dict[str, Any]], None, None]:
        count = 0
        while iterations is None or count < iterations:
            yield [self.get_realtime_quote(symbol, force_refresh=True) for symbol in symbols]
            count += 1
            time.sleep(interval_seconds)

    def get_options_chain(
        self,
        underlying: str,
        underlying_price: Optional[float] = None,
        expiry: Optional[str] = None,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        cache_key = self._cache_key("options", underlying, expiry)
        if not force_refresh:
            cached = self.store.cache_get(cache_key)
            if cached:
                return cached

        price = underlying_price or self.get_realtime_quote(underlying)["ltp"]
        chain = self._fetch_upstox_options_chain(underlying, expiry)
        if not chain:
            chain = synthetic_option_chain(underlying, price)
        self.store.cache_set(cache_key, chain, self.config.options_cache_ttl_seconds)
        return chain

    def get_historical_bars(
        self,
        symbol: str,
        interval: str = "5m",
        start: Optional[str | date | datetime] = None,
        end: Optional[str | date | datetime] = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        start_dt = pd.Timestamp(start or date.today())
        end_dt = pd.Timestamp(end or start_dt)
        cache_key = self._cache_key("bars", symbol, interval, start_dt.date().isoformat(), end_dt.date().isoformat())
        if not force_refresh:
            cached = self.store.cache_get(cache_key)
            if cached:
                return self._frame_from_records(cached)

        frame = self._fetch_upstox_historical(symbol, interval, start_dt, end_dt)
        if frame is None:
            frame = self._fetch_nse_csv(symbol, interval, start_dt, end_dt)
        if frame is None:
            frame = self._fetch_yahoo(symbol, interval, start_dt, end_dt)
        if frame is None:
            frame = self.generate_synthetic_intraday_bars(symbol, start_dt.date(), interval=interval)

        self.store.cache_set(cache_key, self._frame_to_records(frame), self.config.data_cache_ttl_seconds)
        return frame

    def generate_synthetic_intraday_bars(
        self,
        symbol: str,
        session_date: date,
        interval: str = "5m",
        seed: int = 42,
    ) -> pd.DataFrame:
        """Create one deterministic intraday session with a trend, reversal, and volume spikes."""

        start_dt = pd.Timestamp(datetime.combine(session_date, datetime.strptime("09:15", "%H:%M").time()))
        end_dt = pd.Timestamp(datetime.combine(session_date, datetime.strptime("15:29", "%H:%M").time()))
        index = pd.date_range(start_dt, end_dt, freq="1min")
        rng = np.random.default_rng(seed + sum(ord(char) for char in symbol))
        base_price = self._base_price(symbol)

        trend = np.concatenate(
            [
                np.linspace(0, 75, len(index) // 3),
                np.linspace(75, -60, len(index) // 3),
                np.linspace(-60, 105, len(index) - 2 * (len(index) // 3)),
            ]
        )
        intraday_wave = np.sin(np.linspace(0, 5.5 * np.pi, len(index))) * (base_price * 0.0012)
        noise = rng.normal(0, base_price * 0.00045, len(index)).cumsum() * 0.25
        close = base_price + trend + intraday_wave + noise
        open_prices = np.roll(close, 1)
        open_prices[0] = base_price

        spread = np.maximum(1.5, np.abs(rng.normal(base_price * 0.00035, base_price * 0.00012, len(index))))
        high = np.maximum(open_prices, close) + spread
        low = np.minimum(open_prices, close) - spread
        volume_base = 1800 if symbol.upper().endswith("NIFTY") else 850
        volume = rng.integers(volume_base, volume_base * 2, len(index))
        volume[60:80] *= 2
        volume[180:205] *= 3

        frame = pd.DataFrame(
            {
                "open": open_prices,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume.astype(int),
            },
            index=index,
        )
        frame.index.name = "timestamp"
        return self._resample_bars(frame, interval)

    def market_summary(self) -> dict[str, Any]:
        quote_nifty = self.get_realtime_quote("NIFTY")
        quote_banknifty = self.get_realtime_quote("BANKNIFTY")
        return {
            "sgx_nifty": {"value": round(quote_nifty["ltp"] + 42.0, 2), "change_pct": 0.31},
            "us_futures": {"value": 5234.5, "change_pct": 0.27},
            "crude": {"value": 81.2, "change_pct": -0.41},
            "global_cues": [
                "Asian markets mixed into the open.",
                "USDINR stable and crude contained.",
                f"NIFTY reference LTP {quote_nifty['ltp']:.2f}, BANKNIFTY {quote_banknifty['ltp']:.2f}.",
            ],
        }

    def _fetch_upstox_ltp(self, symbol: str) -> Optional[dict[str, Any]]:
        if not self.config.upstox.access_token:
            return None
        url = f"{self.config.upstox.base_url}/market-quote/ltp"
        headers = {"Authorization": f"Bearer {self.config.upstox.access_token}"}
        payload = self._request_json(url, headers=headers, params={"symbol": symbol})
        if not payload:  # pragma: no cover - network path
            return None
        # TODO: confirm exact Upstox LTP response shape for your account tier and API version.
        ltp = payload.get("data", {}).get(symbol, {}).get("last_price")
        if ltp is None:
            return None
        return {
            "symbol": symbol,
            "ltp": float(ltp),
            "timestamp": datetime.utcnow().isoformat(),
            "source": "upstox",
        }

    def _fetch_upstox_options_chain(self, underlying: str, expiry: Optional[str]) -> Optional[list[dict[str, Any]]]:
        if not self.config.upstox.access_token:
            return None
        url = f"{self.config.upstox.base_url}/option/chain"
        headers = {"Authorization": f"Bearer {self.config.upstox.access_token}"}
        payload = self._request_json(url, headers=headers, params={"underlying": underlying, "expiry": expiry})
        if not payload:  # pragma: no cover - network path
            return None
        # TODO: map the live Upstox option-chain payload to the normalized contract format below.
        records = payload.get("data", [])
        normalized = []
        for item in records:
            normalized.append(
                {
                    "symbol": item.get("symbol"),
                    "underlying": underlying,
                    "strike": item.get("strike"),
                    "option_type": item.get("option_type"),
                    "premium": item.get("ltp"),
                    "lot_size": item.get("lot_size", 1),
                    "open_interest": item.get("open_interest", 0),
                    "volume": item.get("volume", 0),
                }
            )
        return normalized or None

    def _fetch_upstox_historical(
        self,
        symbol: str,
        interval: str,
        start_dt: pd.Timestamp,
        end_dt: pd.Timestamp,
    ) -> Optional[pd.DataFrame]:
        if not self.config.upstox.access_token:
            return None
        url = f"{self.config.upstox.base_url}/historical-candle/{symbol}/{interval}/{end_dt.date()}/{start_dt.date()}"
        headers = {"Authorization": f"Bearer {self.config.upstox.access_token}"}
        payload = self._request_json(url, headers=headers)
        if not payload:  # pragma: no cover - network path
            return None
        # TODO: confirm exact historical candle response ordering from Upstox.
        candles = payload.get("data", {}).get("candles", [])
        if not candles:
            return None
        frame = pd.DataFrame(
            candles,
            columns=["timestamp", "open", "high", "low", "close", "volume", "open_interest"],
        )
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        frame = frame.set_index("timestamp")[["open", "high", "low", "close", "volume"]]
        return frame.sort_index()

    def _fetch_nse_csv(
        self,
        symbol: str,
        interval: str,
        start_dt: pd.Timestamp,
        end_dt: pd.Timestamp,
    ) -> Optional[pd.DataFrame]:
        # TODO: replace with a maintained NSE CSV endpoint or local archival download path.
        return None

    def _fetch_yahoo(
        self,
        symbol: str,
        interval: str,
        start_dt: pd.Timestamp,
        end_dt: pd.Timestamp,
    ) -> Optional[pd.DataFrame]:
        # TODO: hook up yfinance or another official data source if your environment allows it.
        return None

    def _synthetic_quote(self, symbol: str) -> dict[str, Any]:
        now = pd.Timestamp.utcnow()
        minute_of_day = (now.hour * 60) + now.minute
        base = self._base_price(symbol)
        drift = np.sin(minute_of_day / 18.0) * (base * 0.0015)
        ltp = round(base + drift, 2)
        return {
            "symbol": symbol,
            "ltp": ltp,
            "timestamp": now.isoformat(),
            "source": "synthetic",
        }

    def _base_price(self, symbol: str) -> float:
        upper = symbol.upper()
        if "BANKNIFTY" in upper:
            return 47500.0
        if "NIFTY" in upper:
            return 22150.0
        if upper == "RELIANCE":
            return 2950.0
        if upper == "HDFCBANK":
            return 1680.0
        if upper == "ICICIBANK":
            return 1120.0
        return 500.0

    def _resample_bars(self, frame: pd.DataFrame, interval: str) -> pd.DataFrame:
        mapping = {"1m": "1min", "3m": "3min", "5m": "5min"}
        rule = mapping.get(interval, "5min")
        if rule == "1min":
            return frame
        resampled = frame.resample(rule, label="right", closed="right").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        )
        return resampled.dropna()

    def _frame_to_records(self, frame: pd.DataFrame) -> list[dict[str, Any]]:
        records = frame.reset_index().to_dict(orient="records")
        for row in records:
            row["timestamp"] = pd.Timestamp(row["timestamp"]).isoformat()
        return records

    def _frame_from_records(self, records: list[dict[str, Any]]) -> pd.DataFrame:
        frame = pd.DataFrame(records)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        return frame.set_index("timestamp").sort_index()
