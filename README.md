# yt-dl

Téléchargeur YouTube local, pour usage personnel. Tourne sur `localhost`,
télécharge une vidéo à la fois, et remet le fichier via votre navigateur.

Vidéo (qualité au choix + sous-titres intégrés) ou audio seul (MP3 / M4A / Opus,
débit au choix, ou flux d'origine sans ré-encodage).

## Prérequis système

À installer vous-même une fois (le script `install.sh` n'y touche pas) :

- **ffmpeg** — assemble vidéo + audio + sous-titres
  - Ubuntu/Debian : `sudo apt install ffmpeg`
  - macOS : `brew install ffmpeg`
- **uv** — construit et gère l'environnement Python
  ([doc](https://docs.astral.sh/uv/)). `install.sh` propose de l'installer si absent.
- **Python 3.11+** — recommandé, mais `uv` sait en fournir un si besoin.

## Installation

Trois scripts, dans l'ordre :

    ./check.sh      # 1. Diagnostic : que manque-t-il ? (ne modifie rien)
    ./install.sh    # 2. Crée l'environnement .venv + installe les dépendances Python
    ./run.sh        # 3. Lance le serveur

`check.sh` sépare ce que vous devez installer vous-même (outils système) de ce
que `install.sh` prend en charge (environnement de l'application).

Alternative en une commande si vous maîtrisez déjà uv :

    uv sync --extra dev

## Lancement

    ./run.sh          # port 8000 par défaut
    ./run.sh 9000     # port de votre choix

`run.sh` active l'environnement `.venv` tout seul puis démarre le serveur.
Ouvrez l'adresse affichée (http://127.0.0.1:8000 par défaut).
Pour arrêter le serveur : `Ctrl+C`.

## Utilisation

1. Collez une URL YouTube et cliquez **Probe**.
2. Choisissez **Video** — qualité, conteneur, pistes de sous-titres — ou
   **Audio** — format et débit.
3. Cliquez **Download**. La progression s'affiche en direct, et le fichier est
   enregistré par votre navigateur une fois prêt.

Les qualités sont dessinées en échelle : la largeur de chaque barre représente
la taille approximative du fichier, pour comparer d'un coup d'œil.

Sélectionner un sous-titre bascule le conteneur en MKV, qui porte les
sous-titres comme des pistes activables — MP4 les convertit dans un format que
beaucoup de lecteurs ignorent. Vous pouvez revenir à MP4 si besoin.

Sous Audio, **Best** garde le flux d'origine sans ré-encodage : le réglage de
débit ne s'applique alors pas et reste désactivé.

## Tests

    uv run pytest              # rapides, hors-ligne (54 tests)
    uv run pytest -m network   # téléchargements réels

## Fonctionnement

`yt-dlp` tourne comme bibliothèque Python, un thread par téléchargement. L'état
des tâches vit en mémoire, la progression arrive au navigateur par server-sent
events (SSE), et chaque tâche télécharge dans son propre dossier temporaire.

Rien n'est conservé après un téléchargement : le dossier temporaire est
supprimé une fois le fichier envoyé, ou après 30 minutes s'il ne l'a jamais
été. Pas d'historique, pas de base de données, pas d'authentification — conçu
pour tourner sur votre machine, pour votre usage.

## À savoir sur les dépendances

Pas de `requirements.txt` ici, et c'est voulu. `uv` sépare deux rôles que ce
fichier mélangeait :

- **`pyproject.toml`** — ce que le projet demande (les 3 paquets directs :
  fastapi, uvicorn, yt-dlp). C'est la source de vérité, éditable.
- **`uv.lock`** — l'arbre complet figé aux versions exactes. Généré, garantit
  une installation identique partout.

Si un contexte `pip` l'exige, exportez un `requirements.txt` à la volée :

    uv export --format requirements-txt --no-dev --no-emit-project --no-hashes -o requirements.txt
