#!/usr/bin/env bash
#
# run.sh — Active l'environnement virtuel puis lance le serveur.
#
# Utilisation :
#     ./run.sh            → port 8000 (par défaut)
#     ./run.sh 9000       → port 9000
#     PORT=9000 ./run.sh  → port 9000 (autre façon)
#
set -euo pipefail
cd "$(dirname "$0")"

if [ -t 1 ]; then
  RED=$'\033[31m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; OFF=$'\033[0m'
else
  RED=''; YELLOW=''; BOLD=''; OFF=''
fi
die() { printf '\n%s✗ %s%s\n\n' "$RED$BOLD" "$1" "$OFF"; exit 1; }

# --- Port : 1er argument, sinon variable PORT, sinon 8000 -------------------
PORT="${1:-${PORT:-8000}}"
if ! printf '%s' "$PORT" | grep -Eq '^[0-9]+$' || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  die "Port invalide : « $PORT ». Donnez un nombre entre 1 et 65535, ex :  ./run.sh 9000"
fi

# --- L'environnement virtuel doit exister -----------------------------------
if [ ! -f .venv/bin/activate ]; then
  die "Environnement introuvable. Lancez d'abord :  ./install.sh"
fi

# --- Activer le venv (valable dans ce processus, suffit pour le serveur) -----
# shellcheck disable=SC1091
source .venv/bin/activate

command -v uvicorn >/dev/null 2>&1 || die "uvicorn absent de l'environnement. Relancez :  ./install.sh"

printf '\n%s▸ Serveur yt-dl%s\n' "$BOLD" "$OFF"
printf '  Ouvrez dans votre navigateur :  %shttp://127.0.0.1:%s%s\n' "$BOLD" "$PORT" "$OFF"
printf '  Pour arrêter : %sCtrl+C%s\n\n' "$YELLOW" "$OFF"

# exec : le serveur remplace ce script (Ctrl+C l'arrête proprement).
exec uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
