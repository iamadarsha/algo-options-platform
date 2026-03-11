const STRATEGY_LABELS = {
  momentum: 'Momentum Breakout',
  opening_range_fade: 'Opening Range Fade',
  mean_reversion: 'Mean Reversion',
};

function formatMoney(value) {
  const number = Number(value || 0);
  return `₹${number.toFixed(2)}`;
}

export default function Dashboard({
  state,
  morningReport,
  strategyToggles,
  setStrategyToggles,
  onPause,
  onResume,
  onSquareOff,
}) {
  const risk = state?.risk || {};
  const marketSummary = morningReport?.market_summary || {};
  const recentTrades = state?.recent_trades || [];
  const positions = state?.positions || [];

  return (
    <section className="dashboard-grid">
      <article className="card card-market">
        <div className="card-header">
          <h2>Market Summary</h2>
          <span className="mono">{morningReport?.generated_at || 'pending'}</span>
        </div>
        <div className="market-stats">
          <div>
            <span>SGX Nifty</span>
            <strong>{marketSummary?.sgx_nifty?.value || '--'}</strong>
          </div>
          <div>
            <span>US Futures</span>
            <strong>{marketSummary?.us_futures?.value || '--'}</strong>
          </div>
          <div>
            <span>Crude</span>
            <strong>{marketSummary?.crude?.value || '--'}</strong>
          </div>
        </div>
        <ul className="cue-list">
          {(marketSummary?.global_cues || []).map((cue) => (
            <li key={cue}>{cue}</li>
          ))}
        </ul>
      </article>

      <article className="card">
        <div className="card-header">
          <h2>Strategies</h2>
          <span className="mono">live toggles</span>
        </div>
        <div className="strategy-list">
          {Object.entries(STRATEGY_LABELS).map(([key, label]) => (
            <label key={key} className="strategy-row">
              <span>{label}</span>
              <input
                type="checkbox"
                checked={strategyToggles[key]}
                onChange={() =>
                  setStrategyToggles((current) => ({
                    ...current,
                    [key]: !current[key],
                  }))
                }
              />
            </label>
          ))}
        </div>
      </article>

      <article className="card">
        <div className="card-header">
          <h2>Risk Meter</h2>
          <span className={`pill ${risk.trading_halted ? 'pill-danger' : 'pill-safe'}`}>
            {risk.trading_halted ? 'Halted' : 'Active'}
          </span>
        </div>
        <div className="risk-grid">
          <div>
            <span>Capital</span>
            <strong>{formatMoney(risk.capital)}</strong>
          </div>
          <div>
            <span>Daily Loss Remaining</span>
            <strong>{formatMoney(risk.daily_loss_remaining)}</strong>
          </div>
          <div>
            <span>Available Capital</span>
            <strong>{formatMoney(risk.available_capital)}</strong>
          </div>
          <div>
            <span>Realized P/L</span>
            <strong>{formatMoney(risk.realized_pnl)}</strong>
          </div>
        </div>
      </article>

      <article className="card">
        <div className="card-header">
          <h2>Manual Override</h2>
          <span className="mono">execution controls</span>
        </div>
        <div className="button-stack">
          <button onClick={onSquareOff}>Force Square Off</button>
          <button onClick={onPause}>Pause Trading</button>
          <button onClick={onResume}>Resume</button>
        </div>
      </article>

      <article className="card card-wide">
        <div className="card-header">
          <h2>Live Signal Feed</h2>
          <span className="mono">{recentTrades.length} recent trades</span>
        </div>
        <div className="feed-list">
          {(recentTrades.length ? recentTrades : morningReport?.candidates || []).slice(0, 6).map((item, index) => (
            <div key={item.trade_id || item.symbol || index} className="feed-row">
              <strong>{item.instrument || item.symbol}</strong>
              <span>{item.reason || (item.tags || []).join(', ') || 'candidate'}</span>
            </div>
          ))}
        </div>
      </article>

      <article className="card card-wide">
        <div className="card-header">
          <h2>Active Trades</h2>
          <span className="mono">{positions.length} positions</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Instrument</th>
              <th>Qty</th>
              <th>Entry</th>
              <th>LTP</th>
              <th>Diff</th>
              <th>P/L</th>
              <th>Side</th>
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 ? (
              <tr>
                <td colSpan="7">No active positions.</td>
              </tr>
            ) : (
              positions.map((position) => (
                <tr key={position.instrument}>
                  <td>{position.instrument}</td>
                  <td>{position.qty}</td>
                  <td>{position.avg_price}</td>
                  <td>{position.ltp}</td>
                  <td>{position.diff_from_entry}</td>
                  <td className={Number(position.pnl) >= 0 ? 'pl-positive' : 'pl-negative'}>{formatMoney(position.pnl)}</td>
                  <td>{position.side}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </article>
    </section>
  );
}
