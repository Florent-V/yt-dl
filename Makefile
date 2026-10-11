# Commandes de base de yt-dl, en local et en Docker.  Aide : make help
#
# Variables surchargeables : make up HTTP_PORT=9000, make public-key OAUTH_DIR=../OAuth-serveur
#                            make prod-public-key PROD_OAUTH_DIR=/var/www/vauban

HTTP_PORT ?= 8765
OAUTH_DIR ?= ../OAuth-serveur
PROD_OAUTH_DIR ?= /var/www/vauban
APP_UID   ?= $(shell id -u)
APP_GID   ?= $(shell id -g)
export HTTP_PORT APP_UID APP_GID

COMPOSE  = docker compose
# Pas de pseudo-terminal hors d'un terminal (CI, cron, redirection)
TTY     := $(shell [ -t 0 ] || echo -T)
SECRETS  = secrets/oauth_client_secret secrets/oauth-public.pem

.DEFAULT_GOAL := help
.PHONY: help install run test test-network audit lock-upgrade \
        init secret public-key prod-public-key check build up down restart logs ps sh health clean

## —— Aide ————————————————————————————————————————————————————————————————
help: ## Affiche cette aide
	@grep -E '(^[a-zA-Z_-]+:.*?## .*$$)|(^## )' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; /^## / {printf "\n\033[1m%s\033[0m\n", substr($$0, 4); next} {printf "  \033[32m%-14s\033[0m %s\n", $$1, $$2}'

## —— Local (sans Docker) ——————————————————————————————————————————————————
install: ## Crée .venv et installe les dépendances (dev incluses)
	uv sync --frozen --extra dev

run: ## Lance le serveur local sur 127.0.0.1:HTTP_PORT (charge .env)
	./run.sh $(HTTP_PORT)

test: ## Tests rapides, hors-ligne
	uv run pytest -q

test-network: ## Tests avec téléchargements réels
	uv run pytest -q -m network

audit: ## Cherche des vulnérabilités connues dans les dépendances figées
	uv export --frozen --no-dev --no-emit-project --format requirements-txt -o /tmp/yt-dl-requirements.txt
	uvx pip-audit --strict -r /tmp/yt-dl-requirements.txt
	@rm -f /tmp/yt-dl-requirements.txt

lock-upgrade: ## Met à jour yt-dlp (casse souvent côté YouTube) dans uv.lock
	uv lock --upgrade-package yt-dlp --upgrade-package yt-dlp-ejs
	uv sync --frozen --extra dev

## —— Docker : préparation —————————————————————————————————————————————————
init: ## Crée .env.docker et le dossier secrets/ (à compléter ensuite)
	@test -f .env.docker || { cp .env.docker.dist .env.docker; echo "→ .env.docker créé : à compléter"; }
	@mkdir -p secrets && chmod 700 secrets

secret: init ## Enregistre le secret du client OAuth (saisie masquée)
	@read -rsp "Secret du client OAuth : " s && echo \
	  && umask 077 && printf '%s' "$$s" > secrets/oauth_client_secret \
	  && echo "→ secrets/oauth_client_secret écrit (600)"

public-key: init ## Récupère la clé publique du serveur OAuth de dev (OAUTH_DIR)
	@$(MAKE) -s -C $(OAUTH_DIR) public-key > secrets/oauth-public.pem.tmp \
	  && mv secrets/oauth-public.pem.tmp secrets/oauth-public.pem \
	  && echo "→ secrets/oauth-public.pem écrit" \
	  || { rm -f secrets/oauth-public.pem.tmp; echo "✗ échec (prod : make prod-public-key)"; exit 1; }

prod-public-key: init ## Récupère la clé publique du serveur OAuth de prod (PROD_OAUTH_DIR)
	@$(MAKE) -s -C $(PROD_OAUTH_DIR) prod-public-key > secrets/oauth-public.pem.tmp \
	  && mv secrets/oauth-public.pem.tmp secrets/oauth-public.pem \
	  && echo "→ secrets/oauth-public.pem écrit" \
	  || { rm -f secrets/oauth-public.pem.tmp; echo "✗ échec : serveur OAuth démarré dans $(PROD_OAUTH_DIR) ?"; exit 1; }

check: ## Vérifie la configuration (fichiers, secrets, compose)
	@test -f .env.docker || { echo "✗ .env.docker absent : make init"; exit 1; }
	@for f in $(SECRETS); do test -s $$f || { echo "✗ $$f absent : make secret / make public-key"; exit 1; }; done
	@$(COMPOSE) config --quiet && echo "✓ configuration valide"

## —— Docker : exploitation ————————————————————————————————————————————————
build: check ## Construit l'image
	$(COMPOSE) build --pull

up: check ## Démarre (construit si besoin) en arrière-plan
	$(COMPOSE) up -d --build
	@echo "→ http://127.0.0.1:$(HTTP_PORT)  (make logs pour suivre)"

down: ## Arrête et supprime le conteneur (les données restent dans le volume)
	$(COMPOSE) down

restart: ## Redémarre le conteneur
	$(COMPOSE) restart

logs: ## Suit les logs
	$(COMPOSE) logs -f --tail=100

ps: ## État du conteneur (avec healthcheck)
	$(COMPOSE) ps

sh: ## Shell dans le conteneur
	$(COMPOSE) exec $(TTY) yt-dl sh

health: ## Interroge /api/health
	@curl -fsS http://127.0.0.1:$(HTTP_PORT)/api/health && echo

clean: ## Arrête et SUPPRIME le volume (sessions, fichiers en cours)
	$(COMPOSE) down --volumes
