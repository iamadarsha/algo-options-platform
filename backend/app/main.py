from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime, time, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

import pandas as pd

try:  # pragma: no cover - optional for CLI-only environments
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover - optional for CLI-only environments
    FastAPI = None
    HTTPException = None
    WebSocket = None
    WebSocketDisconnect = Exception
    CORSMiddleware = None

    class BaseModel:  # type: ignore[override]
        pass

    def Field(*_args: Any, **_kwargs: Any) -> None:
        return None

from app.backtest.backtester import Backtester
from app.config import AppConfig, load_config
from app.controllers.data_ingest import DataIngestController
from app.controllers.news_fetcher import NewsFetcher
from app.controllers.order_manager import OrderManager
from app.controllers.risk_manager import RiskManager
from app.controllers.screener import ScreenerConnector
from app.controllers.strategy_runner import create_strategy
from app.storage.sqlite_store import SQLiteStore
from app.utils.metrics import calculate_performance_metrics, json_ready_metrics


LOGGER = logging.getLogger(__name__)


class StrategyExportPayload(BaseModel):
    name: str = Field(default="custom_strategy")
    config: dict[str, Any]


class DailyTaskScheduler:
    """A minimal pre-market scheduler suitable for local runs and demos."""

    def __init__(self, services: dict[str, Any]) -> None:
        self.services = services
        self.last_run_date: Optional[str] = None

    def run_if_due(self, now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
        now = now or datetime.now()
        if now.time() < time(hour=8, minute=45):
            return None
        today = now.date().isoformat()
        if self.last_run_date == today:
            return None
        self.last_run_date = today
        return generate_morning_report(self.services, force_refresh=False)


def configure_logging(config: AppConfig) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(config.logs_dir / "platform.log", maxBytes=1_000_000, backupCount=5)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def build_services(config_path: Optional[str] = None) -> dict[str, Any]:
    config = load_config(config_path)
    configure_logging(config)
    store = SQLiteStore(config.sqlite_path)
    data_ingest = DataIngestController(config, store)
    news_fetcher = NewsFetcher(config, store)
    screener = ScreenerConnector(config, store)
    risk_manager = RiskManager(
        store=store,
        capital=config.capital,
        daily_loss_limit=config.daily_loss_limit,
        per_trade_loss_limit=config.per_trade_loss_limit,
    )
    order_manager = OrderManager(
        config=config,
        store=store,
        data_ingest=data_ingest,
        paper_mode=(config.paper_trading or config.disable_live_trading),
    )
    backtester = Backtester(config)
    services = {
        "config": config,
        "store": store,
        "data_ingest": data_ingest,
        "news_fetcher": news_fetcher,
        "screener": screener,
        "risk_manager": risk_manager,
        "order_manager": order_manager,
        "backtester": backtester,
    }
    services["scheduler"] = DailyTaskScheduler(services)
    return services


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)


def generate_morning_report(services: dict[str, Any], force_refresh: bool = False) -> dict[str, Any]:
    config: AppConfig = services["config"]
    data_ingest: DataIngestController = services["data_ingest"]
    news_fetcher: NewsFetcher = services["news_fetcher"]
    screener: ScreenerConnector = services["screener"]
    store: SQLiteStore = services["store"]

    market_summary = data_ingest.market_summary()
    news_summary = news_fetcher.build_premarket_summary()
    candidates = screener.get_daily_candidates(force_refresh=force_refresh)
    shortlist = [candidate["symbol"] for candidate in candidates[:3]]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_summary": market_summary,
        "news": news_summary,
        "candidates": candidates,
        "shortlist": shortlist,
        "text_summary": (
            f"Morning report: shortlist {', '.join(shortlist)}. "
            f"Sentiment {news_summary['composite_sentiment']}, "
            f"SGX Nifty {market_summary['sgx_nifty']['value']}."
        ),
    }
    store.save_report("morning_report", report)
    _write_json(config.morning_report_path, report)
    return report


