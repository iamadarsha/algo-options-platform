from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency at local runtime
    yaml = None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_or_default(name: str, default: Any) -> Any:
    value = os.getenv(name)
    return default if value is None else value


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve_env_placeholders(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return os.getenv(value[2:-1], "")
    if isinstance(value, dict):
        return {key: _resolve_env_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_env_placeholders(item) for item in value]
    return value


@dataclass
class UpstoxSettings:
    api_key: str = ""
    api_secret: str = ""
    access_token: str = ""
    redirect_uri: str = "http://localhost:8000/auth/upstox/callback"
    base_url: str = "https://api.upstox.com/v2"


@dataclass
class BacktestSettings:
    slippage_pct: float = 0.2
    commission_per_order: float = 20.0
    bar_size: str = "5m"
    out_of_sample_months: int = 3
    in_sample_months: int = 12


@dataclass
class AlertSettings:
    slack_webhook_url: str = ""
    alert_email_to: str = ""
    sentry_dsn: str = ""
    prometheus_enabled: bool = False


@dataclass
class AppConfig:
    capital: float = 20000.0
    daily_loss_limit: float = 1000.0
    per_trade_loss_limit: float = 500.0
    max_exposure_pct: float = 0.9
    default_strategy: str = "momentum"
    square_off_time: str = "15:14"
    market_close_time: str = "15:29"
    timezone: str = "Asia/Kolkata"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./backend/app/data/algo_platform.db"
    disable_live_trading: bool = True
    paper_trading: bool = True
    request_timeout: int = 6
    data_cache_ttl_seconds: int = 60
    options_cache_ttl_seconds: int = 20
    poll_interval_seconds: int = 1
    universe: list[str] = field(
        default_factory=lambda: ["NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK", "ICICIBANK"]
    )
    strategy_params: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    upstox: UpstoxSettings = field(default_factory=UpstoxSettings)
    backtest: BacktestSettings = field(default_factory=BacktestSettings)
    alerts: AlertSettings = field(default_factory=AlertSettings)

    backend_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    project_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2])

    def __post_init__(self) -> None:
        self.runtime_dir = self.backend_dir / "runtime"
        self.data_dir = self.backend_dir / "app" / "data"
        self.logs_dir = self.runtime_dir / "logs"
        self.morning_report_path = self.runtime_dir / "morning_report.json"
        self.trade_log_path = self.runtime_dir / "trades.csv"
        self.summary_path = self.runtime_dir / "backtest_summary.json"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    @property
    def sqlite_path(self) -> Path:
        if self.database_url.startswith("sqlite:///"):
            raw_path = self.database_url.replace("sqlite:///", "", 1)
            return (self.project_dir / raw_path).resolve()
        return (self.data_dir / "algo_platform.db").resolve()

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["backend_dir"] = str(self.backend_dir)
        payload["project_dir"] = str(self.project_dir)
        payload["runtime_dir"] = str(self.runtime_dir)
        payload["data_dir"] = str(self.data_dir)
        payload["logs_dir"] = str(self.logs_dir)
        payload["morning_report_path"] = str(self.morning_report_path)
        payload["trade_log_path"] = str(self.trade_log_path)
        payload["summary_path"] = str(self.summary_path)
        payload["sqlite_path"] = str(self.sqlite_path)
        return payload


DEFAULT_STRATEGY_PARAMS: Dict[str, Dict[str, Any]] = {
    "momentum": {
        "ema_fast": 20,
        "ema_slow": 50,
        "rsi_period": 14,
        "rsi_long": 58,
        "rsi_short": 42,
        "volume_window": 20,
        "volume_spike_mult": 1.4,
        "breakout_lookback": 12,
        "reward_multiple": 1.5,
    },
    "opening_range_fade": {
        "opening_range_minutes": 15,
        "style": "fade",
        "rsi_period": 14,
        "rsi_oversold": 35,
        "rsi_overbought": 65,
        "volume_spike_mult": 1.2,
        "reward_multiple": 1.3,
    },
    "mean_reversion": {
        "rsi_period": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "vwap_band_pct": 0.003,
        "reward_multiple": 1.2,
    },
}


