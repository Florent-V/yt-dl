# Mise en production initiale

Installation de yt-dl sur le serveur d'applications, derrière le Caddy de l'hôte, protégé
par le serveur OAuth2 (« vauban »). Le serveur OAuth peut être sur la même machine ou sur
une autre : les deux ne se parlent que par leurs URL publiques en HTTPS. À faire une seule fois ; pour les déploiements suivants, voir
[mise-a-jour.md](mise-a-jour.md).

| | |
|---|---|
| Serveur OAuth | `/var/www/vauban` (sur sa machine) |
| Application | `/var/www/vauban-ytdl` |
| Domaine de l'appli | `yt.mondomaine.fr` *(à remplacer partout)* |
| Domaine du serveur OAuth | `oauth.mondomaine.fr` *(à remplacer partout)* |

## Prérequis

- [x] Le serveur OAuth tourne en production et répond sur `https://oauth.mondomaine.fr`
- [x] Depuis la machine de yt-dl, il est joignable :
      `curl -sI https://oauth.mondomaine.fr/login | head -1` → `HTTP/2 200`
- [x] Caddy est installé sur la machine de yt-dl
- [x] `git`, `make` et Docker (avec le plugin `compose`) sont installés
- [x] Mon utilisateur est dans le groupe `docker` (`groups`), sinon :
      `sudo usermod -aG docker $USER` puis se reconnecter

> ⚠️ Toutes les commandes `make` se lancent **sans `sudo`**. L'image reprend l'UID de
> l'utilisateur qui la construit ; en root, la construction échoue.

## 1. DNS

- [x] Enregistrement `A` `yt.mondomaine.fr` → IP du serveur (et `AAAA` si IPv6)
- [x] Propagation vérifiée : `dig +short yt.mondomaine.fr` renvoie l'IP du serveur

Sans DNS, Caddy ne pourra pas obtenir le certificat à l'étape 6.

## 2. Déclarer l'application dans le serveur OAuth

Sur la machine du serveur OAuth :

```bash
cd /var/www/vauban
make prod-app name="yt-dl" id=yt-dl url=https://yt.mondomaine.fr
```

Cela déclare la redirect URI `https://yt.mondomaine.fr/auth/callback` et l'URI de
back-channel `https://yt.mondomaine.fr/auth/backchannel-logout`.

- [x] Application `yt-dl` créée
- [x] **Client secret copié** (il est stocké haché, il ne sera plus jamais affiché)

```bash
make prod-grant email=toi@mondomaine.fr app=yt-dl
grep ^DEFAULT_URI .env.docker      # .env.docker du serveur OAuth
make prod-public-key               # clé publique, à copier à l'étape 4
```

