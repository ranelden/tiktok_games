#!/usr/bin/env bash
# Automated setup for TikTok Game on a fresh server (Azure VPS or other).
# Usage: git clone <repo> && cd tiktok-game && ./setup.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -f docker-compose.yml ]; then
  echo "Erreur : lance ce script depuis la racine du repo (docker-compose.yml introuvable)." >&2
  exit 1
fi

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RESET="\033[0m"

info()  { echo -e "${BOLD}==>${RESET} $1"; }
warn()  { echo -e "${YELLOW}${BOLD}!!${RESET} $1"; }
ok()    { echo -e "${GREEN}${BOLD}OK${RESET} $1"; }

# ---------------------------------------------------------------------------
# 1. Docker + Compose v2
# ---------------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  info "Docker n'est pas installé. Installation via le script officiel get.docker.com..."
  curl -fsSL https://get.docker.com | sudo sh
else
  ok "Docker déjà installé ($(docker --version))."
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Erreur : 'docker compose' (v2) n'est pas disponible même après l'installation." >&2
  echo "Vérifie manuellement l'installation de Docker (https://docs.docker.com/engine/install/)." >&2
  exit 1
fi
ok "docker compose v2 disponible ($(docker compose version --short 2>/dev/null || echo '?'))."

if ! groups "$USER" | grep -q '\bdocker\b'; then
  info "Ajout de $USER au groupe docker (pour utiliser docker sans sudo à l'avenir)..."
  sudo usermod -aG docker "$USER"
  warn "Il faudra te reconnecter (ou lancer 'newgrp docker') pour que ça prenne effet en dehors de ce script."
fi

# ---------------------------------------------------------------------------
# 2. Configuration (.env)
# ---------------------------------------------------------------------------
RECONFIGURE=true
if [ -f .env ]; then
  echo
  read -rp "Un .env existe déjà. Le garder tel quel et juste (re)lancer les conteneurs ? [O/n] " keep
  if [[ ! "$keep" =~ ^[nN]$ ]]; then
    RECONFIGURE=false
    ok "Configuration existante conservée."
  fi
fi

if [ "$RECONFIGURE" = true ]; then
  echo
  info "Configuration du déploiement (Entrée = valeur par défaut entre [])."
  echo

  read -rp "Nom de domaine pointant déjà vers ce serveur (laisser vide pour utiliser l'IP directement) : " DOMAIN

  if [ -n "$DOMAIN" ]; then
    HOST_HTTP_PORT=80
    HOST_HTTPS_PORT=443
    warn "Avec un domaine, Caddy fait du HTTPS automatique (Let's Encrypt) : ça exige les ports 80 ET 443"
    warn "ouverts publiquement et le DNS de $DOMAIN déjà pointé vers l'IP de ce serveur. Sinon le certificat échouera."
  else
    read -rp "Port HTTP à utiliser [8080] : " HOST_HTTP_PORT
    HOST_HTTP_PORT="${HOST_HTTP_PORT:-8080}"
    HOST_HTTPS_PORT=8443
    echo "Pas de domaine -> accès en HTTP simple sur le port $HOST_HTTP_PORT (pas de certificat HTTPS)."
  fi

  echo
  read -rp "Activer Adminer (interface d'admin de la base SQLite) ? [o/N] " want_adminer
  ENABLE_ADMINER=false
  ADMINER_BIND="127.0.0.1"
  ADMINER_PORT=8081
  if [[ "$want_adminer" =~ ^[oOyY]$ ]]; then
    ENABLE_ADMINER=true
    read -rp "Port pour Adminer [8081] : " ADMINER_PORT
    ADMINER_PORT="${ADMINER_PORT:-8081}"
    echo
    echo "Adminer sans mot de passe (SQLite n'a pas d'authentification) : quiconque atteint ce port"
    echo "peut lire/modifier toute la base. Deux options :"
    read -rp "  Le rendre accessible uniquement en local (tunnel SSH, recommandé) ou publiquement ? [local/public] " bind_choice
    if [[ "$bind_choice" =~ ^[pP] ]]; then
      ADMINER_BIND="0.0.0.0"
      warn "Adminer sera exposé publiquement sur le port $ADMINER_PORT sans mot de passe. Restreins l'accès"
      warn "via le pare-feu Azure (NSG) si possible, ou repasse en 'local' en relançant ce script."
    else
      ADMINER_BIND="127.0.0.1"
      ok "Adminer restera accessible uniquement via tunnel SSH (voir l'instruction affichée à la fin)."
    fi
  fi

  SECRET_KEY="$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(32))')"

  cat > .env <<EOF
