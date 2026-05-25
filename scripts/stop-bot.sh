#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PID_FILE="logs/bot.pid"
if [[ ! -f "$PID_FILE" ]]; then
  echo "No PID file at $PID_FILE — bot not running detached."
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "Stopped bot (pid $PID)."
else
  echo "PID $PID not running; cleaning stale PID file."
fi
rm -f "$PID_FILE"
