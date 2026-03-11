# Algo Platform

Intraday options trading platform for Indian markets with a safe paper-trading default, guarded Upstox live execution, SQLite persistence, vectorized backtesting, morning reports, and a React dashboard.

## Features

- Paper trading by default with randomized slippage and idempotent order handling
- Upstox integration behind `DISABLE_LIVE_TRADING` and environment-based secrets
- Data ingestion for historical candles, LTP polling, options chain snapshots, news, and screeners
- Modular strategy engine:
  - Momentum breakout
  - Opening-range fade / breakout-style intraday logic
  - Mean reversion scalp
- Risk controls:
  - Capital-aware sizing
  - Per-trade loss cap
  - Daily hard-stop at `₹1000`
  - Automatic square-off before market close
- Vectorized backtester with walk-forward and Monte Carlo resampling
- FastAPI + WebSocket backend and React dashboard
- Docker, GitHub Actions, and unit tests

## Repo Layout

```text
algo-platform/
├─ backend/
├─ frontend/
├─ infra/
├─ docs/
└─ examples/
```

## Quick Start

### 1. Create environment file

```bash
cp .env.example .env
```

Set at minimum:

```env
DISABLE_LIVE_TRADING=true
APP_ENV=development
DATABASE_URL=sqlite:///./backend/app/data/algo_platform.db
CAPITAL=20000
DAILY_LOSS_LIMIT=1000
PER_TRADE_LOSS_LIMIT=500
```

### 2. Run with Docker

```bash
docker compose up --build
```

Backend API starts on `http://localhost:8000` and the frontend dev server on `http://localhost:5173`.

### 3. Run locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests
python -m app.main run --mode paper --strategy momentum --start 2026-03-10 --end 2026-03-10 --config app/config.yml
```

### 4. One-day paper simulation

```bash
./examples/run_paper.sh
```

This generates:

- `backend/runtime/morning_report.json`
- `backend/runtime/trades.csv`
- `backend/runtime/backtest_summary.json`

## Upstox Setup

1. Create an Upstox developer app.
2. Add your redirect URI in the Upstox console.
3. Put credentials in `.env`:
   - `UPSTOX_API_KEY`
   - `UPSTOX_API_SECRET`
   - `UPSTOX_ACCESS_TOKEN`
4. Keep `DISABLE_LIVE_TRADING=true` until you have validated paper mode.
5. Review [docs/upstox_integration.md](docs/upstox_integration.md) for the OAuth/token flow and live-trading safeguards.

## CLI

```bash
python -m app.main run --mode live|paper|backtest --strategy momentum --start 2026-01-01 --end 2026-03-01 --config app/config.yml
```

Modes:

- `paper`: safe default, simulates fills using market data or synthetic candles
- `live`: requires valid Upstox credentials and `DISABLE_LIVE_TRADING=false`
- `backtest`: runs historical simulation and exports metrics/trades

## Backtesting

The backtester supports:

- Minute-bar simulation
- Slippage and commissions
- Market, limit, and stop logic
- Walk-forward evaluation
- Monte Carlo resampling
- CSV trade log export

Key metrics:

- Total return
- CAGR
- Sharpe ratio
- Sortino ratio
- Max drawdown
- Win rate
- Profit factor
- Max consecutive losses
- Daily PnL distribution

## Risk Rules

Default configuration:

- Capital: `₹20,000`
- Max per-trade rupee loss: `₹500`
- Max daily rupee loss: `₹1000`
- No overnight positions
- Auto square-off near market close (`15:14 IST` by default)

Sizing formulas:

- `max_qty = floor((capital * max_exposure_pct) / (premium * lot_size))`
- `SL% = rupee_stop / (premium * lot_size * qty) * 100`
- `TP% = rupee_target / (premium * lot_size * qty) * 100`

## Morning Report

Daily pre-market tasks produce a JSON morning report including:

- Market cues
- News sentiment summary
- Screener candidates
- Optional shortlist for the day

## Testing

```bash
cd backend
python -m unittest discover -s tests
```

GitHub Actions installs dependencies, runs tests, and builds the Docker image on every push.

## Safety

- Secrets are loaded only from environment variables
- API retries use exponential backoff
- Live-trading calls never run when `DISABLE_LIVE_TRADING=true`
- On API or network failures, the platform falls back to paper mode and surfaces alerts
- Logs redact sensitive credentials

## Disclaimer

This project is educational infrastructure for strategy research and controlled execution workflows. It does not guarantee profits or suitability for any market condition. You are responsible for validating strategies, brokerage behavior, taxes, compliance, and operational risk before using live capital.
