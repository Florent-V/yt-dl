#!/usr/bin/env bash
#
# check.sh — Diagnostic : vérifie que tout le nécessaire est installé.
# Ne modifie rien. Lance simplement : ./check.sh
#
set -uo pipefail
cd "$(dirname "$0")"

# Couleurs (désactivées si la sortie n'est pas un terminal).
if [ -t 1 ]; then
  GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; OFF=$'\033[0m'
else
  GREEN=''; RED=''; YELLOW=''; BOLD=''; OFF=''
fi

ok()   { printf '  %s✓%s  %s\n'      "$GREEN"  "$OFF" "$1"; }
bad()  { printf '  %s✗%s  %s\n'      "$RED"    "$OFF" "$1"; }
warn() { printf '  %s!%s  %s\n'      "$YELLOW" "$OFF" "$1"; }
hint() { printf '        %s→ %s%s\n' "$YELLOW" "$1"   "$OFF"; }

problems=0

printf '\n%sDiagnostic yt-dl%s\n' "$BOLD" "$OFF"
printf 'Vérification des outils nécessaires...\n\n'

# --- Python 3.11+ -----------------------------------------------------------
# Remarque : si uv est présent, il peut fournir Python lui-même. Python
# système est donc « recommandé » mais pas strictement obligatoire.
if command -v python3 >/dev/null 2>&1; then
  version=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)
  if python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    ok "Python $version (3.11 ou plus récent : parfait)"
  else
    warn "Python $version détecté, mais la version 3.11+ est recommandée"
    hint "uv pourra installer une version compatible tout seul lors de l'installation"
  fi
else
  warn "Python n'est pas installé sur le système"
  hint "uv pourra l'installer tout seul lors de l'installation — pas bloquant"
fi

# --- uv ---------------------------------------------------------------------
if command -v uv >/dev/null 2>&1; then
  ok "uv $(uv --version 2>/dev/null | awk '{print $2}') (gestionnaire de l'application)"
else
  bad "uv n'est pas installé  — c'est lui qui installe et lance l'application"
  hint "Lancez  ./install.sh  : il propose de l'installer pour vous"
  problems=$((problems + 1))
fi

# --- ffmpeg -----------------------------------------------------------------
if command -v ffmpeg >/dev/null 2>&1; then
  ok "ffmpeg (assemble la vidéo, l'audio et les sous-titres)"
else
  bad "ffmpeg n'est pas installé  — indispensable pour fusionner et convertir"
  hint "Ubuntu/Debian :  sudo apt install ffmpeg"
  hint "macOS (Homebrew) :  brew install ffmpeg"
  problems=$((problems + 1))
fi

# --- Dépendances de l'application (le dossier .venv créé par uv) -------------
if [ -d .venv ]; then
  ok "Dépendances installées (dossier .venv présent)"
else
  warn "Dépendances pas encore installées"
  hint "Lancez  ./install.sh  pour les installer"
fi

# --- Verdict ----------------------------------------------------------------
printf '\n'
if [ "$problems" -eq 0 ]; then
  printf '%s✓ Tout est prêt.%s Lancez l'\''application avec :  %s./run.sh%s\n\n' \
    "$GREEN$BOLD" "$OFF" "$BOLD" "$OFF"
  exit 0
else
  printf '%s✗ %d élément(s) manquant(s).%s Lancez  %s./install.sh%s  pour corriger.\n\n' \
    "$RED$BOLD" "$problems" "$OFF" "$BOLD" "$OFF"
  exit 1
fi
