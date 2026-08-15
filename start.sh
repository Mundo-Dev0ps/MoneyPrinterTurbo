#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "========================================================"
echo "          Iniciando MoneyPrinterTurbo (Docker)          "
echo "========================================================"

# Detener cualquier contenedor huérfano previo
echo "[1/2] Limpiando contenedores previos..."
docker compose -f docker-compose.release.yml down 2>/dev/null || true
docker compose down 2>/dev/null || true

echo "[2/2] Levantando servicios en primer plano (interactivo sin -d)..."
echo ""
echo "  -> WebUI disponible en: http://localhost:8501"
echo "  -> API disponible en:   http://localhost:8080"
echo ""
echo "Presiona [Ctrl + C] en esta terminal cuando quieras detener la aplicacion."
echo "========================================================"
echo ""

# Si se pasa el argumento --build o -b, se compila localmente
if [ "$1" == "--build" ] || [ "$1" == "-b" ]; then
    docker compose -f docker-compose.yml up --build
else
    # Por defecto levanta la versión release con los volúmenes montados
    docker compose -f docker-compose.release.yml up
fi
