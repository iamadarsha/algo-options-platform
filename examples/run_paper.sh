#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/backend"

python -m app.main run \
  --mode paper \
  --strategy momentum \
  --start 2026-03-10 \
  --end 2026-03-10 \
  --config app/config.yml \
  --simulate-loss-streak 3
