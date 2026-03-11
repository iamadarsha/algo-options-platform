from __future__ import annotations

import logging
from typing import Any

import requests

from app.config import AppConfig
from app.storage.sqlite_store import SQLiteStore


LOGGER = logging.getLogger(__name__)


class ScreenerConnector:
    """Return normalized candidate instruments from Chartink and Screener.in or local fallbacks."""

    def __init__(self, config: AppConfig, store: SQLiteStore) -> None:
        self.config = config
        self.store = store
        self.session = requests.Session()

    def get_daily_candidates(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        cache_key = "screeners:daily"
        if not force_refresh:
            cached = self.store.cache_get(cache_key)
            if cached:
                return cached

        candidates = self.fetch_chartink_candidates() + self.fetch_screener_candidates()
        normalized = self._dedupe_candidates(candidates)
        if not normalized:
            normalized = self._sample_candidates()
        self.store.cache_set(cache_key, normalized, self.config.data_cache_ttl_seconds * 10)
        return normalized

    def fetch_chartink_candidates(self) -> list[dict[str, Any]]:
        # TODO: replace with a maintained Chartink scan endpoint or legal export flow.
        return [
            {
                "symbol": "RELIANCE",
                "source": "chartink",
                "score": 0.82,
                "tags": ["volume", "momentum", "breakout"],
            },
            {
                "symbol": "ICICIBANK",
                "source": "chartink",
                "score": 0.76,
                "tags": ["relative_strength", "breakout"],
            },
        ]

    def fetch_screener_candidates(self) -> list[dict[str, Any]]:
        # TODO: replace with a documented Screener.in integration or a curated local export.
        return [
            {
                "symbol": "HDFCBANK",
                "source": "screener.in",
                "score": 0.73,
                "tags": ["liquidity", "trend"],
            },
            {
                "symbol": "TCS",
                "source": "screener.in",
                "score": 0.68,
                "tags": ["mean_reversion", "quality"],
            },
        ]

    def _dedupe_candidates(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_symbol: dict[str, dict[str, Any]] = {}
        for row in rows:
            symbol = row["symbol"]
            current = by_symbol.get(symbol)
            if current is None or row["score"] > current["score"]:
                by_symbol[symbol] = row
        return sorted(by_symbol.values(), key=lambda item: item["score"], reverse=True)

    def _sample_candidates(self) -> list[dict[str, Any]]:
        return [
            {"symbol": "RELIANCE", "source": "sample", "score": 0.8, "tags": ["momentum"]},
            {"symbol": "HDFCBANK", "source": "sample", "score": 0.75, "tags": ["fade"]},
            {"symbol": "ICICIBANK", "source": "sample", "score": 0.7, "tags": ["mean_reversion"]},
        ]
