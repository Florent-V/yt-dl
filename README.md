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

## Connexion par le serveur OAuth2 (optionnel)

Sans configuration, l'application est ouverte (usage local). Pour la protéger
par le serveur SSO, créez `.env` (`make init`, copie de `.env.example`) et
complétez-le. C'est le seul fichier de configuration, lu tel quel par `run.sh`
et par Docker (`make up`).

1. Déclarer l'application sur le serveur (redirect URI `APP_URL/auth/callback`,
   back-channel logout `APP_URL/auth/backchannel-logout`) et noter le secret.
2. Récupérer la clé publique : `make public-key` (`make prod-public-key` en
   production) écrit `var/oauth-public.pem`.
3. Donner l'accès aux utilisateurs (`make grant email=… app=…`).

L'application suit le modèle BFF du serveur : le navigateur n'a qu'un cookie de
session, les jetons restent côté serveur (SQLite, `var/oauth_state.sqlite3`),
renouvelés toutes les 15 min ; un refus ou un logout token ferme la session.
Le prénom de l'utilisateur s'affiche dans l'en-tête, avec **Sign out**.

Ouvrez l'application à l'adresse exacte de `APP_URL` (`localhost` et
`127.0.0.1` n'ont pas les mêmes cookies). Pour que le serveur OAuth (Docker)
joigne la route de back-channel en local : `HOST=0.0.0.0 ./run.sh 8765`.

## Déploiement Docker

Image de production : Python 3.12 slim, ffmpeg, dépendances figées par
`uv.lock` (deno inclus, nécessaire à yt-dlp pour YouTube), un seul process
uvicorn, utilisateur non-root. Même `.env` que sans Docker ; `compose.yaml`
ne fixe que ce qui tient au conteneur (chemins sous `/data` et `/run/secrets`).

    make init         # crée .env (à compléter)
    make public-key   # clé publique du serveur OAuth de dev → var/oauth-public.pem
                      #   (prod : make prod-public-key si le serveur OAuth est sur la même machine,
                      #    sinon copier sa clé publique dans var/oauth-public.pem)
    make up           # construit et démarre → http://127.0.0.1:8765
    make logs | make ps | make down

Le serveur OAuth peut tourner sur une autre machine : aucun réseau Docker
partagé. yt-dl le joint par `OAUTH_SERVER_URL` (`/token`, `/api/userinfo`), et
le serveur OAuth joint yt-dl par l'URI de back-channel déclarée chez lui,
`APP_URL/auth/backchannel-logout`. Les deux URL doivent donc être joignables
dans les deux sens.

En dev, avec le serveur OAuth en Docker sur la même machine, `localhost:8080`
n'est pas joignable depuis le conteneur (`localhost` y désigne le conteneur
lui-même). Le `.env` de dev ajoute donc `compose.dev.yaml` :

    COMPOSE_FILE=compose.yaml:compose.dev.yaml

yt-dl rejoint alors le réseau Docker du serveur OAuth de dev
(`oauth-serveur_default`) et l'appelle à `http://php:8080` ; le client OAuth de
dev déclare le back-channel `http://yt-dl:8765/auth/backchannel-logout`. Le
`.env` de prod n'a pas cette ligne. Sans Docker (`./run.sh`), le back-channel
du client de dev est `http://host.docker.internal:8765/auth/backchannel-logout`
(avec `HOST=0.0.0.0`).

`make help` liste toutes les commandes (local et Docker).

Procédures pas à pas : [mise en production](docs/mise-en-production.md),
[mise à jour](docs/mise-a-jour.md). Blocage YouTube (« Sign in to confirm
you're not a bot ») : [cookies](docs/youtube-cookies.md) ou
[sortie par la Freebox](docs/youtube-freebox.md).

### Sécurité du déploiement

- **Fail closed** : l'image fixe `REQUIRE_LOGIN=1`. Sans `OAUTH_SERVER_URL`,
  l'application refuse de démarrer au lieu de s'ouvrir sans authentification.
- **Réseau** : le port n'écoute que sur `127.0.0.1` (`HTTP_BIND`). Pour un
  accès extérieur, placez un reverse proxy HTTPS de l'hôte devant (Caddy,
  comme pour le serveur OAuth) et mettez `APP_URL` en `https://…` : le cookie
  devient `Secure` et HSTS est envoyé.
- **Secrets** : `.env` (droits 600, ignoré par git) contient le secret client ;
  dans le conteneur, c'est une variable d'environnement, visible par
  `docker inspect` (donc par qui contrôle Docker, déjà équivalent à root sur
  l'hôte). La clé publique est montée en lecture seule sous `/run/secrets`.
- **Conteneur** : système de fichiers en lecture seule (sauf le volume `/data`
  et un `/tmp` limité en tmpfs), toutes les capabilities retirées,
  `no-new-privileges`, limites de mémoire, CPU et nombre de processus,
  logs en rotation.
- **Application** : seuls les sites connus de yt-dlp sont acceptés (extracteur
  « generic » désactivé, contre le SSRF vers le réseau interne ;
  `YTDL_ALLOW_GENERIC=1` le réactive). Il y a aussi des en-têtes CSP et
  anti-framing, un téléchargement visible par son seul propriétaire, des
  limites (`MAX_ACTIVE_JOBS`, `MAX_FILESIZE`, `MIN_FREE_MB`) et une validation
  stricte des codes de langue.
- **Mises à jour** : yt-dlp casse régulièrement face à YouTube.
  `make lock-upgrade` puis `make up` ; `make audit` vérifie les CVE connues
  des dépendances.

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

    uv run pytest              # rapides, hors-ligne (104 tests)
    uv run pytest -m network   # téléchargements réels

## Fonctionnement

`yt-dlp` tourne comme bibliothèque Python, un thread par téléchargement. L'état
des tâches vit en mémoire, la progression arrive au navigateur par server-sent
events (SSE), et chaque tâche télécharge dans son propre dossier temporaire.

Rien n'est conservé après un téléchargement : le dossier temporaire est
supprimé une fois le fichier envoyé, ou après 30 minutes s'il ne l'a jamais
été. Pas d'historique ; la seule base est le petit SQLite des sessions OAuth.

L'appli s'installe comme PWA. Les icônes (`favicon.ico`, `icon-*.png`,
`apple-touch-icon.png`) sont générées depuis `assets/logo.png` :

    uv run --with pillow python assets/make-icons.py

Après un changement d'icônes, incrémenter `CACHE` dans `app/static/sw.js`.

## À savoir sur les dépendances

Pas de `requirements.txt` ici, et c'est voulu. `uv` sépare deux rôles que ce
fichier mélangeait :

- **`pyproject.toml`** — ce que le projet demande (les paquets directs :
  fastapi, uvicorn, yt-dlp, httpx, PyJWT). C'est la source de vérité, éditable.
- **`uv.lock`** — l'arbre complet figé aux versions exactes. Généré, garantit
  une installation identique partout.

Si un contexte `pip` l'exige, exportez un `requirements.txt` à la volée :

    uv export --format requirements-txt --no-dev --no-emit-project --no-hashes -o requirements.txt
