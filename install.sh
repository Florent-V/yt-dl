#!/usr/bin/env bash
#
# install.sh — Prépare l'application.
#
#   • NE réinstalle PAS les outils système déjà présents (ffmpeg, uv).
#   • Crée l'environnement virtuel Python (.venv).
#   • Installe les dépendances Python DANS cet environnement.
#
# Lancez simplement : ./install.sh
#
set -uo pipefail
cd "$(dirname "$0")"

if [ -t 1 ]; then
  GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; OFF=$'\033[0m'
else
  GREEN=''; RED=''; YELLOW=''; BOLD=''; OFF=''
fi

step() { printf '\n%s▸ %s%s\n'      "$BOLD"  "$1" "$OFF"; }
ok()   { printf '  %s✓%s %s\n'      "$GREEN" "$OFF" "$1"; }
skip() { printf '  %s•%s %s\n'      "$YELLOW" "$OFF" "$1"; }
die()  { printf '\n  %s✗ %s%s\n\n'  "$RED$BOLD" "$1" "$OFF"; exit 1; }

printf '\n%sInstallation de yt-dl%s\n' "$BOLD" "$OFF"

# --- 1. ffmpeg : outil système, jamais réinstallé ici -----------------------
# (son installation demande le mot de passe administrateur : à faire à la main)
step "ffmpeg (outil système)"
if command -v ffmpeg >/dev/null 2>&1; then
  skip "déjà installé — on n'y touche pas"
else
  printf '  %sAbsent.%s Installez-le vous-même puis relancez ce script :\n' "$YELLOW" "$OFF"
  printf '    Ubuntu/Debian :  %ssudo apt install ffmpeg%s\n' "$BOLD" "$OFF"
  printf '    macOS         :  %sbrew install ffmpeg%s\n'    "$BOLD" "$OFF"
  die "ffmpeg requis avant de continuer"
fi

# --- 2. uv : doit rester GLOBAL (c'est lui qui crée le venv) -----------------
# uv ne peut pas vivre dans le venv : il faut qu'il existe AVANT de le créer.
# C'est la seule dépendance système que ce script propose d'installer, car
# elle est indispensable pour construire l'environnement Python.
step "uv (crée l'environnement, doit rester global)"
if command -v uv >/dev/null 2>&1; then
  skip "déjà installé — on n'y touche pas ($(uv --version 2>/dev/null | awk '{print $2}'))"
else
  printf '  Absent. C'\''est l'\''outil qui construit l'\''environnement Python.\n'
  printf '  L'\''installer maintenant ? [O/n] '
  read -r answer
  case "${answer:-o}" in
    [nN]*) die "Installation annulée — uv est indispensable" ;;
  esac
  curl -LsSf https://astral.sh/uv/install.sh | sh \
    || die "Téléchargement de uv échoué (connexion internet ?)"
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 \
    || die "uv installé mais introuvable — fermez/rouvrez le terminal puis relancez ./install.sh"
  ok "uv installé"
fi

# --- 3. Environnement virtuel + dépendances Python --------------------------
# 'uv sync' fait les deux d'un coup : il crée .venv (Python isolé) et y
# installe exactement les versions figées dans uv.lock. --extra dev ajoute
# les outils de test.
step "Environnement virtuel Python + dépendances"
printf '  (peut prendre une minute la première fois)\n'
uv sync --extra dev || die "Installation des dépendances Python échouée"
ok "Environnement .venv créé et dépendances installées"

# --- Fin --------------------------------------------------------------------
printf '\n%s✓ Installation terminée.%s\n\n' "$GREEN$BOLD" "$OFF"
printf 'Lancer l'\''application :\n'
printf '    %s./run.sh%s          (port 8000)\n'   "$BOLD" "$OFF"
printf '    %s./run.sh 9000%s     (port de votre choix)\n\n' "$BOLD" "$OFF"
printf '%sÀ savoir :%s ./run.sh active l'\''environnement .venv tout seul.\n' "$YELLOW" "$OFF"
printf 'Un script ne peut pas activer le venv dans votre terminal (limite Unix) :\n'
printf 'si vous voulez l'\''activer à la main pour travailler dedans, tapez :\n'
printf '    %ssource .venv/bin/activate%s\n\n' "$BOLD" "$OFF"
