function formatMoney(value) {
  return `₹${Number(value || 0).toFixed(2)}`;
}

export default function TradeLog({ trades }) {
  return (
    <article className="card">
      <div className="card-header">
        <h2>Trade Log</h2>
        <span className="mono">{trades.length} entries</span>
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Instrument</th>
            <th>Qty</th>
            <th>Entry</th>
            <th>Exit</th>
            <th>P/L</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {trades.length === 0 ? (
            <tr>
              <td colSpan="7">Trade log will populate after a paper or backtest run.</td>
            </tr>
          ) : (
            trades.map((trade) => (
              <tr key={trade.trade_id || `${trade.instrument}-${trade.opened_at}`}>
                <td>{trade.opened_at || trade.timestamp}</td>
                <td>{trade.instrument}</td>
                <td>{trade.qty}</td>
                <td>{trade.entry_price}</td>
                <td>{trade.exit_price}</td>
                <td className={Number(trade.pl) >= 0 ? 'pl-positive' : 'pl-negative'}>
                  {formatMoney(trade.pl)}
                </td>
                <td>{trade.reason}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </article>
  );
}
