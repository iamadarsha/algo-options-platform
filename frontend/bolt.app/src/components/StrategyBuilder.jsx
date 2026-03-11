import { useState } from 'react';

const DEFAULT_JSON = {
  ema_fast: 20,
  ema_slow: 50,
  rsi_period: 14,
  rsi_long: 58,
  rsi_short: 42,
  volume_spike_mult: 1.4,
};

export default function StrategyBuilder({ onExport }) {
  const [name, setName] = useState('custom_momentum');
  const [jsonText, setJsonText] = useState(JSON.stringify(DEFAULT_JSON, null, 2));

  function handleSubmit(event) {
    event.preventDefault();
    const config = JSON.parse(jsonText);
    onExport({ name, config });
  }

  return (
    <article className="card">
      <div className="card-header">
        <h2>Strategy Builder</h2>
        <span className="mono">export JSON</span>
      </div>
      <form className="builder-form" onSubmit={handleSubmit}>
        <label>
          Strategy Name
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          Strategy JSON
          <textarea value={jsonText} onChange={(event) => setJsonText(event.target.value)} rows={14} />
        </label>
        <button type="submit">Export to Backend</button>
      </form>
    </article>
  );
}
