# Blocage YouTube : sortie par la Freebox (VPN WireGuard)

> ⚠️ **Prise en charge par l'appli à venir.** L'option `YTDL_PROXY` et le fichier
> `compose.vpn.yaml` ne sont pas encore codés. Ce document décrit la mise en place prévue ;
> la partie Freebox (étapes 1 et 2) peut déjà être faite.

## Le problème

```
[youtube] …: Sign in to confirm you're not a bot. Use --cookies-from-browser or --cookies …
```

YouTube filtre les IP d'hébergeurs (datacenter). Une IP de particulier n'est pas concernée.
Ici, yt-dlp sort par la connexion de la maison : aucun compte Google, aucun cookie à
renouveler.

Autre solution, plus simple à mettre en place : [youtube-cookies.md](youtube-cookies.md).

## Principe

```
                          Serveur (Docker)                                Maison
navigateur ─► Caddy ─► yt-dl ──(proxy HTTP)──► gluetun ══ WireGuard ══► Freebox ─► YouTube
                         │                     (réseau Docker interne)
                         └─► serveur OAuth (direct, inchangé)
```

- La **Freebox** est le serveur VPN : pas besoin de machine allumée à la maison.
- Sur le serveur, un conteneur **gluetun** établit le tunnel et expose un proxy HTTP sur le
  réseau Docker interne uniquement.
- Seul **yt-dlp** passe par ce proxy (`YTDL_PROXY`). Caddy, OAuth et le back-channel ne
  changent pas.
- Si le tunnel tombe, les téléchargements échouent : pas de repli silencieux sur l'IP du
  serveur.

## Prérequis

- [ ] Freebox avec serveur VPN **WireGuard** (Delta, Pop, Ultra ; Revolution : vérifier dans
      Freebox OS, sinon OpenVPN, que gluetun gère aussi)
- [ ] **IPv4 publique fixe (« full-stack »)** : les abonnements récents peuvent être en IP
      partagée. Se demande gratuitement dans l'espace abonné Free
      (*Ma Freebox → Demander une adresse IP fixe V4 full-stack*), effectif après redémarrage
      de la box. gluetun n'accepte qu'une **IP** comme point d'entrée, pas un nom de domaine.
- [ ] Fibre : chaque vidéo descend à la maison puis **remonte** vers le serveur, la vitesse
      est limitée par le débit montant.

## ⚠️ Sécurité

Un client VPN de la Freebox est **dans le réseau local de la maison** (box, NAS,
imprimante, autres appareils). Si le serveur était compromis, le tunnel serait une porte
d'entrée chez toi. Mesures prévues, toutes obligatoires :

- Le proxy n'est publié sur **aucun port** de l'hôte : seul le conteneur yt-dl le joint, par
  le réseau Docker interne.
- gluetun **bloque les plages privées** dans le tunnel (règles iptables, étape 4) : seul
  Internet est joignable par la maison.
- Mot de passe fort sur l'interface d'administration de la Freebox
  (`mafreebox.freebox.fr`), accès distant à Freebox OS désactivé s'il ne sert pas.
- Un utilisateur VPN dédié à yt-dl, révocable seul.
- yt-dl n'accepte que les sites connus de yt-dlp (extracteur « generic » désactivé) : on ne
  peut pas lui faire télécharger une adresse du réseau local.

## 1. Freebox : activer le serveur WireGuard

Dans Freebox OS (`http://mafreebox.freebox.fr`, depuis la maison) :

1. *Paramètres de la Freebox* (mode avancé) → *Serveur VPN* → onglet **WireGuard** →
   activer. Noter le port.
2. *Serveur VPN* → *Utilisateurs* → **Ajouter** : nom `yt-dl`, type WireGuard.
3. Télécharger le fichier de configuration de cet utilisateur (`.conf`).

