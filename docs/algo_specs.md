# Algorithm Specifications

## Universe

- Index underlyings: `NIFTY`, `BANKNIFTY`
- Equity underlyings: top NSE stocks or screener-selected symbols
- Intraday only, no overnight carry

## Strategies

### Momentum Breakout

- Indicators: EMA 20, EMA 50, RSI 14, rolling volume average
- Long signal: EMA 20 crosses above EMA 50, RSI above threshold, volume spike, and close near breakout range
- Short signal: EMA 20 crosses below EMA 50, RSI below threshold, volume spike
- Default bar size: 5 minutes

### Opening Range Fade / Breakout

- Uses the first 15 minutes as the opening range
- `style=fader` is not used; the supported values are `fade` and `breakout`
- Fade long: price sweeps below opening low, closes back inside, and RSI is oversold
- Fade short: price sweeps above opening high, closes back inside, and RSI is overbought
- Breakout long: close above opening high with confirmation
- Breakout short: close below opening low with confirmation

### Mean Reversion Scalp

- Indicators: RSI and VWAP
- Long signal: RSI oversold and close materially below VWAP
- Short signal: RSI overbought and close materially above VWAP
- Default bar size: 1 minute for scalps, 5 minutes for broader mean reversion

## Position Sizing

- Prefer one lot if affordable and liquid
- Else step 1 to 3 strikes OTM until capital and liquidity constraints are met
- Quantity formula:
  - `qty = floor((capital * max_exposure_pct) / (premium * lot_size))`
- Stop loss:
  - `SL% = (rupee_stop / (premium * lot_size * qty)) * 100`
- Take profit:
  - `TP% = (rupee_take / (premium * lot_size * qty)) * 100`

## Risk Defaults

- Capital: `₹20,000`
- Per-trade rupee loss: `₹500`
- Daily rupee loss: `₹1,000`
- Auto square-off: `15:14 IST`
