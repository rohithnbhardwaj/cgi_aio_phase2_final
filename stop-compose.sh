#!/usr/bin/env bash
set -euo pipefail

# Stop & remove containers for the compose project (keeps volumes by default)
# Usage: ./stop.sh
# To also remove volumes: set REMOVE_VOLUMES=1 ./stop.sh

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

# colors
RED="\033[0;31m"
YEL="\033[0;33m"
GRN="\033[0;32m"
NC="\033[0m"

REMOVE_VOLUMES="${REMOVE_VOLUMES:-0}"

echo -e "${YEL}Stopping compose services...${NC}"
docker compose down

if [ "$REMOVE_VOLUMES" = "1" ]; then
  echo -e "${YEL}Removing volumes (this is destructive)...${NC}"
  docker compose down -v
fi

echo -e "${GRN}Containers stopped and removed (volumes preserved).${NC}"
echo -e "${GRN}If you wanted volumes removed, re-run with REMOVE_VOLUMES=1 ./stop.sh${NC}"
