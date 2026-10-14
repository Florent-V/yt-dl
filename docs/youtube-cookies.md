# Blocage YouTube : méthode des cookies

## Le problème

```
[youtube] …: Sign in to confirm you're not a bot. Use --cookies-from-browser or --cookies …
```

YouTube filtre les IP d'hébergeurs (datacenter) et y exige une connexion. En fournissant à
yt-dlp les cookies d'un compte YouTube connecté, les requêtes du serveur passent pour celles
de ce compte.

Autre solution, sans compte : faire sortir yt-dlp par l'IP de la maison, voir
[youtube-freebox.md](youtube-freebox.md).

## Principe

```
Machine perso                                     Serveur
─────────────                                     ───────
Firefox, profil dédié  ──► script ──► fichier ──► var/youtube/cookies.txt ──► yt-dlp
(compte jetable)           (export)   cookies.txt  (lu à chaque téléchargement)
```

- Le script se lance **sur la machine perso**, jamais sur le serveur (il faut un navigateur).
- Il produit un fichier texte au format Netscape (`# Netscape HTTP Cookie File`) : c'est ce
  fichier, et lui seul, qui va sur le serveur. C'est l'option `--cookies` dont parle le
  message d'erreur.
- `--cookies-from-browser` (l'autre option du message) lit directement un navigateur
  installé : inutilisable sur le serveur, mais c'est ce que le script utilise en local
  pour produire le fichier.

## ⚠️ Sécurité et limites

- **Compte jetable obligatoire.** Le fichier donne accès au compte à qui le possède, et
  YouTube peut bannir (temporairement ou définitivement) un compte utilisé par yt-dlp.
  Jamais ton compte Google principal.
- Le fichier se protège comme `.env` : droits `600`, jamais commité (`var/` et
  `youtube-cookies.txt` sont ignorés par git), jamais envoyé par mail ou messagerie.
- Les cookies expirent ou sont invalidés par YouTube : relancer le script quand l'erreur
  revient (en général après quelques semaines).
- Rester raisonnable : quelques téléchargements, pas des centaines par heure.

## 1. Créer le compte jetable

- [ ] Nouveau compte Google, utilisé uniquement pour yt-dl
- [ ] Une première connexion à YouTube faite avec, à la main (accepter les conditions, etc.)

## 2. Premier export (une seule fois)

Prérequis sur la machine perso : Firefox, `uv`, le dépôt cloné (le script utilise le
yt-dlp du projet), accès SSH au serveur.

```bash
./scripts/youtube-cookies.sh user@serveur
```

1. Firefox s'ouvre sur un **profil dédié** (`~/ytdl-cookies-profile`), séparé de ton
   Firefox habituel : il ne contiendra que le compte jetable.
2. Se connecter au compte jetable, puis **fermer Firefox**.
3. Le script extrait les cookies, vérifie que la session YouTube est bien présente, puis
   les copie sur le serveur dans `/var/www/vauban-ytdl/var/youtube/cookies.txt` (droits 600).

Sans argument, le script écrit seulement `./youtube-cookies.txt`, à copier soi-même.

- [ ] « ✓ Cookies envoyés » affiché
- [ ] Sur le serveur : `ls -l var/youtube/cookies.txt` → `-rw-------`, propriétaire = l'utilisateur qui lance `make`

Variables facultatives : `YTDL_COOKIE_PROFILE` (autre dossier de profil),
`YTDL_REMOTE_FILE` (autre chemin sur le serveur).

## 3. Activer les cookies dans yt-dl

Dans le `.env` du serveur :

```ini
YTDL_COOKIES_FILE=var/youtube/cookies.txt
```

```bash
make check             # signale un cookies.txt manquant
make down && make up   # recrée le conteneur : .env relu
```

- [ ] Analyse et téléchargement de la vidéo qui échouait : OK

Fonctionnement : en Docker, le dossier `var/youtube/` est monté en lecture seule sur
`/run/youtube` ; le fichier doit donc s'appeler `var/youtube/cookies.txt`. Sans Docker
(`./run.sh`), le chemin de `.env` est lu tel quel. À chaque analyse et chaque
téléchargement, yt-dl fait une copie privée et temporaire du fichier (yt-dlp réécrit le
fichier de cookies qu'on lui donne). Variable vide = pas de cookies. Fichier absent ou
illisible = avertissement dans `make logs`, puis fonctionnement sans cookies.

### Tester en local

```bash
./scripts/youtube-cookies.sh                         # écrit ./youtube-cookies.txt
mkdir -p -m 700 var/youtube
mv youtube-cookies.txt var/youtube/cookies.txt
# .env : YTDL_COOKIES_FILE=var/youtube/cookies.txt
make down && make up                                 # ou ./run.sh
```

En local, l'IP de la maison n'est en général pas bloquée : ce test vérifie que les cookies
sont bien pris en compte (pas d'erreur, téléchargement OK), pas qu'ils lèvent le blocage.

## 4. Renouveler les cookies

Quand « Sign in to confirm you're not a bot » revient :

```bash
./scripts/youtube-cookies.sh user@serveur
```

Firefox s'ouvre sur `youtube.com/robots.txt`, déjà connecté : le fermer dès que la page est
chargée. Pas de redémarrage du conteneur : le fichier est relu à chaque analyse et téléchargement
(le script l'envoie sous un nom temporaire puis le renomme, yt-dl ne lit jamais un fichier
incomplet).

Si le script répond « Pas de session YouTube dans ce profil », le compte a été déconnecté :
relancer et se reconnecter dans la fenêtre Firefox.

## Pourquoi un profil dédié plutôt que la fenêtre privée du wiki yt-dlp

Le [wiki yt-dlp](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies)
conseille : fenêtre privée, connexion, onglet sur `youtube.com/robots.txt`, export avec une
extension, puis fermeture de la fenêtre sans jamais la rouvrir. La raison : YouTube fait
tourner les cookies des onglets YouTube ouverts, ce qui invalide une copie exportée plus tôt.

Le profil dédié respecte la même règle (il reste fermé entre deux exports, et chaque export
part de l'état le plus récent) en évitant de se reconnecter à chaque fois. Il évite aussi
d'exporter les cookies de ton navigateur habituel, qui contiendraient **tous** tes sites.

## Dépannage

| Symptôme | Cause |
|---|---|
| Firefox ne s'ouvre pas / profil inaccessible | Firefox snap : le profil ne doit pas être dans un dossier caché (`~/.quelquechose`) |
| `HTTP Error 400: Bad Request` dans yt-dl | Fichier corrompu (fins de ligne Windows) : le régénérer avec le script |
| « Sign in to confirm… » juste après un export | Firefox du profil rouvert depuis, ou compte signalé par YouTube : relancer le script ; si ça persiste, changer de compte jetable |
| « This content isn't available, try again later » | Trop de requêtes : attendre, espacer les téléchargements |
