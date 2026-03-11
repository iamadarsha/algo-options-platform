import { useEffect, useState } from 'react';
import Dashboard from './components/Dashboard';
import StrategyBuilder from './components/StrategyBuilder';
import TradeLog from './components/TradeLog';
import {
  connectLiveUpdates,
  exportStrategy,
  fetchMorningReport,
  fetchState,
  pauseTrading,
  resumeTrading,
  squareOff,
} from './api';

const DEFAULT_TOGGLES = {
  momentum: true,
  opening_range_fade: true,
  mean_reversion: true,
};

export default function App() {
  const [state, setState] = useState(null);
  const [morningReport, setMorningReport] = useState(null);
  const [strategyToggles, setStrategyToggles] = useState(DEFAULT_TOGGLES);
  const [statusMessage, setStatusMessage] = useState('');

  useEffect(() => {
    let socket;

    async function bootstrap() {
      const [runtimeState, report] = await Promise.all([fetchState(), fetchMorningReport()]);
      setState(runtimeState);
      setMorningReport(report);
      socket = connectLiveUpdates((nextState) => {
        setState(nextState);
        if (nextState.morning_report) {
          setMorningReport(nextState.morning_report);
        }
      });
    }

    bootstrap().catch((error) => setStatusMessage(error.message));

    return () => {
      if (socket) {
        socket.close();
      }
    };
  }, []);

  async function handleAction(action) {
    try {
      let response;
      if (action === 'pause') response = await pauseTrading();
      if (action === 'resume') response = await resumeTrading();
      if (action === 'squareOff') response = await squareOff();
      if (response?.state) {
        setState(response.state);
      } else if (response?.risk) {
        setState(response);
      }
    } catch (error) {
      setStatusMessage(error.message);
    }
  }

  async function handleExport(payload) {
    try {
      const response = await exportStrategy(payload);
      setStatusMessage(`Saved strategy JSON to ${response.saved_to}`);
    } catch (error) {
      setStatusMessage(error.message);
    }
  }

  return (
    <main className="app-shell">
      <section className="hero-panel">
        <div>
          <p className="eyebrow">Intraday Options Control Room</p>
          <h1>Algo Platform</h1>
          <p className="hero-copy">
            Paper-first execution, morning reports, live controls, and persistent risk state for
            NIFTY, BANKNIFTY, and liquid NSE names.
          </p>
        </div>
        <div className="status-chip">{statusMessage || state?.mode || 'connecting'}</div>
      </section>

      <Dashboard
        state={state}
        morningReport={morningReport}
        strategyToggles={strategyToggles}
        setStrategyToggles={setStrategyToggles}
        onPause={() => handleAction('pause')}
        onResume={() => handleAction('resume')}
        onSquareOff={() => handleAction('squareOff')}
      />

      <section className="grid-two">
        <StrategyBuilder onExport={handleExport} />
        <TradeLog trades={state?.recent_trades || []} />
      </section>
    </main>
  );
}
