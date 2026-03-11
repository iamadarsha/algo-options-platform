from __future__ import annotations

import logging
from datetime import datetime
from random import Random
from typing import Any, Optional
from uuid import uuid4

import requests

from app.config import AppConfig
from app.controllers.data_ingest import DataIngestController
from app.storage.sqlite_store import SQLiteStore


LOGGER = logging.getLogger(__name__)


class OrderManager:
    """Broker wrapper with idempotency, optimistic locking, and paper fills."""

    def __init__(
        self,
        config: AppConfig,
        store: SQLiteStore,
        data_ingest: DataIngestController,
        paper_mode: Optional[bool] = None,
    ) -> None:
        self.config = config
        self.store = store
        self.data_ingest = data_ingest
        self.paper_mode = config.paper_trading if paper_mode is None else paper_mode
        self.alerts: list[str] = []
        self.session = requests.Session()

    def place_order(
        self,
        instrument: str,
        qty: int,
        order_type: str,
        price: float,
        product: str = "INTRADAY",
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        side: str = "BUY",
        idempotency_key: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if idempotency_key:
            existing = self.store.get_order_by_idempotency(idempotency_key)
            if existing:
                return existing

        paper_mode = self.paper_mode or self.config.disable_live_trading
        order_id = str(uuid4())
        fill_price = price
        status = "FILLED"
        meta = meta or {}

        if paper_mode:
            fill_price = self._simulate_fill_price(order_id, instrument, price, side, meta)
        else:
            try:
                live_response = self._submit_upstox_order(
                    instrument=instrument,
                    qty=qty,
                    order_type=order_type,
                    price=price,
                    product=product,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    side=side,
                )
                fill_price = live_response.get("fill_price", price)
                status = live_response.get("status", "SUBMITTED")
            except Exception as exc:  # pragma: no cover - live path
                status = "FILLED"
                paper_mode = True
                fill_price = self._simulate_fill_price(order_id, instrument, price, side, meta)
                self.alerts.append(f"Live order failed, used paper mode fallback: {exc}")
                LOGGER.warning("Falling back to paper mode for %s due to %s", instrument, exc)

        order = {
            "order_id": order_id,
            "idempotency_key": idempotency_key,
            "instrument": instrument,
            "side": side,
            "qty": int(qty),
            "order_type": order_type.upper(),
            "requested_price": float(price),
            "fill_price": float(fill_price),
            "status": status,
            "product": product,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "paper_mode": paper_mode,
            "version": 0,
            "meta": meta,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        self.store.save_order(order)

        if status in {"FILLED", "COMPLETE"}:
            self._apply_position(order)
        return order

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        order = self.store.get_order(order_id)
        if not order:
            return {"order_id": order_id, "status": "NOT_FOUND"}

        updated = self.store.update_order(order_id, int(order["version"]), status="CANCELLED")
        if not updated:
            return {"order_id": order_id, "status": "STALE_VERSION"}
        order = self.store.get_order(order_id) or order
        return order

    def get_positions(self) -> list[dict[str, Any]]:
        return self.store.list_positions()

    def square_off_all(self) -> list[dict[str, Any]]:
        results = []
        for position in self.get_positions():
            opposite_side = "SELL" if position["side"] == "BUY" else "BUY"
            order = self.place_order(
                instrument=position["instrument"],
                qty=position["qty"],
                order_type="MARKET",
                price=float(position["avg_price"]),
                side=opposite_side,
                idempotency_key=f"squareoff:{position['instrument']}",
                meta={"reason": "square_off"},
            )
            results.append(order)
        return results

    def _apply_position(self, order: dict[str, Any]) -> None:
        side = order["side"].upper()
        if side == "BUY":
            self.store.upsert_position(
                order["instrument"],
                qty=int(order["qty"]),
                avg_price=float(order["fill_price"]),
                side="BUY",
                meta=order.get("meta", {}),
            )
        else:
            self.store.remove_position(order["instrument"])

    def _simulate_fill_price(
        self,
        order_id: str,
        instrument: str,
        requested_price: float,
        side: str,
        meta: Optional[dict[str, Any]] = None,
    ) -> float:
        base_price = requested_price
        meta = meta or {}
        if "ltp" in meta:
            base_price = float(meta["ltp"])
        rng = Random(order_id)
        slip_pct = rng.uniform(0.1, 0.5) / 100.0
        if side.upper() == "BUY":
            return round(base_price * (1 + slip_pct), 2)
        return round(base_price * (1 - slip_pct), 2)

    def _submit_upstox_order(self, **payload: Any) -> dict[str, Any]:
        if self.config.disable_live_trading:
            raise RuntimeError("DISABLE_LIVE_TRADING is enabled")
        if not self.config.upstox.access_token:
            raise RuntimeError("Missing Upstox access token")

        url = f"{self.config.upstox.base_url}/order/place"
        headers = {
            "Authorization": f"Bearer {self.config.upstox.access_token}",
            "Content-Type": "application/json",
        }
        live_payload = {
            "instrument_token": payload["instrument"],
            "quantity": payload["qty"],
            "order_type": payload["order_type"],
            "price": payload["price"],
            "product": payload.get("product", "INTRADAY"),
            "transaction_type": payload.get("side", "BUY"),
        }
        # TODO: verify the exact Upstox live payload keys before production use.
        response = self.session.post(url, json=live_payload, headers=headers, timeout=self.config.request_timeout)
        response.raise_for_status()
        data = response.json()
        return {
            "status": data.get("status", "SUBMITTED"),
            "fill_price": data.get("data", {}).get("average_price", payload["price"]),
        }
