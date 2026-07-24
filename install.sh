#!/usr/bin/env bash
#
# install.sh — Installe tout ce qu'il faut pour l'application.
# Crée l'environnement isolé (.venv) et y installe les dépendances.
# Lancez simplement : ./install.sh
#
set -uo pipefail
cd "$(dirname "$0")"

if [ -t 1 ]; then
  GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; OFF=$'\033[0m'
else
  GREEN=''; RED=''; YELLOW=''; BOLD=''; OFF=''
fi

step() { printf '\n%s▸ %s%s\n'  "$BOLD"  "$1" "$OFF"; }
ok()   { printf '  %s✓%s %s\n'  "$GREEN" "$OFF" "$1"; }
die()  { printf '\n  %s✗ %s%s\n\n' "$RED$BOLD" "$1" "$OFF"; exit 1; }

printf '\n%sInstallation de yt-dl%s\n' "$BOLD" "$OFF"

# --- 1. ffmpeg (le script ne peut pas l'installer sans mot de passe admin) ---
step "Vérification de ffmpeg"
if command -v ffmpeg >/dev/null 2>&1; then
  ok "ffmpeg déjà présent"
else
  printf '  %sffmpeg est absent.%s Installez-le puis relancez ce script :\n' "$YELLOW" "$OFF"
  printf '    Ubuntu/Debian :  %ssudo apt install ffmpeg%s\n' "$BOLD" "$OFF"
  printf '    macOS         :  %sbrew install ffmpeg%s\n' "$BOLD" "$OFF"
  die "ffmpeg requis (demande le mot de passe administrateur, à faire à la main)"
fi

# --- 2. uv ------------------------------------------------------------------
step "Vérification de uv"
if command -v uv >/dev/null 2>&1; then
  ok "uv déjà présent ($(uv --version 2>/dev/null | awk '{print $2}'))"
else
  printf '  uv est absent. C'\''est l'\''outil qui installe et lance l'\''application.\n'
  printf '  Voulez-vous l'\''installer maintenant ? [O/n] '
  read -r answer
  case "${answer:-o}" in
    [nN]*) die "Installation annulée. uv est nécessaire pour continuer." ;;
  esac
  printf '  Téléchargement de uv depuis astral.sh...\n'
  curl -LsSf https://astral.sh/uv/install.sh | sh || die "Le téléchargement de uv a échoué (connexion internet ?)"
  # Rendre uv utilisable immédiatement dans ce script.
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || die "uv installé mais introuvable — fermez et rouvrez le terminal, puis relancez ./install.sh"
  ok "uv installé"
fi

# --- 3. Environnement + dépendances -----------------------------------------
# 'uv sync' crée l'environnement isolé .venv ET y installe les dépendances,
# en une seule commande. --extra dev ajoute les outils de test.
step "Création de l'environnement et installation des dépendances"
printf '  (peut prendre une minute la première fois)\n'
uv sync --extra dev || die "L'installation des dépendances a échoué"
ok "Environnement .venv prêt et dépendances installées"

# --- Fin --------------------------------------------------------------------
printf '\n%s✓ Installation terminée.%s\n\n' "$GREEN$BOLD" "$OFF"
printf 'Pour lancer l'\''application :\n'
printf '    %s./run.sh%s\n' "$BOLD" "$OFF"
printf '  puis ouvrez  %shttp://127.0.0.1:8000%s  dans votre navigateur.\n\n' "$BOLD" "$OFF"
printf '%sÀ savoir :%s ./run.sh utilise l'\''environnement .venv automatiquement —\n' "$YELLOW" "$OFF"
printf 'aucune « activation » manuelle n'\''est nécessaire.\n'
printf 'Si vous voulez quand même l'\''activer à la main :  %ssource .venv/bin/activate%s\n\n' "$BOLD" "$OFF"
