# Architecture

## Overview

The platform is split into:

- FastAPI backend for orchestration, WebSocket streaming, order control, and reporting
- SQLite for cache, trades, orders, and risk recovery
- Strategy modules with a shared `generate_signals(df, config)` API
- A paper-first execution path guarded by `DISABLE_LIVE_TRADING`
- A React dashboard that consumes REST and WebSocket updates

## Order Flow

```mermaid
sequenceDiagram
    participant UI as Frontend Dashboard
    participant API as FastAPI
    participant Engine as Strategy Runner
    participant Risk as Risk Manager
    participant Order as Order Manager
    participant Broker as Upstox/Paper Broker
    participant DB as SQLite

    UI->>API: Enable strategy / run command
    API->>Engine: Evaluate latest candles
    Engine->>Risk: can_open_trade(exposure, rupee_risk)
    Risk->>DB: Load persisted state
    Risk-->>Engine: allow / deny
    Engine->>Order: place_order(...)
    Order->>DB: Check idempotency key
    alt Paper mode or live disabled
        Order->>Broker: Simulated fill using LTP + slippage
    else Live mode allowed
        Order->>Broker: Submit Upstox order
    end
    Broker-->>Order: Fill / reject
    Order->>DB: Persist order and position
    Order-->>Engine: Execution result
    Engine->>Risk: register_fill(trade)
    Risk->>DB: Persist risk snapshot
    API-->>UI: WebSocket update
```

## Risk Enforcement

```mermaid
sequenceDiagram
    participant Engine as Strategy Runner
    participant Risk as Risk Manager
    participant Order as Order Manager
    participant DB as SQLite

    Engine->>Risk: register_fill(trade)
    Risk->>Risk: Update realized PnL
    Risk->>DB: Save risk snapshot
    alt Daily loss >= limit
        Risk->>Risk: trading_halted = true
        Risk-->>Engine: Halt trading
        Engine->>Order: square_off_all()
        Order->>DB: Persist exits
    else Below limit
        Risk-->>Engine: Continue
    end
```

## Square-Off Flow

```mermaid
sequenceDiagram
    participant Scheduler as Session Monitor
    participant Order as Order Manager
    participant Broker as Upstox/Paper Broker
    participant DB as SQLite
    participant UI as Frontend Dashboard

    Scheduler->>Order: square_off_all()
    Order->>DB: Load active positions
    loop each active position
        Order->>Broker: Market exit request
        Broker-->>Order: Fill / failure
        Order->>DB: Persist order, trade exit, position update
    end
    Order-->>UI: Square-off result event
```

## Assumptions

- Market hours use NSE cash-session timing with auto square-off at `15:14 IST` by default.
- `NIFTY` and `BANKNIFTY` lot sizes can change over time, so the code first looks for broker or chain metadata and then falls back to a local mapping.
- Some remote endpoints differ by broker account tier or API version; where exact live behavior is uncertain, the code defaults to paper mode and includes clear TODOs.
