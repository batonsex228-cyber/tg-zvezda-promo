#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -f .env ]]; then
  echo "[ERROR] Create .env from .env.example, add both BotFather tokens, Tourist domain and owner ID."
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] Docker is not installed."
  exit 1
fi
echo "[INFO] Pulling both GHCR images and Caddy..."
docker compose pull
echo "[INFO] Starting both Telegram bots and Mini App..."
docker compose up -d
docker compose ps
echo "[INFO] See logs: docker compose logs --tail=80 zvezdochka tourist caddy"
