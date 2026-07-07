#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLED_PYTHON="/Users/admin/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"

if [[ -x "$BUNDLED_PYTHON" ]]; then
  PYTHON="$BUNDLED_PYTHON"
else
  PYTHON="python3"
fi

exec "$PYTHON" "$ROOT_DIR/weather_map_automation/generate_us_15day_heatmap.py" "$@"
