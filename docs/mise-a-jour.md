# Mise à jour en production

À faire après chaque merge sur `main` à déployer (fonctionnalité, correctif, PR
Dependabot). Première installation : voir [mise-en-production.md](mise-en-production.md).

Durée : quelques minutes. Le redémarrage coupe le service ~15 s ; les sessions sont
conservées (volume `/data`), mais **un téléchargement en cours est perdu**.

## 1. Avant de déployer

- [ ] La CI est verte sur le dernier commit de `main` (onglet *Actions* sur GitHub)
- [ ] Aucun téléchargement en cours (sinon il sera interrompu)

```bash
cd /var/www/vauban-ytdl
git log -1 --oneline        # commit actuellement déployé : à noter pour un retour arrière
git fetch
git log --oneline HEAD..origin/main
git diff --stat HEAD origin/main -- .env.example compose.yaml Dockerfile Makefile
```

- [ ] Commit actuel noté : `__________`
- [ ] Commits à déployer relus
- [ ] Si `.env.example` a changé : `git diff HEAD origin/main -- .env.example`,
      reporter les nouvelles variables dans `.env`
- [ ] Si `compose.yaml` a changé : relu (nouveau secret, nouveau volume, nouveau réseau ?)

## 2. Déployer

```bash
git pull --ff-only
make build     # reconstruit l'image (--pull : récupère aussi les correctifs de l'image Python)
make up        # remplace le conteneur
make ps        # attendre « healthy »
make health    # {"status":"ok"}
```

- [ ] `git pull --ff-only` sans erreur (sinon : modification locale sur le serveur, à
      examiner avec `git status`, ne jamais forcer)
- [ ] `make ps` affiche `healthy`
- [ ] `make health` renvoie `{"status":"ok"}`

## 3. Vérifier

- [ ] `make logs` : pas d'erreur au démarrage (Ctrl+C pour quitter)
- [ ] `https://yt.mondomaine.fr` : connexion OK, appli affichée
- [ ] Un téléchargement court fonctionne
- [ ] Ce qui a changé dans ce déploiement fonctionne

Ménage occasionnel (anciennes images) :

```bash
docker image prune -f
```

## Retour arrière

Si la nouvelle version ne fonctionne pas, revenir au commit noté à l'étape 1 :

```bash
git checkout <commit-noté>
make up
make health
```

- [ ] Ancienne version de nouveau en service
- [ ] Problème reporté / corrigé sur `main`, puis retour sur la branche :
      `git checkout main && git pull --ff-only && make build && make up`

## Cas particuliers

### yt-dlp ne fonctionne plus

YouTube change souvent ; yt-dlp suit. Symptômes : erreurs à l'analyse ou au téléchargement
sur des vidéos qui fonctionnaient.

- [ ] En local : `make lock-upgrade`, `make test`, puis commit et push de `uv.lock`
      (ou merger la PR Dependabot « yt-dlp » si elle existe)
- [ ] CI verte, puis procédure de mise à jour ci-dessus

« Sign in to confirm you're not a bot » : l'IP du serveur est filtrée par YouTube. Une
mise à jour de yt-dlp aide parfois ; sinon, deux solutions :
[cookies d'un compte jetable](youtube-cookies.md) ou
[sortie par la Freebox](youtube-freebox.md).

### Changement du secret OAuth ou de la clé du serveur OAuth

```bash
# nouveau client secret : OAUTH_CLIENT_SECRET dans .env
# nouvelle clé publique (après rotation des clés JWT du serveur OAuth) : var/oauth-public.pem
make down && make up    # recrée le conteneur : configuration et clé relues au démarrage
```

- [ ] Connexion et back-channel re-testés (voir recette de
      [mise-en-production.md](mise-en-production.md), étape 7)
