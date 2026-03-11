const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws/live';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json();
}

export function fetchState() {
  return request('/api/state');
}

export function fetchMorningReport() {
  return request('/api/morning-report');
}

export function pauseTrading() {
  return request('/api/control/pause', { method: 'POST' });
}

export function resumeTrading() {
  return request('/api/control/resume', { method: 'POST' });
}

export function squareOff() {
  return request('/api/control/square-off', { method: 'POST' });
}

export function exportStrategy(payload) {
  return request('/api/strategy/export', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function connectLiveUpdates(onMessage) {
  const socket = new WebSocket(WS_URL);
  socket.onmessage = (event) => {
    onMessage(JSON.parse(event.data));
  };
  return socket;
}
