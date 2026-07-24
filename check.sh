#!/usr/bin/env bash
#
# check.sh — Diagnostic. Vérifie ce qui est installé. NE MODIFIE RIEN.
# Lancez simplement : ./check.sh
#
set -uo pipefail
cd "$(dirname "$0")"

if [ -t 1 ]; then
  GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; OFF=$'\033[0m'
else
  GREEN=''; RED=''; YELLOW=''; BOLD=''; OFF=''
fi

ok()   { printf '  %s✓%s  %s\n'      "$GREEN"  "$OFF" "$1"; }
bad()  { printf '  %s✗%s  %s\n'      "$RED"    "$OFF" "$1"; }
warn() { printf '  %s!%s  %s\n'      "$YELLOW" "$OFF" "$1"; }
hint() { printf '        %s→ %s%s\n' "$YELLOW" "$1"   "$OFF"; }

missing_system=0   # à installer soi-même (droits admin / outil global)
missing_app=0      # réparable via ./install.sh

printf '\n%sDiagnostic yt-dl%s\n\n' "$BOLD" "$OFF"

# ===========================================================================
printf '%sOutils système%s  (à installer vous-même si absents)\n' "$BOLD" "$OFF"
# ===========================================================================

# --- ffmpeg : indispensable, installation manuelle (mot de passe admin) -----
if command -v ffmpeg >/dev/null 2>&1; then
  ok "ffmpeg (assemble vidéo + audio + sous-titres)"
else
  bad "ffmpeg absent — indispensable"
  hint "Ubuntu/Debian :  sudo apt install ffmpeg"
  hint "macOS         :  brew install ffmpeg"
  missing_system=$((missing_system + 1))
fi

# --- Python 3.11+ : recommandé, mais uv sait en fournir un ------------------
if command -v python3 >/dev/null 2>&1; then
  version=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)
  if python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    ok "Python $version"
  else
    warn "Python $version présent, 3.11+ recommandé"
    hint "Pas bloquant : uv installera une version compatible pour l'application"
  fi
else
  warn "Python système absent"
  hint "Pas bloquant : uv en installera un pour l'application"
fi

# --- uv : outil global qui construit l'environnement ------------------------
if command -v uv >/dev/null 2>&1; then
  ok "uv $(uv --version 2>/dev/null | awk '{print $2}') (construit et gère l'environnement)"
else
  bad "uv absent — construit l'environnement de l'application"
  hint "./install.sh propose de l'installer pour vous"
  missing_system=$((missing_system + 1))
fi

# ===========================================================================
printf '\n%sApplication%s  (réparable avec ./install.sh)\n' "$BOLD" "$OFF"
# ===========================================================================

# --- Environnement virtuel + dépendances Python -----------------------------
if [ -f .venv/bin/uvicorn ]; then
  ok "Environnement .venv prêt (dépendances Python installées)"
else
  warn "Environnement Python pas encore installé"
  hint "Lancez  ./install.sh"
  missing_app=$((missing_app + 1))
fi

# --- Verdict ----------------------------------------------------------------
printf '\n'
if [ "$missing_system" -gt 0 ]; then
  printf '%s✗ Installez d'\''abord les outils système ci-dessus,%s puis lancez  %s./install.sh%s\n\n' \
    "$RED$BOLD" "$OFF" "$BOLD" "$OFF"
  exit 1
elif [ "$missing_app" -gt 0 ]; then
  printf '%s! Outils système OK.%s Lancez  %s./install.sh%s  pour finir.\n\n' \
    "$YELLOW$BOLD" "$OFF" "$BOLD" "$OFF"
  exit 1
else
  printf '%s✓ Tout est prêt.%s Lancez :  %s./run.sh%s  (ou  %s./run.sh 9000%s  pour un autre port)\n\n' \
    "$GREEN$BOLD" "$OFF" "$BOLD" "$OFF" "$BOLD" "$OFF"
  exit 0
fi
