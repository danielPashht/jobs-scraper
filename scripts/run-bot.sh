#!/usr/bin/env bash
# Run the jobs bot detached and prevent the Mac from sleeping while it runs.
# Usage:
#   ./scripts/run-bot.sh            # foreground (Ctrl-C to stop)
#   ./scripts/run-bot.sh --detach   # background, survives terminal close; check logs/bot.log
#   ./scripts/stop-bot.sh           # stop a detached bot

set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python}"
LOG_DIR="logs"
PID_FILE="$LOG_DIR/bot.pid"
LOG_FILE="$LOG_DIR/bot.log"
mkdir -p "$LOG_DIR"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and fill in TG_BOT_TOKEN." >&2
  exit 1
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "Python venv not found at $PYTHON. Run: python3 -m venv .venv && .venv/bin/pip install -e '.[cf]'" >&2
  exit 1
fi

# caffeinate -i prevents idle sleep while the bot's process group is alive.
# -d would also prevent display sleep — overkill for a headless bot.
CMD=(caffeinate -i "$PYTHON" -m scraper.bot)

if [[ "${1:-}" == "--detach" ]]; then
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Bot already running (pid $(cat "$PID_FILE")). Use ./scripts/stop-bot.sh first." >&2
    exit 1
  fi
  nohup "${CMD[@]}" >>"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
  disown || true
  sleep 1
  if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Bot started (pid $(cat "$PID_FILE")). Logs: $LOG_FILE"
  else
    echo "Bot exited immediately. Tail $LOG_FILE for details." >&2
    rm -f "$PID_FILE"
    exit 1
  fi
else
  exec "${CMD[@]}"
fi
