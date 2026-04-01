#!/usr/bin/env bash
set -euo pipefail

# Usage: ./reset.sh
# DANGEROUS: removes compose containers, volumes and compose-created local images
# Read before running.
# If you want a non-destructive reset, run: ./stop.sh && docker compose up -d --build

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

# colors
RED="\033[0;31m"
YEL="\033[0;33m"
GRN="\033[0;32m"
NC="\033[0m"

echo -e "${YEL}*** FULL RESET: this will remove containers, volumes and local images created by compose ***${NC}"
read -r -p "Are you sure you want to continue? (type 'yes' to proceed): " ans
if [ "$ans" != "yes" ]; then
  echo -e "${RED}Aborting.${NC}"
  exit 1
fi

# Stop and remove everything including volumes and local images created by compose.
echo -e "${YEL}Stopping and removing containers, volumes, and local images...${NC}"
docker compose down -v --rmi local --remove-orphans

# Optionally prune unused images (global), uncomment if you want:
# echo -e "${YEL}Pruning unused images (this is global)...${NC}"
# docker image prune -af

echo -e "${YEL}Rebuilding images (no cache)...${NC}"
docker compose build --no-cache

echo -e "${YEL}Bringing services up...${NC}"
docker compose up -d

echo -e "${GRN}Reset complete. Run ./status.sh to check service health.${NC}"
