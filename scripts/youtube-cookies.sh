#!/usr/bin/env bash
# Exporte les cookies YouTube d'un compte JETABLE et les envoie au serveur.
# À lancer sur sa machine perso (pas sur le serveur). Voir docs/youtube-cookies.md.
#
#   ./scripts/youtube-cookies.sh user@serveur     # export + envoi
#   ./scripts/youtube-cookies.sh                  # export seul, dans ./youtube-cookies.txt
#
# Variables facultatives :
#   YTDL_COOKIE_PROFILE  profil Firefox dédié   (défaut : ~/ytdl-cookies-profile)
#   YTDL_REMOTE_FILE     chemin sur le serveur  (défaut : /var/www/vauban-ytdl/var/youtube/cookies.txt)
set -euo pipefail

SERVER="${1:-}"
PROFILE="${YTDL_COOKIE_PROFILE:-$HOME/ytdl-cookies-profile}"   # pas de dossier caché : Firefox snap n'y a pas accès
REMOTE_FILE="${YTDL_REMOTE_FILE:-/var/www/vauban-ytdl/var/youtube/cookies.txt}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEST_VIDEO="https://www.youtube.com/watch?v=jNQXAC9IVRw"     # « Me at the zoo », 19 s

command -v firefox >/dev/null || { echo "✗ firefox introuvable"; exit 1; }
command -v uv >/dev/null || { echo "✗ uv introuvable"; exit 1; }

if [ ! -d "$PROFILE" ]; then
  mkdir -p "$PROFILE"
  chmod 700 "$PROFILE"
  URL="https://accounts.google.com/ServiceLogin?service=youtube&continue=https://www.youtube.com/"
  echo "Premier lancement : profil Firefox dédié créé dans $PROFILE"
  echo "→ Connecte-toi au compte YouTube JETABLE (pas ton compte perso), puis ferme Firefox."
else
  URL="https://www.youtube.com/robots.txt"
  echo "→ Ferme Firefox dès que la page est chargée."
fi
# --no-remote : instance séparée, même si ton Firefox habituel est ouvert ; bloque jusqu'à la fermeture
firefox --no-remote --profile "$PROFILE" "$URL" >/dev/null 2>&1

# Le fichier ne doit pas exister : yt-dlp lit d'abord le fichier --cookies s'il est présent
TMPDIR_COOKIES=$(mktemp -d)
trap 'rm -rf "$TMPDIR_COOKIES"' EXIT
OUT="$TMPDIR_COOKIES/cookies.txt"
umask 077

# yt-dlp lit les cookies du profil et les écrit au format Netscape attendu par --cookies.
# La requête de test sert aussi à vérifier que le compte est bien reconnu.
uv run --project "$PROJECT_DIR" yt-dlp \
  --cookies-from-browser "firefox:$PROFILE" --cookies "$OUT" \
  --skip-download --quiet --no-warnings "$TEST_VIDEO"

grep -q '__Secure-3PSID' "$OUT" \
  || { echo "✗ Pas de session YouTube dans ce profil : relance et connecte-toi."; exit 1; }

if [ -z "$SERVER" ]; then
  install -m 600 "$OUT" ./youtube-cookies.txt
  echo "✓ Cookies écrits dans ./youtube-cookies.txt (à garder privé, à ne jamais commiter)"
else
  REMOTE_DIR=$(dirname "$REMOTE_FILE")
  # Copie puis renommage : yt-dl ne lit jamais un fichier à moitié écrit
  ssh "$SERVER" "mkdir -p -m 700 '$REMOTE_DIR'"
  scp -q "$OUT" "$SERVER:$REMOTE_FILE.tmp"
  ssh "$SERVER" "chmod 600 '$REMOTE_FILE.tmp' && mv '$REMOTE_FILE.tmp' '$REMOTE_FILE'"
  echo "✓ Cookies envoyés vers $SERVER:$REMOTE_FILE"
fi
