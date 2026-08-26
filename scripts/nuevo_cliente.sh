#!/usr/bin/env bash
# Genera el archivo .env de un cliente nuevo, con secretos aleatorios.
#
#   ./scripts/nuevo_cliente.sh "Ana Pérez" > clientes/ana.env
#
# Después llena a mano TELEGRAM_TOKEN, GEMINI_API_KEY, DATABASE_URL y BASE_URL,
# y pega esas variables en Render (o usa el archivo con docker compose).

set -euo pipefail

OWNER="${1:-}"
if [ -z "$OWNER" ]; then
  echo "Uso: $0 \"Nombre del cliente\" [Nombre del bot] [Moneda] [Zona horaria]" >&2
  exit 1
fi

APP_NAME="${2:-Kuri}"
CURRENCY="${3:-USD}"
TIMEZONE="${4:-America/Guayaquil}"

secret() { head -c 32 /dev/urandom | base64 | tr -d '=+/' | cut -c1-40; }

cat <<EOF
# Cliente: $OWNER
# Generado: $(date -u +%Y-%m-%dT%H:%M:%SZ)

APP_NAME=$APP_NAME
APP_TAGLINE=Tus finanzas, en un chat
OWNER_NAME=$OWNER

# --- Completa estos cuatro a mano ---
TELEGRAM_TOKEN=
GEMINI_API_KEY=
DATABASE_URL=
BASE_URL=

# --- Generados automáticamente: no los cambies después del deploy ---
TELEGRAM_WEBHOOK_SECRET=$(secret)
DASHBOARD_TOKEN=$(secret)

# Déjalo vacío para que el primer usuario que escriba /start quede como dueño,
# o pon aquí el ID de Telegram del cliente para blindarlo desde el inicio.
ALLOWED_USER_IDS=

GEMINI_MODEL=gemini-2.5-flash
CURRENCY=$CURRENCY
CURRENCY_SYMBOL=\$
TIMEZONE=$TIMEZONE
LOCALE_DECIMAL_COMMA=false
BUFFER_NAME=Colchón
BUFFER_INITIAL=0
LOG_LEVEL=INFO
EOF
