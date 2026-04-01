#!/usr/bin/env bash
set -euo pipefail

# run this from the repo root (where docker-compose.yml lives)
cd "$(dirname "$0")"

# Configuration: set these to the service names used in your compose file
SERVICE_STREAMLIT="${SERVICE_STREAMLIT:-streamlit_app}"   
SERVICE_DB="${SERVICE_DB:-streamlit_db}"                  
DB_HEALTH_TIMEOUT="${DB_HEALTH_TIMEOUT:-60}"              

echo "Starting helper (cwd=$(pwd))"

# Start gnome-keyring secrets if available (helps the docker credential helper)
if command -v gnome-keyring-daemon >/dev/null 2>&1; then
  echo "Starting gnome-keyring-daemon (secrets) if not already running..."
  # ignore errors: this is best-effort
  eval "$(gnome-keyring-daemon --start --components=secrets 2>/dev/null || true)"
fi

# Create a fallback minimal docker config dir (used only with --config if needed)
TMP_DOCKER_CONFIG="$HOME/.tmp_docker_cfg_for_pull"
mkdir -p "$TMP_DOCKER_CONFIG"
cat > "$TMP_DOCKER_CONFIG/config.json" <<'JSON'
{"auths":{},"credsStore":""}
JSON

# Try to ensure postgres image is available (pull) to avoid long delays during up
echo "Attempting to ensure postgres image is available..."
if ! docker pull --platform linux/amd64 postgres:15 2>&1 | sed -n '1,120p'; then
  echo "Normal pull failed or credential helper invoked — trying explicit --config fallback..."
  docker --config "$TMP_DOCKER_CONFIG" pull --platform linux/amd64 postgres:15
fi

echo "Building and starting docker-compose stack..."
docker compose up --build -d

echo
echo "Listing containers:"
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"

# Wait for DB healthy if it has a healthcheck
if docker compose ps --services | grep -q -E "^${SERVICE_DB}$"; then
  echo "Waiting for DB service '${SERVICE_DB}' to become healthy (timeout ${DB_HEALTH_TIMEOUT}s)..."
  start_ts=$(date +%s)
  while true; do
    # get container id for the service (first container)
    cid=$(docker compose ps -q "${SERVICE_DB}" 2>/dev/null || true)
    if [ -n "$cid" ]; then
      # if the container exposes health info, inspect it; else consider running if up
      health=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)
      echo "  DB container status: ${health:-unknown}"
      if [ "$health" = "healthy" ] || [ "$health" = "running" ]; then
        echo "DB is ready."
        break
      fi
    fi
    now=$(date +%s)
    elapsed=$((now - start_ts))
    if [ $elapsed -ge $DB_HEALTH_TIMEOUT ]; then
      echo "Timed out waiting for DB to become healthy after ${DB_HEALTH_TIMEOUT}s. Continuing anyway."
      break
    fi
    sleep 2
  done
else
  echo "DB service '${SERVICE_DB}' not found in compose project; skipping health wait."
fi

# Tail a small amount of logs for the Streamlit service
echo
LOG_SERVICE="${SERVICE_STREAMLIT}"
echo "Tailing last 50 lines of logs for '${LOG_SERVICE}' (if service exists):"
# prefer service name in compose; fall back to generic 'streamlit' for older setups
if docker compose ps --services | grep -q -E "^${LOG_SERVICE}$"; then
  docker compose logs --tail=50 "${LOG_SERVICE}" | sed -n '1,200p'
else
  # try 'streamlit' as fallback
  if docker compose ps --services | grep -q -E "^streamlit$"; then
    docker compose logs --tail=50 streamlit | sed -n '1,200p'
  else
    echo "No streamlit service found in compose. Available services:"
    docker compose ps --services || true
  fi
fi

echo
echo "Done. Open http://localhost:8501 in your browser (or the port you defined)."
