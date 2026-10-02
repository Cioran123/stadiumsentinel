#!/usr/bin/env bash
# Restart the Next.js dev server and the webcam live-labeling server, then open the dashboard.
#
#   npm run dashboard              # restart both servers + open browser
#   npm run dashboard -- --refresh # also rebuild incidents from existing tracks first
#   npm run dashboard -- --no-live # skip the webcam live server
#   PORT=3000 LIVE_PORT=8766 npm run dashboard
set -euo pipefail

cd "$(dirname "$0")/.."
PORT="${PORT:-3100}"
LIVE_PORT="${LIVE_PORT:-8765}"
URL="http://localhost:${PORT}/overview"
REFRESH=0
LIVE=1
for arg in "$@"; do
  case "$arg" in
    --refresh) REFRESH=1 ;;
    --no-live) LIVE=0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

free_port() {
  local pids
  pids="$(lsof -ti "tcp:$1" || true)"
  if [[ -n "$pids" ]]; then
    echo "[dashboard] stopping process on port $1"
    kill $pids 2>/dev/null || true
    for _ in {1..20}; do
      lsof -ti "tcp:$1" >/dev/null || break
      sleep 0.25
    done
  fi
}

if [[ "$REFRESH" == 1 ]]; then
  echo "[dashboard] rebuilding incidents from existing tracks"
  .venv/bin/python pipeline/run_all.py --verifier none
fi

free_port "$PORT"
LIVE_PID=""
if [[ "$LIVE" == 1 ]]; then
  free_port "$LIVE_PORT"
  echo "[dashboard] starting webcam live server on http://localhost:${LIVE_PORT}"
  .venv/bin/python pipeline/live_server.py --port "$LIVE_PORT" &
  LIVE_PID=$!
fi
cleanup() { [[ -n "$LIVE_PID" ]] && kill "$LIVE_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# Open the browser once the web server answers; runs alongside the server below.
(
  for _ in {1..120}; do
    if curl -s -o /dev/null "$URL"; then
      open "$URL"
      exit 0
    fi
    sleep 0.5
  done
  echo "[dashboard] server did not respond at ${URL}" >&2
) &

echo "[dashboard] starting server at ${URL} (Ctrl+C stops both)"
NEXT_PUBLIC_LIVE_URL="http://localhost:${LIVE_PORT}" npx next dev --port "$PORT"
