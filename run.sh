#!/usr/bin/env bash
#
# run.sh — Active l'environnement virtuel puis lance le serveur.
#
# Utilisation :
#     ./run.sh            → port 8000 (par défaut)
#     ./run.sh 9000       → port 9000
#     PORT=9000 ./run.sh  → port 9000 (autre façon)
#     HOST=0.0.0.0 ./run.sh → écoute sur toutes les interfaces (défaut 127.0.0.1)
#
# Si un fichier .env existe, il est chargé (configuration OAuth2, voir .env.example).
#
set -euo pipefail
cd "$(dirname "$0")"

if [ -t 1 ]; then
  RED=$'\033[31m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; OFF=$'\033[0m'
else
  RED=''; YELLOW=''; BOLD=''; OFF=''
fi
die() { printf '\n%s✗ %s%s\n\n' "$RED$BOLD" "$1" "$OFF"; exit 1; }

# --- Configuration locale (.env), sans écraser l'environnement déjà défini --
if [ -f .env ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"
    [ -z "${!key+x}" ] && export "$line"
  done < .env
fi

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
HOST="${HOST:-127.0.0.1}"
printf '  Ouvrez dans votre navigateur :  %s%s%s\n' "$BOLD" "${APP_URL:-http://127.0.0.1:$PORT}" "$OFF"
if [ -n "${OAUTH_SERVER_URL:-}" ]; then
  printf '  Connexion via :                 %s\n' "$OAUTH_SERVER_URL"
fi
printf '  Pour arrêter : %sCtrl+C%s\n\n' "$YELLOW" "$OFF"

# exec : le serveur remplace ce script (Ctrl+C l'arrête proprement).
# Un seul process : jobs en mémoire (app/jobs.py).
exec uvicorn app.main:app --host "$HOST" --port "$PORT" --proxy-headers