def build_runtime_state(services: dict[str, Any]) -> dict[str, Any]:
    config: AppConfig = services["config"]
    store: SQLiteStore = services["store"]
    risk_manager: RiskManager = services["risk_manager"]
    order_manager: OrderManager = services["order_manager"]
    morning_report = store.load_report("morning_report") or {}
    trades = store.list_trades()[-20:]
    positions = []
    for position in order_manager.get_positions():
        avg_price = float(position["avg_price"])
        ltp = avg_price
        diff_from_entry = round(ltp - avg_price, 2)
        pnl = round(diff_from_entry * float(position["qty"]), 2)
        positions.append({**position, "ltp": ltp, "diff_from_entry": diff_from_entry, "pnl": pnl})
    return {
        "mode": "paper" if order_manager.paper_mode or config.disable_live_trading else "live",
        "risk": risk_manager.snapshot(),
        "positions": positions,
        "active_trades": [trade for trade in trades if trade.get("status") == "open"],
        "recent_trades": trades[-10:],
        "morning_report": morning_report,
        "alerts": order_manager.alerts,
    }


def run_mode(
    services: dict[str, Any],
    mode: str,
    strategy_name: str,
    start: str,
    end: str,
    force_refresh: bool = False,
    simulate_loss_streak: int = 0,
) -> dict[str, Any]:
    config: AppConfig = services["config"]
    data_ingest: DataIngestController = services["data_ingest"]
    risk_manager: RiskManager = services["risk_manager"]
    order_manager: OrderManager = services["order_manager"]
    store: SQLiteStore = services["store"]
    backtester: Backtester = services["backtester"]

    services["risk_manager"] = RiskManager(
        store=store,
        capital=config.capital,
        daily_loss_limit=config.daily_loss_limit,
        per_trade_loss_limit=config.per_trade_loss_limit,
        trading_day=str(start),
    )
    risk_manager = services["risk_manager"]

    report = generate_morning_report(services, force_refresh=force_refresh)
    if mode == "live" and config.disable_live_trading:
        order_manager.alerts.append("Live mode requested but DISABLE_LIVE_TRADING=true. Falling back to paper mode.")
        mode = "paper"

    strategy = create_strategy(strategy_name, config)
    bar_size = "1m" if strategy_name == "mean_reversion" else config.backtest.bar_size
    bars = data_ingest.get_historical_bars("NIFTY", interval=bar_size, start=start, end=end, force_refresh=force_refresh)

    if mode == "backtest":
        result = backtester.run(bars, strategy, underlying="NIFTY", capital=config.capital)
        trades_df = result.trades
        signals = result.signals
        equity_curve = result.equity_curve
    else:
        session = strategy.run_intraday_session(
            bars,
            underlying="NIFTY",
            risk_manager=risk_manager,
            order_manager=order_manager,
            store=store,
        )
        trades_df = session["trades"]
        signals = session["signals"]
        equity_curve = session["equity_curve"]

    metrics = calculate_performance_metrics(
        equity_curve=equity_curve,
        trades=trades_df if not trades_df.empty else pd.DataFrame(columns=["pl", "closed_at"]),
        start_capital=config.capital,
    )

    if simulate_loss_streak > 0:
        for index in range(10):
            if index >= simulate_loss_streak and risk_manager.state.trading_halted:
                break
            risk_manager.register_fill(
                {
                    "pl": -config.per_trade_loss_limit,
                    "reason": f"simulated_loss_{index + 1}",
                }
            )
            if risk_manager.state.trading_halted:
                order_manager.alerts.append("Trading halted after simulated cumulative losses breached the daily limit.")
                break

    walk_forward = backtester.walk_forward(bars, strategy, underlying="NIFTY")
    monte_carlo = backtester.monte_carlo(trades_df if not trades_df.empty else pd.DataFrame(columns=["pl"]))
    backtester.export_trade_log(trades_df, str(config.trade_log_path))

    summary = {
        "mode": mode,
        "strategy": strategy_name,
        "report_path": str(config.morning_report_path),
        "trade_log_path": str(config.trade_log_path),
        "metrics": json_ready_metrics(metrics),
        "walk_forward": walk_forward,
        "monte_carlo": monte_carlo,
        "trading_halted": risk_manager.state.trading_halted,
        "risk": risk_manager.snapshot(),
        "signal_count": int((signals["signal"] != 0).sum()),
        "trade_count": int(len(trades_df)),
        "morning_report": report,
    }
    _write_json(config.summary_path, summary)
    return summary


