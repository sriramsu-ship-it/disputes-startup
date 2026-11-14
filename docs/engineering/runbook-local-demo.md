# Run the demo on your laptop (synthetic data only)

Everything runs on your machine at http://localhost:8000. Nothing is exposed to your network.

## Option A: Docker Desktop (simplest)
1. Install and open Docker Desktop: https://www.docker.com/products/docker-desktop/
2. In Terminal:
   ```bash
   git clone https://github.com/sriramsu-ship-it/disputes-startup
   cd disputes-startup
   scripts/demo.sh start
   ```
   First start builds the image and processes the synthetic cases (a few minutes).
3. Open http://localhost:8000 and sign in (below).

Other commands: `scripts/demo.sh stop | status | logs | test | reset`.

## Option B: no Docker (macOS with Homebrew)
```bash
brew install python@3.13 postgresql@16
brew services start postgresql@16
git clone https://github.com/sriramsu-ship-it/disputes-startup
cd disputes-startup
DISPUTES_DATABASE_URL=postgresql://$USER@127.0.0.1:5432/disputes_demo scripts/demo_native.sh start
```
Use the same `DISPUTES_DATABASE_URL=...` prefix for `stop`, `status`, `logs`, `test` and `reset`.

## Signing in
- Password for every demo login: `synthetic-demo-local`
- MFA: the sign-in page shows the current 6-digit code (local dev mode only; refused in hosted mode).
- Logins:
  - `u-specialist-1@demo.invalid`: analyst (review and approve cases)
  - `u-supervisor-1@demo.invalid`, `u-supervisor-2@demo.invalid`: escalations and second approvals
  - `u-admin-1@demo.invalid`: configuration
  - `u-auditor-1@demo.invalid`: read-only audit view
  - `u-client-0@demo.invalid`, `u-client-1@demo.invalid`: client portal for each synthetic lender

## Showing it on a call
Share your browser window. Start with the client portal (`u-client-0`) to show what a lender sees, then sign in as the analyst to open a case and its audit export.

## If something goes wrong
- "port 8000 is already in use": add `DISPUTES_PORT=8001` before the command and open http://localhost:8001.
- Option B, "bootstrap failed": Postgres isn't running (`brew services start postgresql@16`).
- `scripts/demo.sh logs` (or `demo_native.sh logs`) shows the web and worker logs.

## What this is not
Synthetic data only. The AI step is a rule-based stand-in, not a real model. Not hosted, not hardened for the internet, not SOC 2.