- [x] Accès donné à mon compte
- [x] Valeur de `DEFAULT_URI` notée (sera `OAUTH_SERVER_URL`, à l'identique, sans `/` final)
- [x] Clé publique copiée (bloc `-----BEGIN PUBLIC KEY-----` … `-----END PUBLIC KEY-----`)

## 3. Récupérer le code

Le dépôt est privé : le serveur le lit avec une clé de déploiement **en lecture seule**.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/ytdl_deploy -N "" -C "deploy vauban-ytdl"
cat ~/.ssh/ytdl_deploy.pub
```

- [x] Clé publique ajoutée sur GitHub : dépôt → *Settings → Deploy keys → Add deploy key*,
      **sans** cocher *Allow write access*

```bash
sudo mkdir /var/www/vauban-ytdl && sudo chown $USER: /var/www/vauban-ytdl
GIT_SSH_COMMAND="ssh -i ~/.ssh/ytdl_deploy" \
  git clone git@github.com:Florent-V/yt-dl.git /var/www/vauban-ytdl
cd /var/www/vauban-ytdl
git config core.sshCommand "ssh -i ~/.ssh/ytdl_deploy"
```

- [x] Dépôt cloné dans `/var/www/vauban-ytdl`
- [x] `git pull` fonctionne sans demander de mot de passe

## 4. Configuration

Un seul fichier, `.env` (droits 600, jamais commité), le même qu'en développement.

```bash
cd /var/www/vauban-ytdl
make init               # crée .env depuis .env.example
nano var/oauth-public.pem   # coller la clé publique de l'étape 2
```

(Si le serveur OAuth est sur la même machine, `make prod-public-key` écrit ce fichier
directement depuis `/var/www/vauban`.)

- [x] `.env` créé
- [x] `var/oauth-public.pem` écrit (commence par `-----BEGIN PUBLIC KEY-----`)

Dans `.env`, renseigner :

```ini
APP_URL=https://yt.mondomaine.fr
OAUTH_SERVER_URL=https://oauth.mondomaine.fr
OAUTH_CLIENT_ID=yt-dl
OAUTH_CLIENT_SECRET=<secret de l'étape 2>
```

- [x] `APP_URL` en `https://`, sans `/` final
- [x] `OAUTH_SERVER_URL` identique au `DEFAULT_URI` noté à l'étape 2, sans `/` final
- [x] `OAUTH_CLIENT_ID=yt-dl` et `OAUTH_CLIENT_SECRET` renseignés
- [x] Limites relues (`MAX_ACTIVE_JOBS`, `MAX_FILESIZE`, `MIN_FREE_MB`)

`OAUTH_INTERNAL_URL` reste vide : yt-dl appelle le serveur OAuth à `OAUTH_SERVER_URL`.

## 5. Démarrer le conteneur

```bash
make check     # ✓ configuration valide
make up        # construit l'image et démarre
make ps        # attendre « healthy » (~15 s)
make health    # {"status":"ok"}
```

- [x] `make check` affiche « configuration valide »
- [x] `make ps` affiche `healthy`
- [x] `make health` renvoie `{"status":"ok"}`

En cas d'échec : `make logs`.

| Message | Cause |
|---|---|
| `REQUIRE_LOGIN is set but OAUTH_SERVER_URL is empty` | `.env` incomplet |
| `Permission denied` sur `/run/secrets/…` | `make` lancé avec `sudo`, ou `var/oauth-public.pem` créé par un autre utilisateur |
| `✗ OAUTH_CLIENT_SECRET vide dans .env` (`make check`) | secret de l'étape 2 non reporté |

## 6. Caddy (HTTPS)

Ajouter dans `/etc/caddy/Caddyfile` :

```caddyfile
yt.mondomaine.fr {
	encode zstd gzip
	header -Server

	reverse_proxy 127.0.0.1:8765 {
		# Progression en direct (server-sent events) : pas de mise en tampon
		flush_interval -1
	}

	log {
		output file /var/log/caddy/yt-dl.access.log {
			roll_size 20mb
			roll_keep 10
		}
		# Pas de code OAuth ni de cookie de session dans les journaux
		format filter {
			request>uri regexp "([?&](?:code|state)=)[^&]*" "${1}REDACTED"
			request>headers>Cookie delete
		}
	}
}
```

```bash
caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

- [x] `caddy validate` sans erreur
- [x] Caddy rechargé
- [x] `https://yt.mondomaine.fr/api/health` renvoie `{"status":"ok"}` avec un certificat valide

## 7. Recette

- [ ] `https://yt.mondomaine.fr` redirige vers la page de connexion du serveur OAuth
- [ ] Après connexion, retour sur l'appli avec mon prénom affiché
- [ ] Analyse d'une URL YouTube : titre et formats affichés
- [ ] Téléchargement vidéo d'une vidéo courte : progression en direct, fichier lisible
- [ ] Téléchargement audio (mp3) : fichier lisible
- [ ] Back-channel : sur la machine du serveur OAuth, depuis `/var/www/vauban`,
      `make prod-console c="app:application:test-backchannel-logout yt-dl toi@mondomaine.fr"`
      → au clic suivant dans l'appli, retour à la page de connexion
- [ ] Déconnexion depuis l'appli : la session SSO est fermée aussi
- [ ] Sur mobile : « Ajouter à l'écran d'accueil » affiche la bonne icône

Si YouTube répond « Sign in to confirm you're not a bot », l'IP du serveur est filtrée par
YouTube : ce n'est pas un problème de déploiement (voir [mise-a-jour.md](mise-a-jour.md),
« yt-dlp ne fonctionne plus »).

## Après la mise en production

- [ ] GitHub : *Settings → Branches* : protéger `main` (CI verte requise, pas de force-push)
- [ ] GitHub : *Settings → Code security* : alertes Dependabot activées
- [ ] Noter ici la date et le commit déployé : `git log -1 --oneline`