def create_app(config_path: Optional[str] = None) -> FastAPI:
    if FastAPI is None or CORSMiddleware is None:
        raise RuntimeError("FastAPI and pydantic are required to run the API server")

    services = build_services(config_path)
    app = FastAPI(title="Algo Platform", version="1.0.0")
    app.state.services = services

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup() -> None:
        scheduler: DailyTaskScheduler = app.state.services["scheduler"]
        scheduler.run_if_due()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/state")
    async def state() -> dict[str, Any]:
        return build_runtime_state(app.state.services)

    @app.get("/api/morning-report")
    async def morning_report() -> dict[str, Any]:
        report = app.state.services["store"].load_report("morning_report")
        if report is None:
            report = generate_morning_report(app.state.services, force_refresh=False)
        return report

    @app.post("/api/control/pause")
    async def pause_trading() -> dict[str, Any]:
        app.state.services["risk_manager"].enforce_stop()
        return build_runtime_state(app.state.services)

    @app.post("/api/control/resume")
    async def resume_trading() -> dict[str, Any]:
        app.state.services["risk_manager"].resume()
        return build_runtime_state(app.state.services)

    @app.post("/api/control/square-off")
    async def square_off() -> dict[str, Any]:
        results = app.state.services["order_manager"].square_off_all()
        return {"results": results, "state": build_runtime_state(app.state.services)}

    @app.post("/api/strategy/export")
    async def export_strategy(payload: StrategyExportPayload) -> dict[str, Any]:
        config: AppConfig = app.state.services["config"]
        export_path = config.runtime_dir / f"{payload.name}.json"
        _write_json(export_path, {"name": payload.name, "config": payload.config})
        return {"saved_to": str(export_path)}

    @app.post("/api/run/{mode}")
    async def trigger_run(mode: str, strategy: str = "momentum") -> dict[str, Any]:
        if mode not in {"paper", "live", "backtest"}:
            raise HTTPException(status_code=400, detail="Invalid mode")
        today = datetime.now().date().isoformat()
        return run_mode(app.state.services, mode=mode, strategy_name=strategy, start=today, end=today)

    @app.websocket("/ws/live")
    async def websocket_live(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                scheduler: DailyTaskScheduler = app.state.services["scheduler"]
                scheduler.run_if_due()
                await websocket.send_json(build_runtime_state(app.state.services))
                await asyncio.sleep(app.state.services["config"].poll_interval_seconds)
        except WebSocketDisconnect:
            return

    return app


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Algo Platform CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run paper/live/backtest workflow")
    run_parser.add_argument("--mode", choices=["paper", "live", "backtest"], required=True)
    run_parser.add_argument("--strategy", default="momentum")
    run_parser.add_argument("--start", required=True)
    run_parser.add_argument("--end", required=True)
    run_parser.add_argument("--config", default="app/config.yml")
    run_parser.add_argument("--force-refresh", action="store_true")
    run_parser.add_argument("--simulate-loss-streak", type=int, default=0)

    report_parser = subparsers.add_parser("morning-report", help="Generate morning report JSON")
    report_parser.add_argument("--config", default="app/config.yml")
    report_parser.add_argument("--force-refresh", action="store_true")

    serve_parser = subparsers.add_parser("serve", help="Run FastAPI server")
    serve_parser.add_argument("--config", default="app/config.yml")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)

    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.command == "serve":
        import uvicorn

        uvicorn.run(create_app(args.config), host=args.host, port=args.port, reload=False)
        return

    services = build_services(args.config)

    if args.command == "morning-report":
        report = generate_morning_report(services, force_refresh=args.force_refresh)
        print(json.dumps(report, indent=2))
        return

    if args.command == "run":
        summary = run_mode(
            services,
            mode=args.mode,
            strategy_name=args.strategy,
            start=args.start,
            end=args.end,
            force_refresh=args.force_refresh,
            simulate_loss_streak=args.simulate_loss_streak,
        )
        print(json.dumps(summary, indent=2))


try:  # pragma: no cover - optional when API dependencies are not installed locally
    app = create_app()
except Exception:
    app = None


if __name__ == "__main__":
    main()