- [ ] Serveur WireGuard actif
- [ ] Utilisateur `yt-dl` créé, fichier `.conf` récupéré
- [ ] Dans le fichier, `Endpoint` = **IP publique** de la box (pas un nom en
      `freeboxos.fr` ; sinon remplacer par l'IP)

Le fichier contient la **clé privée** du client : il se protège comme `.env`.

## 2. Copier la configuration sur le serveur

```bash
scp yt-dl.conf user@serveur:/var/www/vauban-ytdl/var/freebox-wg0.conf
ssh user@serveur chmod 600 /var/www/vauban-ytdl/var/freebox-wg0.conf
rm yt-dl.conf          # sur la machine perso, une fois copié
```

- [ ] `var/freebox-wg0.conf` présent sur le serveur, droits `600`

## 3. Activer le tunnel dans yt-dl *(à venir)*

Dans le `.env` du serveur :

```ini
COMPOSE_FILE=compose.yaml:compose.vpn.yaml
YTDL_PROXY=http://gluetun:8888
```

```bash
make down && make up
make ps                # gluetun et yt-dl « healthy »
```

Contenu prévu de `compose.vpn.yaml` (pour information) :

```yaml
services:
  gluetun:
    image: qmcgaw/gluetun:v3.41.3          # version épinglée, mise à jour par Dependabot
    cap_add: [NET_ADMIN]                   # requis pour WireGuard, sur ce conteneur seulement
    devices: [/dev/net/tun:/dev/net/tun]
    environment:
      VPN_SERVICE_PROVIDER: custom
      VPN_TYPE: wireguard
      HTTPPROXY: "on"                      # écoute sur :8888, réseau Docker interne uniquement
    volumes:
      - ./var/freebox-wg0.conf:/gluetun/wireguard/wg0.conf:ro
      - ./vpn-post-rules.txt:/iptables/post-rules.txt:ro
    restart: unless-stopped
    # pas de « ports: » : le proxy n'est pas joignable depuis l'extérieur
  yt-dl:
    depends_on:
      gluetun: { condition: service_healthy }
```

## 4. Bloquer le réseau local de la maison *(à venir)*

`vpn-post-rules.txt` (versionné), appliqué par gluetun au démarrage :

```sh
iptables -I OUTPUT -o wg0 -d 192.168.0.0/16 -j REJECT
iptables -I OUTPUT -o wg0 -d 172.16.0.0/12 -j REJECT
iptables -I OUTPUT -o wg0 -d 10.0.0.0/8 -j REJECT
iptables -I OUTPUT -o wg0 -d 169.254.0.0/16 -j REJECT
```

Le filtre porte sur l'interface du tunnel (`wg0`) seulement : le réseau Docker (en
`172.x`) reste joignable par l'autre interface, sinon yt-dl ne pourrait plus parler au proxy.

## 5. Recette

```bash
# IP vue par Internet depuis le proxy : doit être celle de la maison
docker compose exec yt-dl python -c \
  "import httpx; print(httpx.get('https://api.ipify.org', proxy='http://gluetun:8888').text)"

# Réseau local de la maison : doit échouer (REJECT)
docker compose exec yt-dl python -c \
  "import httpx; httpx.get('http://192.168.1.254', proxy='http://gluetun:8888', timeout=5)"
```

- [ ] L'IP affichée est celle de la Freebox
- [ ] La requête vers `192.168.1.254` échoue
- [ ] Depuis l'extérieur, `curl http://<ip-serveur>:8888` ne répond pas
- [ ] Analyse et téléchargement de la vidéo qui échouait : OK
- [ ] `docker compose stop gluetun` → les téléchargements échouent (pas de repli sur l'IP du
      serveur), puis `docker compose start gluetun`

## Révoquer l'accès

Freebox OS → *Serveur VPN* → *Utilisateurs* → supprimer `yt-dl`. Le tunnel est coupé
immédiatement ; sur le serveur, retirer les deux lignes de `.env`, supprimer
`var/freebox-wg0.conf`, puis `make down && make up`.

## Dépannage

| Symptôme | Piste |
|---|---|
| gluetun redémarre en boucle | `docker compose logs gluetun` ; `Endpoint` doit être une IP ; port WireGuard de la box correct |
| Tunnel établi mais pas de trafic | IP partagée (pas full-stack) : le port de la box n'est pas joignable |
| Téléchargements très lents | Débit montant de la maison, ou box sollicitée par ailleurs |
| L'IP de la maison change | Normalement fixe en full-stack ; sinon mettre à jour `Endpoint` dans `var/freebox-wg0.conf` |
| « Sign in to confirm… » malgré le tunnel | Vérifier l'IP vue (étape 5) ; si c'est bien la maison, mettre yt-dlp à jour |
