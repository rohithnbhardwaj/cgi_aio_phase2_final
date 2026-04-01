#!/usr/bin/env bash
# run-compose.sh — builds & starts compose stack, waits for DB health, tails streamlit logs
set -euo pipefail

# --- Configurable (can override via env) ---
# NOTE: these must be the *service names* as defined in docker-compose.yml
SERVICE_STREAMLIT="${SERVICE_STREAMLIT:-streamlit}"
SERVICE_DB="${SERVICE_DB:-db}"
DB_HEALTH_TIMEOUT="${DB_HEALTH_TIMEOUT:-60}"   # seconds to wait for DB healthy
POST_PULL_WAIT="${POST_PULL_WAIT:-2}"          # wait after pull
NO_CACHE="${NO_CACHE:-0}"                      # set to 1 to force --no-cache build

# --- helper/entry ---
cd "$(dirname "$0")" || exit 1
echo "Starting helper (cwd=$(pwd))"
echo

# Optional: start gnome-keyring-daemon (best-effort)
if command -v gnome-keyring-daemon >/dev/null 2>&1; then
  echo "Attempting to start gnome-keyring-daemon (secrets) if available..."
  eval "$(gnome-keyring-daemon --start --components=secrets 2>/dev/null || true)"
fi

# Minimal docker config (fallback for credential helpers)
TMP_DOCKER_CONFIG="$HOME/.tmp_docker_cfg_for_pull"
mkdir -p "$TMP_DOCKER_CONFIG"
cat > "$TMP_DOCKER_CONFIG/config.json" <<'JSON'
{"auths":{},"credsStore":""}
JSON

echo
echo "Ensuring postgres:15 image is available (best-effort pull)..."
if ! docker pull --platform linux/amd64 postgres:15 2>&1 | sed -n '1,120p'; then
  echo "Pull failed (maybe credential-helper). Trying fallback pull with explicit --config..."
  docker --config "$TMP_DOCKER_CONFIG" pull --platform linux/amd64 postgres:15 || true
fi
sleep "$POST_PULL_WAIT"

echo
if [ "$NO_CACHE" = "1" ]; then
  echo "Building with no-cache..."
  docker compose build --no-cache
  docker compose up -d
else
  echo "Building (cached where possible) and starting stack..."
  docker compose up --build -d
fi

echo
echo "Containers (short):"
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"

# Wait for DB service to become healthy (if present)
if docker compose ps --services | grep -q -E "^${SERVICE_DB}$"; then
  echo
  echo "Waiting for DB service '${SERVICE_DB}' to become healthy (timeout ${DB_HEALTH_TIMEOUT}s)..."
  start_ts=$(date +%s)
  while true; do
    cid=$(docker compose ps -q "${SERVICE_DB}" 2>/dev/null || true)
    if [ -n "$cid" ]; then
      health=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)
      echo "  DB container status: ${health:-unknown}"
      if [ "$health" = "healthy" ] || [ "$health" = "running" ]; then
        echo "DB is ready."
        break
      fi
    else
      echo "  DB container id not found yet."
    fi
    now=$(date +%s)
    elapsed=$((now - start_ts))
    if [ $elapsed -ge "$DB_HEALTH_TIMEOUT" ]; then
      echo "Timed out waiting for DB to become healthy after ${DB_HEALTH_TIMEOUT}s — continuing anyway."
      break
    fi
    sleep 2
  done
else
  echo "DB service '${SERVICE_DB}' not found in compose project; skipping health wait."
fi

# Tail recent logs for Streamlit(service) or fallback
echo
LOG_SERVICE="${SERVICE_STREAMLIT}"
echo "Tailing last 50 lines of logs for '${LOG_SERVICE}' (if service exists):"
if docker compose ps --services | grep -q -E "^${LOG_SERVICE}$"; then
  docker compose logs --tail=50 "${LOG_SERVICE}" | sed -n '1,200p'
else
  echo "Streamlit service '${LOG_SERVICE}' not found. Available services:"
  docker compose ps --services || true
fi

echo
echo "Done. Open http://localhost:8501 (or your configured port)."
