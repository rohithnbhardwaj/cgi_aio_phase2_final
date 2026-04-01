#!/usr/bin/env bash
set -euo pipefail

# Usage: ./status.sh
# Shows `docker compose ps` + a little health/port summary + docker ps table

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

# colors
RED="\033[0;31m"
YEL="\033[0;33m"
GRN="\033[0;32m"
CYN="\033[0;36m"
NC="\033[0m"

echo -e "${CYN}== docker compose services ==${NC}"
docker compose ps

echo
echo -e "${CYN}== docker ps (summary) ==${NC}"
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"

echo
echo -e "${CYN}== Health checks (if available) ==${NC}"
# iterate compose services and show container health
services=$(docker compose ps --services 2>/dev/null || true)
if [ -z "$services" ]; then
  echo -e "${YEL}No services found in compose project.${NC}"
  exit 0
fi

for svc in $services; do
  cid=$(docker compose ps -q "$svc" 2>/dev/null || true)
  if [ -z "$cid" ]; then
    echo -e "${YEL}$svc: not running${NC}"
    continue
  fi
  health=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || true)
  case "$health" in
    healthy) color=${GRN} ;;
    starting) color=${YEL} ;;
    unhealthy) color=${RED} ;;
    running) color=${GRN} ;;
    *) color=${YEL} ;;
  esac
  echo -e "${color}${svc}: ${health}${NC}"
done

echo
echo -e "${GRN}Done. Open http://localhost:8501 (or your configured port)${NC}"
