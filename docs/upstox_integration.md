# Upstox Integration

## Safety First

- Keep `DISABLE_LIVE_TRADING=true` until paper mode is validated.
- Never store credentials in source code.
- The backend redacts secrets from logs and falls back to paper mode on API errors.

## Required Environment Variables

- `UPSTOX_API_KEY`
- `UPSTOX_API_SECRET`
- `UPSTOX_ACCESS_TOKEN`
- `UPSTOX_REDIRECT_URI`

## OAuth Flow

1. Create an app in the Upstox developer console.
2. Set a redirect URI such as `http://localhost:8000/auth/upstox/callback`.
3. Send the user to the Upstox authorization URL documented in the official Upstox API docs.
4. Receive the authorization code on your callback URL.
5. Exchange the code for an access token using your app key and secret.
6. Store the access token in your environment or secrets manager.

## Local Setup

```bash
cp .env.example .env
```

Set:

```env
UPSTOX_API_KEY=your_key
UPSTOX_API_SECRET=your_secret
UPSTOX_ACCESS_TOKEN=your_access_token
UPSTOX_REDIRECT_URI=http://localhost:8000/auth/upstox/callback
DISABLE_LIVE_TRADING=true
```

## Live Trading Checklist

1. Run paper mode for at least several sessions.
2. Verify order payloads, risk halts, and square-off behavior.
3. Set `DISABLE_LIVE_TRADING=false`.
4. Restart the backend.
5. Confirm the dashboard shows live mode explicitly before sending any order.

## Implementation Notes

- The repository uses a conservative wrapper around the broker API.
- If an endpoint returns an error, times out, or changes shape, the wrapper logs the event and switches to paper mode.
- Some exact Upstox endpoints can vary by API version, so those functions include TODO comments where a human should confirm the production path against current official docs.
