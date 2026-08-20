#!/usr/bin/env bash
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${REPO_DIR}/logs"
mkdir -p "${LOG_DIR}" "${REPO_DIR}/models" "${REPO_DIR}/storage"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="${LOG_DIR}/auto_producer_${TIMESTAMP}.log"

GCP_KEY="${REPO_DIR}/secrets/gcp-key.json"
GCP_PROJECT="rrss-multi-deploy"
SECRET_NAME="moneyprinter-config"

# Escribir el secreto ÚNICAMENTE en la memoria RAM temporal (/dev/shm)
RAM_CONFIG_PATH="/dev/shm/mpt_config_${TIMESTAMP}.toml"

cleanup() {
    rm -f "${RAM_CONFIG_PATH}"
}
trap cleanup EXIT INT TERM

echo "[$(date)] Iniciando ejecucion en VPS remoto (Zero-Disk Secrets)..." | tee -a "${LOG_FILE}"

if [ ! -f "${GCP_KEY}" ]; then
    echo "[$(date)] ERROR: Clave GCP no encontrada en ${GCP_KEY}" | tee -a "${LOG_FILE}"
    exit 1
fi

# 1. Obtener el secreto desde GCP Secret Manager via REST API
python3 -c "
import json, urllib.request, urllib.parse, base64, re
from google.oauth2 import service_account
from google.auth.transport.requests import Request

creds = service_account.Credentials.from_service_account_file(
    '${GCP_KEY}',
    scopes=['https://www.googleapis.com/auth/cloud-platform']
)
creds.refresh(Request())
token = creds.token

url = 'https://secretmanager.googleapis.com/v1/projects/${GCP_PROJECT}/secrets/${SECRET_NAME}/versions/latest:access'
req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
with urllib.request.urlopen(req) as resp:
    res = json.loads(resp.read().decode('utf-8'))
    payload = base64.b64decode(res['payload']['data']).decode('utf-8')
    
    # Asegurar modelo Whisper eficiente (medium/small) en CPU para máxima velocidad
    if '[whisper]' in payload:
        payload = re.sub(r'model_size\s*=\s*\"large-v3\"', 'model_size = \"medium\"', payload)
    else:
        payload += '\n[whisper]\nmodel_size = \"medium\"\ndevice = \"cpu\"\ncompute_type = \"int8\"\n'

    with open('${RAM_CONFIG_PATH}', 'w', encoding='utf-8') as f:
        f.write(payload)
" 2>&1 | tee -a "${LOG_FILE}"

chmod 600 "${RAM_CONFIG_PATH}"
echo "[$(date)] Secreto descargado exitosamente en memoria RAM (/dev/shm)." | tee -a "${LOG_FILE}"

# 2. Ejecutar contenedor Docker montando el config desde memoria RAM y caché persistente de modelos
docker run -i --rm \
  -v "${RAM_CONFIG_PATH}:/MoneyPrinterTurbo/config.toml:ro" \
  -v "${REPO_DIR}/models:/root/.cache/huggingface" \
  -v "${REPO_DIR}/models:/MoneyPrinterTurbo/models" \
  -v "${REPO_DIR}/storage:/MoneyPrinterTurbo/storage" \
  -v "${REPO_DIR}/app:/MoneyPrinterTurbo/app" \
  -v "${REPO_DIR}/config:/MoneyPrinterTurbo/config" \
  -v "${REPO_DIR}/scripts:/MoneyPrinterTurbo/scripts" \
  ghcr.io/harry0703/moneyprinterturbo:latest \
  sh -c 'pip install -q "mcp>=1.3.0,<2" >/dev/null 2>&1 && python3 /MoneyPrinterTurbo/scripts/auto_producer.py "$@"' sh "$@" 2>&1 | tee -a "${LOG_FILE}"

echo "[$(date)] Ejecucion completada. Memoria RAM liberada." | tee -a "${LOG_FILE}"
