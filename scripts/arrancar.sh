#!/usr/bin/env bash
# Deja el bot corriendo desde cero.
#
#   ./scripts/arrancar.sh
#
# Crea el entorno, instala, revisa la configuración y arranca.

set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  echo "→ Creando el entorno de Python…"
  python3 -m venv .venv
fi
source .venv/bin/activate

echo "→ Instalando dependencias…"
pip install -q --upgrade pip
pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo "  Te creé un .env. Ábrelo y llena TELEGRAM_TOKEN y GEMINI_API_KEY."
  echo "  Después vuelve a correr este script."
  exit 1
fi

echo "→ Revisando la configuración…"
if ! PYTHONPATH=. python scripts/verificar.py; then
  echo "  Arregla lo de arriba y vuelve a correrlo."
  exit 1
fi

echo "→ Arrancando el bot. Ctrl+C para parar."
python run_bot.py
