#!/bin/sh
# Start the unmodified My Virtual Office server on Android/Termux with a real
# OpenCode server as the AI backend. No Docker, no root.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
STATUS_DIR=${VO_STATUS_DIR:-$HOME/vo-data}
case "$STATUS_DIR" in
  /*) ;;
  *) echo "VO_STATUS_DIR must be absolute (got: $STATUS_DIR)" >&2; exit 2 ;;
esac
mkdir -p "$STATUS_DIR" "$STATUS_DIR/logs"
export VO_STATUS_DIR="$STATUS_DIR"

chmod +x "$ROOT/scripts/opencode" "$ROOT/scripts/opencode-bridge"
python3 "$ROOT/scripts/setup_office_agents.py"

OC_PORT=${VO_OPENCODE_SERVER_PORT:-41777}
PW_FILE="$STATUS_DIR/.opencode-server-password"
PW=$(cat "$PW_FILE")
OC_URL="http://127.0.0.1:$OC_PORT"

# Start the REAL upstream OpenCode server through the glibc loader when it is
# not already running. Its credentials stay in a 0600 file, never in source.
if ! curl -fsS -m 3 -u "opencode:$PW" "$OC_URL/api/info" >/dev/null 2>&1; then
  LOADER=${VO_GLIBC_LOADER:-$PREFIX/glibc/lib/ld-linux-aarch64.so.1}
  LIBDIR=${VO_GLIBC_LIBDIR:-$PREFIX/glibc/lib}
  OC_BIN=${VO_OPENCODE_REAL_BIN:-$HOME/.opencode/bin/opencode}
  if [ ! -x "$LOADER" ] || [ ! -f "$OC_BIN" ]; then
    echo "Real OpenCode binary or glibc loader not found; see ANDROID.md" >&2
    exit 3
  fi
  echo "Starting OpenCode server on $OC_PORT ..."
  (
    cd "$STATUS_DIR/opencode-main"
    OPENCODE_CONFIG_DIR="$STATUS_DIR/opencode-config" \
    OPENCODE_SERVER_PASSWORD="$PW" \
    OPENCODE_DISABLE_AUTOUPDATE=1 \
    nohup "$LOADER" --library-path "$LIBDIR" "$OC_BIN" serve \
      --hostname 127.0.0.1 --port "$OC_PORT" \
      >>"$STATUS_DIR/logs/opencode-server.log" 2>&1 &
  )
  n=0
  while [ "$n" -lt 60 ]; do
    if curl -fsS -m 2 -u "opencode:$PW" "$OC_URL/api/info" >/dev/null 2>&1; then
      break
    fi
    n=$((n + 1))
    sleep 0.5
  done
  if ! curl -fsS -m 2 -u "opencode:$PW" "$OC_URL/api/info" >/dev/null 2>&1; then
    echo "OpenCode server did not start; see $STATUS_DIR/logs/opencode-server.log" >&2
    exit 4
  fi
fi

export VO_OPENCODE_ENABLED=true
export VO_OPENCODE_BIN="$ROOT/scripts/opencode-bridge"
export VO_OPENCODE_CONFIG_DIR="$STATUS_DIR/opencode-config"
export VO_OPENCODE_MAIN_WORKSPACE="$STATUS_DIR/opencode-main"
export VO_OPENCODE_WORKSPACE_ROOT="$STATUS_DIR/opencode-agents"
export VO_OPENCODE_SERVER_URL="$OC_URL"
export VO_OPENCODE_SERVER_PASSWORD="$PW"
export VO_HERMES_RESOURCE_ROOT=${VO_HERMES_RESOURCE_ROOT:-$HOME/.hermes}
export VO_UPDATE_CHECK=${VO_UPDATE_CHECK:-0}
export PYTHONUNBUFFERED=1

echo "AI Office (original My Virtual Office) -> http://127.0.0.1:${VO_PORT:-8090}"
cd "$ROOT/app"
exec python3 -u server.py