def default_config_payload() -> Dict[str, Any]:
    return {
        "capital": 20000,
        "daily_loss_limit": 1000,
        "per_trade_loss_limit": 500,
        "max_exposure_pct": 0.9,
        "default_strategy": "momentum",
        "square_off_time": "15:14",
        "market_close_time": "15:29",
        "timezone": "Asia/Kolkata",
        "app_env": _env_or_default("APP_ENV", "development"),
        "log_level": _env_or_default("LOG_LEVEL", "INFO"),
        "database_url": _env_or_default("DATABASE_URL", "sqlite:///./backend/app/data/algo_platform.db"),
        "disable_live_trading": _coerce_bool(_env_or_default("DISABLE_LIVE_TRADING", True)),
        "paper_trading": _coerce_bool(_env_or_default("PAPER_TRADING", True)),
        "request_timeout": int(_env_or_default("NEWS_REQUEST_TIMEOUT", 6)),
        "data_cache_ttl_seconds": int(_env_or_default("DATA_CACHE_TTL_SECONDS", 60)),
        "options_cache_ttl_seconds": int(_env_or_default("OPTIONS_CACHE_TTL_SECONDS", 20)),
        "poll_interval_seconds": 1,
        "universe": ["NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK", "ICICIBANK"],
        "strategy_params": DEFAULT_STRATEGY_PARAMS,
        "upstox": {
            "api_key": _env_or_default("UPSTOX_API_KEY", ""),
            "api_secret": _env_or_default("UPSTOX_API_SECRET", ""),
            "access_token": _env_or_default("UPSTOX_ACCESS_TOKEN", ""),
            "redirect_uri": _env_or_default("UPSTOX_REDIRECT_URI", "http://localhost:8000/auth/upstox/callback"),
            "base_url": "https://api.upstox.com/v2",
        },
        "backtest": {
            "slippage_pct": float(_env_or_default("BACKTEST_SLIPPAGE_PCT", 0.2)),
            "commission_per_order": float(_env_or_default("BACKTEST_COMMISSION_PER_ORDER", 20)),
            "bar_size": _env_or_default("BACKTEST_BAR_SIZE", "5m"),
            "out_of_sample_months": 3,
            "in_sample_months": 12,
        },
        "alerts": {
            "slack_webhook_url": _env_or_default("SLACK_WEBHOOK_URL", ""),
            "alert_email_to": _env_or_default("ALERT_EMAIL_TO", ""),
            "sentry_dsn": _env_or_default("SENTRY_DSN", ""),
            "prometheus_enabled": _coerce_bool(_env_or_default("PROMETHEUS_ENABLED", False)),
        },
    }


def load_config(config_path: Optional[str | Path] = None) -> AppConfig:
    payload = default_config_payload()
    if config_path:
        config_file = Path(config_path)
        if not config_file.is_absolute():
            candidates = [
                (Path.cwd() / config_file).resolve(),
                (Path(__file__).resolve().parent.parent / config_file).resolve(),
                (Path(__file__).resolve().parent / config_file).resolve(),
                (Path(__file__).resolve().parents[2] / config_file).resolve(),
            ]
            config_file = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
        if config_file.exists() and yaml is not None:
            with config_file.open("r", encoding="utf-8") as handle:
                file_payload = _resolve_env_placeholders(yaml.safe_load(handle) or {})
            payload = _deep_merge(payload, file_payload)

    payload["capital"] = float(_env_or_default("CAPITAL", payload["capital"]))
    payload["daily_loss_limit"] = float(_env_or_default("DAILY_LOSS_LIMIT", payload["daily_loss_limit"]))
    payload["per_trade_loss_limit"] = float(
        _env_or_default("PER_TRADE_LOSS_LIMIT", payload["per_trade_loss_limit"])
    )
    payload["max_exposure_pct"] = float(_env_or_default("MAX_EXPOSURE_PCT", payload["max_exposure_pct"]))

    payload["upstox"] = UpstoxSettings(**payload.get("upstox", {}))
    payload["backtest"] = BacktestSettings(**payload.get("backtest", {}))
    payload["alerts"] = AlertSettings(**payload.get("alerts", {}))
    return AppConfig(**payload)
