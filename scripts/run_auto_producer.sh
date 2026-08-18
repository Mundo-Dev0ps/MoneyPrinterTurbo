#!/usr/bin/env bash
set -e

REPO_DIR="/home/mundo-devops/mundo-devops/repos/MoneyPrinterTurbo"
LOG_DIR="${REPO_DIR}/storage/logs"
mkdir -p "${LOG_DIR}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="${LOG_DIR}/auto_producer_${TIMESTAMP}.log"

echo "[$(date)] Iniciando ejecucion programada de Auto-Producer..." | tee -a "${LOG_FILE}"

docker run -i --rm \
  -v "${REPO_DIR}/config.toml:/MoneyPrinterTurbo/config.toml" \
  -v "${REPO_DIR}/storage:/MoneyPrinterTurbo/storage" \
  -v "${REPO_DIR}/app:/MoneyPrinterTurbo/app" \
  -v "${REPO_DIR}/config:/MoneyPrinterTurbo/config" \
  -v "${REPO_DIR}/scripts:/MoneyPrinterTurbo/scripts" \
  -v "${REPO_DIR}/mcp_server.py:/MoneyPrinterTurbo/mcp_server.py" \
  ghcr.io/harry0703/moneyprinterturbo:latest \
  sh -c "pip install -q 'mcp>=1.3.0,<2' >/dev/null 2>&1 && python3 /MoneyPrinterTurbo/scripts/auto_producer.py \"$@\"" 2>&1 | tee -a "${LOG_FILE}"

echo "[$(date)] Ejecucion programada finalizada." | tee -a "${LOG_FILE}"
