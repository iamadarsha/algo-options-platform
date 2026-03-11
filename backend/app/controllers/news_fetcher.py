from __future__ import annotations

import logging
import os
import time
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any, Optional

import requests

from app.config import AppConfig
from app.storage.sqlite_store import SQLiteStore


LOGGER = logging.getLogger(__name__)

POSITIVE_WORDS = {"gain", "up", "beat", "surge", "bullish", "growth", "stable", "record"}
NEGATIVE_WORDS = {"drop", "down", "miss", "selloff", "bearish", "risk", "weak", "loss"}


class NewsFetcher:
    """Fetch RSS headlines and broker commentary with a light sentiment layer."""

    RSS_SOURCES = {
        "Economic Times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "Moneycontrol": "https://www.moneycontrol.com/rss/MCtopnews.xml",
        "CNBC-TV18": "https://www.cnbctv18.com/commonfeeds/v1/eng/rss/market.xml",
        "BloombergQuint": "https://www.ndtvprofit.com/rss",
    }

    def __init__(self, config: AppConfig, store: SQLiteStore) -> None:
        self.config = config
        self.store = store
        self.session = requests.Session()
        self.twitter_bearer_token = os.getenv("TWITTER_BEARER_TOKEN", "")
        try:  # pragma: no cover - optional package
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

            self._analyzer = SentimentIntensityAnalyzer()
        except Exception:  # pragma: no cover - optional package
            self._analyzer = None

    def fetch_headlines(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        cache_key = "news:headlines"
        if not force_refresh:
            cached = self.store.cache_get(cache_key)
            if cached:
                return cached

        headlines: list[dict[str, Any]] = []
        for source, url in self.RSS_SOURCES.items():
            try:
                response = self.session.get(url, timeout=self.config.request_timeout)
                response.raise_for_status()
                root = ET.fromstring(response.text)
                for item in root.findall(".//item")[:3]:
                    title = (item.findtext("title") or "").strip()
                    if not title:
                        continue
                    headlines.append(
                        {
                            "source": source,
                            "title": title,
                            "link": item.findtext("link") or "",
                            "sentiment": self.sentiment_score(title),
                        }
                    )
                time.sleep(0.1)
            except Exception as exc:  # pragma: no cover - network path
                LOGGER.warning("RSS fetch failed for %s: %s", source, exc)

        if not headlines:
            headlines = self._sample_headlines()

        self.store.cache_set(cache_key, headlines, self.config.data_cache_ttl_seconds * 5)
        return headlines

    def fetch_verified_broker_posts(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        cache_key = "news:broker_posts"
        if not force_refresh:
            cached = self.store.cache_get(cache_key)
            if cached:
                return cached

        if not self.twitter_bearer_token:
            posts = self._sample_posts()
            self.store.cache_set(cache_key, posts, self.config.data_cache_ttl_seconds * 5)
            return posts

        # TODO: replace with Twitter/X API v2 integration when a bearer token is available.
        posts = self._sample_posts()
        self.store.cache_set(cache_key, posts, self.config.data_cache_ttl_seconds * 5)
        return posts

    def sentiment_score(self, text: str) -> float:
        if self._analyzer is not None:  # pragma: no cover - optional package
            return round(self._analyzer.polarity_scores(text)["compound"], 3)

        tokens = [token.strip(".,:;!?").lower() for token in text.split()]
        counts = Counter(tokens)
        positive = sum(counts[word] for word in POSITIVE_WORDS)
        negative = sum(counts[word] for word in NEGATIVE_WORDS)
        total = max(len(tokens), 1)
        return round((positive - negative) / total, 3)

    def build_premarket_summary(self) -> dict[str, Any]:
        headlines = self.fetch_headlines()
        posts = self.fetch_verified_broker_posts()
        combined_score = 0.0
        if headlines or posts:
            values = [item["sentiment"] for item in headlines] + [item["sentiment"] for item in posts]
            combined_score = round(sum(values) / len(values), 3)

        tone = "neutral"
        if combined_score > 0.15:
            tone = "positive"
        elif combined_score < -0.15:
            tone = "negative"

        summary = (
            f"Pre-market tone is {tone}. "
            f"Tracked {len(headlines)} headlines and {len(posts)} broker posts with composite sentiment {combined_score}."
        )
        return {
            "summary": summary,
            "composite_sentiment": combined_score,
            "headlines": headlines,
            "broker_posts": posts,
        }

    def _sample_headlines(self) -> list[dict[str, Any]]:
        samples = [
            ("Economic Times", "Banks lead early gains as PSU lenders see strong deposit growth."),
            ("Moneycontrol", "IT stocks lag while crude eases and global risk appetite improves."),
            ("CNBC-TV18", "NIFTY likely to open steady as traders watch US futures and rupee."),
            ("BloombergQuint", "Brokerages stay selective on autos after mixed monthly volume prints."),
        ]
        return [
            {
                "source": source,
                "title": title,
                "link": "",
                "sentiment": self.sentiment_score(title),
            }
            for source, title in samples
        ]

    def _sample_posts(self) -> list[dict[str, Any]]:
        samples = [
            "Verified broker desk: expect range-bound open unless banks extend momentum.",
            "Options desk note: watch 22150 CE and 22000 PE for first-hour liquidity.",
            "Broker commentary: fading stretched moves may work if breadth weakens after 10am.",
        ]
        return [
            {"source": "sample", "text": text, "sentiment": self.sentiment_score(text)}
            for text in samples
        ]
