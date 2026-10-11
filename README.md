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
par le serveur SSO, copiez `.env.example` en `.env` et complétez-le ; `run.sh`
le charge au démarrage.

1. Déclarer l'application sur le serveur (redirect URI `APP_URL/auth/callback`,
   back-channel logout `APP_URL/auth/backchannel-logout`) et noter le secret.
2. Récupérer la clé publique : `make public-key > var/oauth-public.pem`
   (dans le dépôt du serveur ; `make prod-public-key` en production).
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
uvicorn, utilisateur non-root. Le conteneur rejoint le réseau Docker du
serveur OAuth (`oauth-serveur_default` par défaut, celui du dev). En prod
(serveur OAuth dans `/var/www/vauban`), c'est `vauban_default` : le donner dans
`.env` (`OAUTH_NETWORK=vauban_default`)
ou dans le shell : Compose lit cette variable pour interpréter `compose.yaml`,
pas dans `.env.docker`.

    make init         # crée .env.docker (à compléter) et secrets/
    make secret       # secret du client OAuth (saisie masquée) → secrets/oauth_client_secret
    make public-key   # clé publique du serveur OAuth de dev → secrets/oauth-public.pem
                      #   (prod : make prod-public-key, serveur OAuth dans /var/www/vauban)
    make up           # construit et démarre → http://127.0.0.1:8765
    make logs | make ps | make down

Côté serveur OAuth, l'URI de back-channel logout devient
`http://yt-dl:8765/auth/backchannel-logout` (alias réseau du conteneur).
`OAUTH_SERVER_URL` est l'adresse vue par le navigateur ; `OAUTH_INTERNAL_URL`
(`http://php:8080`) celle utilisée par le conteneur pour `/token` et `/api/userinfo`.

`make help` liste toutes les commandes (local et Docker).

### Sécurité du déploiement

- **Fail closed** : l'image fixe `REQUIRE_AUTH=1`. Sans `OAUTH_SERVER_URL`,
  l'application refuse de démarrer au lieu de s'ouvrir sans authentification.
- **Réseau** : le port n'écoute que sur `127.0.0.1` (`HTTP_BIND`). Pour un
  accès extérieur, placez un reverse proxy HTTPS de l'hôte devant (Caddy,
  comme pour le serveur OAuth) et mettez `APP_URL` en `https://…` : le cookie
  devient `Secure` et HSTS est envoyé.
- **Secrets** : le secret client et la clé publique sont des secrets Compose
  (fichiers en lecture seule sous `/run/secrets`), absents des variables
  d'environnement et de `docker inspect`. `secrets/` et `.env.docker` sont ignorés par git.
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