DOMAIN=$DOMAIN
HOST_HTTP_PORT=$HOST_HTTP_PORT
HOST_HTTPS_PORT=$HOST_HTTPS_PORT
APP_PORT=5000
FLASK_DEBUG=false
SECRET_KEY=$SECRET_KEY
ENABLE_ADMINER=$ENABLE_ADMINER
ADMINER_PORT=$ADMINER_PORT
ADMINER_BIND=$ADMINER_BIND
EOF
  ok ".env généré."
fi

# shellcheck disable=SC1091
source .env

# ---------------------------------------------------------------------------
# 3. Persistent directories
# ---------------------------------------------------------------------------
mkdir -p volumes/db volumes/uploads volumes/caddy
ok "Dossiers volumes/ prêts."

# ---------------------------------------------------------------------------
# 4. Local firewall (ufw), if present and active
# ---------------------------------------------------------------------------
if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q "Status: active"; then
  info "ufw actif détecté, ouverture des ports nécessaires..."
  sudo ufw allow "${HOST_HTTP_PORT}/tcp" >/dev/null
  sudo ufw allow "${HOST_HTTPS_PORT}/tcp" >/dev/null
  if [ "${ENABLE_ADMINER:-false}" = "true" ] && [ "${ADMINER_BIND:-127.0.0.1}" = "0.0.0.0" ]; then
    sudo ufw allow "${ADMINER_PORT}/tcp" >/dev/null
  fi
  ok "Ports ouverts dans ufw."
  warn "N'oublie pas d'ouvrir aussi ces ports dans le pare-feu Azure (NSG) depuis le portail : ufw ne gère que ce serveur."
else
  warn "Pas de ufw actif ici : pense à ouvrir les ports $HOST_HTTP_PORT/$HOST_HTTPS_PORT dans le pare-feu Azure (NSG)"
  warn "depuis le portail (et $ADMINER_PORT aussi si Adminer public)."
fi

# ---------------------------------------------------------------------------
# 5. Launch
# ---------------------------------------------------------------------------
COMPOSE_FILES=(-f docker-compose.yml)
if [ "${ENABLE_ADMINER:-false}" = "true" ]; then
  COMPOSE_FILES+=(-f docker-compose.prod.yml)
fi

echo
info "Démarrage des conteneurs (docker compose ${COMPOSE_FILES[*]} up -d --build)..."
sudo docker compose "${COMPOSE_FILES[@]}" up -d --build

echo
ok "C'est lancé !"
echo
if [ -n "${DOMAIN:-}" ]; then
  echo "  Accès : https://$DOMAIN"
else
  PUBLIC_IP="$(curl -fs4 ifconfig.me 2>/dev/null || echo "<IP-de-ce-serveur>")"
  echo "  Accès : http://$PUBLIC_IP:$HOST_HTTP_PORT"
fi
if [ "${ENABLE_ADMINER:-false}" = "true" ]; then
  if [ "${ADMINER_BIND:-127.0.0.1}" = "127.0.0.1" ]; then
    echo "  Adminer (local uniquement) : depuis ta machine, lance"
    echo "    ssh -L ${ADMINER_PORT}:localhost:${ADMINER_PORT} <user>@<IP-de-ce-serveur>"
    echo "  puis ouvre http://localhost:${ADMINER_PORT}"
  else
    echo "  Adminer (public, sans mot de passe) : http://<IP-de-ce-serveur>:${ADMINER_PORT}"
  fi
fi
echo
echo "  Logs        : docker compose logs -f"
echo "  Arrêter     : docker compose down"
echo "  Mettre à jour : git pull && ./setup.sh   (garde ta config existante)"
