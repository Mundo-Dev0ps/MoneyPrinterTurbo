#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE_NAME="${MONEYPRINTERTURBO_MCP_IMAGE:-moneyprinterturbo-mcp:local}"
LAZY_PROXY="${MCP_LAZY_PROXY:-$HOME/.bin/mcp-lazy-docker}"

if [[ "${1:-}" != "--exec-container" ]] && [[ "${MCP_LAZY_DISABLE:-0}" != "1" ]] && [[ -x "$LAZY_PROXY" ]]; then
  exec "$LAZY_PROXY" \
    --name "moneyprinterturbo" \
    --image "$IMAGE_NAME" \
    --watch "$REPO_DIR/mcp_server.py" \
    --watch "$REPO_DIR/app/mcp/server.py" \
    --watch "$0" \
    --idle-timeout "${MCP_IDLE_TIMEOUT_SEC:-120}" \
    -- "$0" --exec-container
fi

exec docker run -i --rm \
  -v "$REPO_DIR/config.toml:/MoneyPrinterTurbo/config.toml" \
  -v "$REPO_DIR/storage:/MoneyPrinterTurbo/storage" \
  -v "$REPO_DIR/app:/MoneyPrinterTurbo/app:ro" \
  -v "$REPO_DIR/mcp_server.py:/MoneyPrinterTurbo/mcp_server.py:ro" \
  "$IMAGE_NAME"
