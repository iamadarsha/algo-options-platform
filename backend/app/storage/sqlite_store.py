from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteStore:
    """Tiny persistence layer for cache, orders, trades, and risk state."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.database_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_database(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    expires_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS risk_state (
                    trading_day TEXT PRIMARY KEY,
                    capital REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    daily_loss_limit REAL NOT NULL,
                    per_trade_loss_limit REAL NOT NULL,
                    trading_halted INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    instrument TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    order_type TEXT NOT NULL,
                    requested_price REAL,
                    fill_price REAL,
                    status TEXT NOT NULL,
                    product TEXT NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    paper_mode INTEGER NOT NULL,
                    version INTEGER NOT NULL DEFAULT 0,
                    meta_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS positions (
                    instrument TEXT PRIMARY KEY,
                    qty INTEGER NOT NULL,
                    avg_price REAL NOT NULL,
                    side TEXT NOT NULL,
                    meta_json TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    order_id TEXT,
                    strategy TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    pl REAL NOT NULL,
                    sl REAL,
                    tp REAL,
                    reason TEXT,
                    status TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT NOT NULL,
                    meta_json TEXT
                );

                CREATE TABLE IF NOT EXISTS reports (
                    report_name TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def cache_get(self, key: str) -> Optional[Any]:
        with self.connection() as conn:
            row = conn.execute("SELECT payload, expires_at FROM cache WHERE key = ?", (key,)).fetchone()
            if row is None:
                return None
            expires_at = row["expires_at"]
            if expires_at and datetime.fromisoformat(expires_at) < datetime.now(timezone.utc):
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                return None
            return json.loads(row["payload"])

    def cache_set(self, key: str, payload: Any, ttl_seconds: int) -> None:
        expires_at = datetime.now(timezone.utc).timestamp() + max(ttl_seconds, 0)
        expiry = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()
        now = _utc_now()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO cache(key, payload, expires_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    payload = excluded.payload,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(payload), expiry, now),
            )

    def load_risk_state(self, trading_day: str) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM risk_state WHERE trading_day = ?", (trading_day,)).fetchone()
            return dict(row) if row else None

    def save_risk_state(self, state: Dict[str, Any]) -> None:
        now = _utc_now()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO risk_state(
                    trading_day, capital, realized_pnl, daily_loss_limit,
                    per_trade_loss_limit, trading_halted, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trading_day) DO UPDATE SET
                    capital = excluded.capital,
                    realized_pnl = excluded.realized_pnl,
                    daily_loss_limit = excluded.daily_loss_limit,
                    per_trade_loss_limit = excluded.per_trade_loss_limit,
                    trading_halted = excluded.trading_halted,
                    updated_at = excluded.updated_at
                """,
                (
                    state["trading_day"],
                    state["capital"],
                    state["realized_pnl"],
                    state["daily_loss_limit"],
                    state["per_trade_loss_limit"],
                    int(state["trading_halted"]),
                    now,
                ),
            )

    def save_order(self, order: Dict[str, Any]) -> None:
        now = _utc_now()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO orders(
                    order_id, idempotency_key, instrument, side, qty, order_type,
                    requested_price, fill_price, status, product, stop_loss, take_profit,
                    paper_mode, version, meta_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    fill_price = excluded.fill_price,
                    status = excluded.status,
                    stop_loss = excluded.stop_loss,
                    take_profit = excluded.take_profit,
                    version = excluded.version,
                    meta_json = excluded.meta_json,
                    updated_at = excluded.updated_at
                """,
                (
                    order["order_id"],
                    order.get("idempotency_key"),
                    order["instrument"],
                    order["side"],
                    order["qty"],
                    order["order_type"],
                    order.get("requested_price"),
                    order.get("fill_price"),
                    order["status"],
                    order.get("product", "INTRADAY"),
                    order.get("stop_loss"),
                    order.get("take_profit"),
                    int(order.get("paper_mode", True)),
                    int(order.get("version", 0)),
                    json.dumps(order.get("meta", {})),
                    order.get("created_at", now),
                    order.get("updated_at", now),
                ),
            )

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
            return dict(row) if row else None

    def get_order_by_idempotency(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM orders WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            return dict(row) if row else None

    def update_order(self, order_id: str, expected_version: int, **fields: Any) -> bool:
        existing = self.get_order(order_id)
        if not existing or int(existing["version"]) != expected_version:
            return False

        merged = dict(existing)
        merged.update(fields)
        merged["version"] = expected_version + 1
        self.save_order(merged)
        return True

    def upsert_position(self, instrument: str, qty: int, avg_price: float, side: str, meta: Optional[Dict[str, Any]] = None) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO positions(instrument, qty, avg_price, side, meta_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument) DO UPDATE SET
                    qty = excluded.qty,
                    avg_price = excluded.avg_price,
                    side = excluded.side,
                    meta_json = excluded.meta_json,
                    updated_at = excluded.updated_at
                """,
                (instrument, qty, avg_price, side, json.dumps(meta or {}), _utc_now()),
            )

    def remove_position(self, instrument: str) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM positions WHERE instrument = ?", (instrument,))

    def list_positions(self) -> list[Dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM positions ORDER BY instrument").fetchall()
            return [dict(row) for row in rows]

    def save_trade(self, trade: Dict[str, Any]) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO trades(
                    trade_id, order_id, strategy, instrument, side, qty,
                    entry_price, exit_price, pl, sl, tp, reason, status,
                    opened_at, closed_at, meta_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_id) DO UPDATE SET
                    exit_price = excluded.exit_price,
                    pl = excluded.pl,
                    reason = excluded.reason,
                    status = excluded.status,
                    closed_at = excluded.closed_at,
                    meta_json = excluded.meta_json
                """,
                (
                    trade["trade_id"],
                    trade.get("order_id"),
                    trade["strategy"],
                    trade["instrument"],
                    trade["side"],
                    trade["qty"],
                    trade["entry_price"],
                    trade["exit_price"],
                    trade["pl"],
                    trade.get("sl"),
                    trade.get("tp"),
                    trade.get("reason"),
                    trade.get("status", "closed"),
                    trade["opened_at"],
                    trade["closed_at"],
                    json.dumps(trade.get("meta", {})),
                ),
            )

    def list_trades(self) -> list[Dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM trades ORDER BY opened_at").fetchall()
            return [dict(row) for row in rows]

    def save_report(self, report_name: str, payload: Any) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO reports(report_name, payload, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(report_name) DO UPDATE SET
                    payload = excluded.payload,
                    created_at = excluded.created_at
                """,
                (report_name, json.dumps(payload), _utc_now()),
            )

    def load_report(self, report_name: str) -> Optional[Any]:
        with self.connection() as conn:
            row = conn.execute("SELECT payload FROM reports WHERE report_name = ?", (report_name,)).fetchone()
            return json.loads(row["payload"]) if row else None

    def dump_table(self, table_name: str) -> Iterable[Dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
            return [dict(row) for row in rows]
