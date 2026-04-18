#!/bin/bash
set -e

GITHUB_REPO="frenchtoblerone54/ghostwire"
VERSION="latest"
GW_SERVICE_NAME="ghostwire-server"
RED="\033[0;31m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
BLUE="\033[0;34m"
CYAN="\033[0;36m"
MAGENTA="\033[0;35m"
BOLD="\033[1m"
DIM="\033[2m"
NC="\033[0m"

p_step() { echo -e "\n${BLUE}${BOLD}▶  $1${NC}"; }
p_ok() { echo -e "  ${GREEN}✓${NC}  $1"; }
p_warn() { echo -e "  ${YELLOW}⚠${NC}  $1"; }
p_err() { echo -e "  ${RED}✗${NC}  $1" >&2; }
p_info() { echo -e "  ${CYAN}ℹ${NC}  $1"; }
p_ask() { echo -ne "  ${MAGENTA}?${NC}  $1"; }
p_sep() { echo -e "  ${DIM}------------------------------------------------------------${NC}"; }

p_token_box() {
    local token="$1"
    echo ""
    echo -e "  ${YELLOW}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "  ${YELLOW}${BOLD}║  🔑  AUTHENTICATION TOKEN                                ║${NC}"
    echo -e "  ${YELLOW}${BOLD}║                                                          ║${NC}"
    echo -e "  ${YELLOW}${BOLD}║  ${NC}${BOLD}${token}${NC}${YELLOW}${BOLD}  ║${NC}"
    echo -e "  ${YELLOW}${BOLD}║                                                          ║${NC}"
    echo -e "  ${YELLOW}${BOLD}║  ⚠  Save this token! You'll need it for the client.     ║${NC}"
    echo -e "  ${YELLOW}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

p_panel_box() {
    local url="$1"
    echo ""
    echo -e "  ${CYAN}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "  ${CYAN}${BOLD}║  🖥  Web Management Panel                                ║${NC}"
    echo -e "  ${CYAN}${BOLD}║                                                          ║${NC}"
    echo -e "  ${CYAN}${BOLD}║  URL: ${NC}${url}${CYAN}${BOLD}  ║${NC}"
    echo -e "  ${CYAN}${BOLD}║                                                          ║${NC}"
    echo -e "  ${CYAN}${BOLD}║  Bookmark this URL — it's your admin panel!              ║${NC}"
    echo -e "  ${CYAN}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

clear
echo -e "${CYAN}${BOLD}"
echo "  ============================================================"
echo "    GhostWire Server Installation                           "
echo "    Anti-Censorship Reverse Tunnel                          "
echo "  ============================================================"
echo -e "${NC}"
echo -e "  ${DIM}Source: github.com/${GITHUB_REPO}${NC}"
echo ""

p_step "Checking prerequisites..."
if [ "$EUID" -ne 0 ]; then
    p_err "Please run as root (use sudo)"
    exit 1
fi
p_ok "Root access: OK"

ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
    BINARY_SUFFIX=""
    p_ok "CPU: x86_64 — OK"
elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
    BINARY_SUFFIX="-arm64"
    p_ok "CPU: arm64 — OK"
else
    p_err "Unsupported architecture: $ARCH (supported: x86_64, arm64)"
    exit 1
fi

OS=$(uname -s)
if [ "$OS" != "Linux" ]; then
    p_err "Only Linux is supported"
    exit 1
fi
p_ok "OS: Linux — OK"

GW_BASE_URL="${GW_MIRROR_BASE_URL:-https://github.com/${GITHUB_REPO}/releases/${VERSION}/download}"
p_step "Downloading GhostWire server..."
wget -q --show-progress "${GW_BASE_URL}/ghostwire-server${BINARY_SUFFIX}" -O /tmp/ghostwire-server${BINARY_SUFFIX}
wget -q "${GW_BASE_URL}/ghostwire-server${BINARY_SUFFIX}.sha256" -O /tmp/ghostwire-server${BINARY_SUFFIX}.sha256

p_step "Verifying checksum..."
cd /tmp
sha256sum -c "ghostwire-server${BINARY_SUFFIX}.sha256"
p_ok "Checksum verified"

p_step "Installing binary..."
install -m 755 /tmp/ghostwire-server${BINARY_SUFFIX} /usr/local/bin/ghostwire-server
p_ok "Binary installed to /usr/local/bin/ghostwire-server"

p_step "Creating configuration directory..."
mkdir -p /etc/ghostwire
p_ok "Directory ready: /etc/ghostwire"

if [ ! -f /etc/ghostwire/server.toml ]; then
    p_step "Generating authentication token..."
    TOKEN=$(/usr/local/bin/ghostwire-server --generate-token)
    p_ok "Token generated"
    p_sep
    p_info "WebSocket Configuration (client connects to this):"
    p_info "Default is 127.0.0.1 for security (use with nginx/proxy)"
    p_ask "WebSocket listen host [127.0.0.1]: "; read -r WS_HOST
    WS_HOST=${WS_HOST:-127.0.0.1}
    p_ask "WebSocket listen port [8443]: "; read -r WS_PORT
    WS_PORT=${WS_PORT:-8443}
    p_ok "WebSocket: ${WS_HOST}:${WS_PORT}"
    p_sep
    p_info "Tunnel Mode:"
    p_info "  reverse — server listens on configured ports, client forwards to internet (default)"
    p_info "  direct  — client listens on configured ports, server forwards to targets"
    GW_MODE=""
    while true; do
        p_ask "Mode [1=reverse, 2=direct] (default: 1): "; read -r GW_MODE
        GW_MODE=${GW_MODE:-1}
        case "$GW_MODE" in
            "1") GW_MODE="reverse"; break ;;
            "2") GW_MODE="direct"; break ;;
            *) p_err "Please enter 1 or 2" ;;
        esac
    done
    p_ok "Mode: ${GW_MODE}"
    p_sep
    TUNNELS=()
    TUNNEL_ARRAY="[]"
    if [ "$GW_MODE" = "reverse" ]; then
        p_info "Port Mapping Configuration (users connect to these ports):"
        p_info "  8080=80,8443=443              — Simple port forwarding"
        p_info "  8000-8010=3000                — Port range to single destination"
        p_info "  9000=1.1.1.1:443              — Forward to remote IP"
        p_info "  127.0.0.1:8080=80             — Bind to specific local IP"
        while true; do
            p_ask "Port mappings [8080=80,8443=443]: "; read -r TUNNEL_INPUT
            TUNNEL_INPUT=${TUNNEL_INPUT:-"8080=80,8443=443"}
            [ -n "$TUNNEL_INPUT" ] && break
            p_err "This field is required"
        done
        IFS="," read -ra TUNNELS <<< "$TUNNEL_INPUT"
        TUNNELS=("${TUNNELS[@]// /}")
        TUNNEL_ARRAY=$(printf ",\"%s\"" "${TUNNELS[@]}")
        TUNNEL_ARRAY="[${TUNNEL_ARRAY:1}]"
    else
        p_info "Direct mode: port mappings are defined on the client side."
    fi
    p_sep
    p_ask "Enable auto-update? [Y/n]: "; read -r AUTO_UPDATE
    AUTO_UPDATE=${AUTO_UPDATE:-y}
    if [[ $AUTO_UPDATE =~ ^[Yy]$ ]]; then
        AUTO_UPDATE="true"
    else
        AUTO_UPDATE="false"
    fi
    p_sep
    p_ask "Enable web management panel? [Y/n]: "; read -r ENABLE_PANEL
    ENABLE_PANEL=${ENABLE_PANEL:-y}
    PANEL_ENABLED="false"
    PANEL_CONFIG=""
    if [[ $ENABLE_PANEL =~ ^[Yy]$ ]]; then
        PANEL_ENABLED="true"
        p_ask "  Panel listen host [127.0.0.1]: "; read -r PANEL_HOST
        PANEL_HOST=${PANEL_HOST:-127.0.0.1}
        p_ask "  Panel listen port [9090]: "; read -r PANEL_PORT
        PANEL_PORT=${PANEL_PORT:-9090}
        PANEL_PATH=$(/usr/local/bin/ghostwire-server --generate-token)
        PANEL_CONFIG="
[panel]
enabled=true
host=\"${PANEL_HOST}\"
port=${PANEL_PORT}
path=\"${PANEL_PATH}\"
threads=4"
    fi
    p_sep
    p_info "WebSocket Pool — controls max parallel WebSocket connections:"
    p_info "  2-4:   Light usage (< 50 concurrent connections)"
    p_info "  8:     Default, good for most deployments"
    p_info "  16-32: Heavy usage (multiple simultaneous users)"
    p_ask "WebSocket pool size (ws_pool_children) [8]: "; read -r WS_POOL_CHILDREN
    WS_POOL_CHILDREN=${WS_POOL_CHILDREN:-8}
    p_ok "ws_pool_children: ${WS_POOL_CHILDREN}"
    p_sep
    p_info "Service Name — the systemd service name used for auto-restart after updates."
    p_ask "Service name [ghostwire-server]: "; read -r GW_SERVICE_NAME
    GW_SERVICE_NAME=${GW_SERVICE_NAME:-ghostwire-server}
    p_ok "Service name: ${GW_SERVICE_NAME}"
    p_sep
    p_step "Configuration Summary:"
    p_info "WebSocket: ${WS_HOST}:${WS_PORT}/ws"
    p_info "Mode: ${GW_MODE}"
    [ "$GW_MODE" = "reverse" ] && p_info "Tunnels: ${TUNNEL_ARRAY}"
    p_info "ws_pool_children: ${WS_POOL_CHILDREN}"
    p_info "Auto-update: ${AUTO_UPDATE}"
    p_info "Service name: ${GW_SERVICE_NAME}"
    [[ $PANEL_ENABLED == "true" ]] && p_info "Web panel: http://${PANEL_HOST}:${PANEL_PORT}/${PANEL_PATH}/"
    echo ""
    p_ask "Confirm and save configuration? [Y/n]: "; read -r CONFIRM
    CONFIRM=${CONFIRM:-y}
    if [[ ! $CONFIRM =~ ^[Yy]$ ]]; then
        p_err "Installation cancelled"
        exit 1
    fi

    cat > /etc/ghostwire/server.toml <<EOF
[server]
protocol="websocket"
listen_host="${WS_HOST}"
listen_port=${WS_PORT}
mode="${GW_MODE}"
listen_backlog=4096
websocket_path="/ws"
ping_interval=30
ping_timeout=60
ws_pool_enabled=true
ws_pool_children=${WS_POOL_CHILDREN}
ws_pool_min=2
ws_pool_stripe=false
udp_enabled=true
ws_send_batch_bytes=65536
auto_update=${AUTO_UPDATE}
update_check_interval=300
update_check_on_startup=true
service_name="${GW_SERVICE_NAME}"

[auth]
token="${TOKEN}"
EOF
    if [ "$GW_MODE" = "reverse" ]; then
        cat >> /etc/ghostwire/server.toml <<EOF

[tunnels]
ports=${TUNNEL_ARRAY}
EOF
    fi
    cat >> /etc/ghostwire/server.toml <<EOF

[logging]
level="info"
file="/var/log/ghostwire-server.log"${PANEL_CONFIG}
EOF

    p_ok "Configuration created at /etc/ghostwire/server.toml"
    p_token_box "$TOKEN"
    [[ $PANEL_ENABLED == "true" ]] && p_panel_box "http://${PANEL_HOST}:${PANEL_PORT}/${PANEL_PATH}/"
    p_info "Tip: If using a domain, enable Cloudflare proxy for better reliability and DDoS protection."
    echo ""
else
    p_warn "Configuration already exists at /etc/ghostwire/server.toml"
    WS_PORT=$(grep "listen_port" /etc/ghostwire/server.toml | cut -d"=" -f2 | tr -d " ")
    WS_PORT=${WS_PORT:-8443}
fi

p_step "Installing systemd service..."
cat > /etc/systemd/system/${GW_SERVICE_NAME}.service <<EOF
[Unit]
Description=GhostWire Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/ghostwire-server -c /etc/ghostwire/server.toml
Restart=always
RestartSec=5
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
p_ok "Systemd service installed: ${GW_SERVICE_NAME}"

p_sep
p_ask "Setup nginx now? [y/N] "; read -r -n 1 REPLY; echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    p_step "Installing nginx..."
    apt-get update && apt-get install -y nginx certbot python3-certbot-nginx
    if [ -f /etc/nginx/sites-available/ghostwire ]; then
        p_warn "Removing existing ghostwire nginx configuration..."
        rm -f /etc/nginx/sites-enabled/ghostwire
        rm -f /etc/nginx/sites-available/ghostwire
        if systemctl is-active --quiet nginx; then
            p_info "Restarting nginx..."
            systemctl restart nginx
        fi
    fi
    p_ask "Enter your domain name: "; read -r DOMAIN

    cat > /etc/nginx/sites-available/ghostwire <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
}
EOF

    ln -sf /etc/nginx/sites-available/ghostwire /etc/nginx/sites-enabled/
    nginx -t && systemctl reload nginx

    p_ask "Generate TLS certificate with Let's Encrypt? [y/N] "; read -r -n 1 REPLY; echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        certbot --nginx -d ${DOMAIN}
    fi

    cat > /etc/nginx/sites-available/ghostwire <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://\$server_name\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location /ws {
        proxy_pass http://127.0.0.1:${WS_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
        proxy_buffering off;
        proxy_request_buffering off;
        tcp_nodelay on;
    }

    location / {
        root /var/www/html;
        index index.html;
    }
}
EOF

    systemctl reload nginx
    p_ok "nginx configured for ${DOMAIN}"
    if [[ $PANEL_ENABLED == "true" ]]; then
        echo ""
        p_ask "Setup nginx for panel on another domain? [y/N] "; read -r -n 1 REPLY; echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            p_ask "Enter panel domain name: "; read -r PANEL_DOMAIN
            if [ -f /etc/nginx/sites-available/ghostwire-panel ]; then
                p_warn "Removing existing ghostwire-panel nginx configuration..."
                rm -f /etc/nginx/sites-enabled/ghostwire-panel
                rm -f /etc/nginx/sites-available/ghostwire-panel
                if systemctl is-active --quiet nginx; then
                    p_info "Restarting nginx..."
                    systemctl restart nginx
                fi
            fi
            cat > /etc/nginx/sites-available/ghostwire-panel <<EOF
server {
    listen 80;
    server_name ${PANEL_DOMAIN};
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
}
EOF
            ln -sf /etc/nginx/sites-available/ghostwire-panel /etc/nginx/sites-enabled/
            nginx -t && systemctl reload nginx
            p_ask "Generate TLS certificate for ${PANEL_DOMAIN}? [y/N] "; read -r -n 1 REPLY; echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                certbot --nginx -d ${PANEL_DOMAIN}
            fi
            cat > /etc/nginx/sites-available/ghostwire-panel <<EOF
server {
    listen 80;
    server_name ${PANEL_DOMAIN};
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    location / {
        return 301 https://\$server_name\$request_uri;
    }
}
server {
    listen 443 ssl http2;
    server_name ${PANEL_DOMAIN};
    ssl_certificate /etc/letsencrypt/live/${PANEL_DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${PANEL_DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    location / {
        proxy_pass http://127.0.0.1:${PANEL_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
            systemctl reload nginx
            p_ok "nginx configured for panel: https://${PANEL_DOMAIN}/${PANEL_PATH}/"
        fi
    fi
else
    p_info "Skipping nginx setup. Example configuration available at the GitHub repository README."
fi

p_step "Enabling and starting GhostWire server..."
systemctl enable ${GW_SERVICE_NAME}
if systemctl is-active --quiet ${GW_SERVICE_NAME}; then
    p_warn "Restarting existing service..."
    systemctl restart ${GW_SERVICE_NAME}
else
    systemctl start ${GW_SERVICE_NAME}
fi
p_ok "GhostWire server is running"

p_sep
p_ok "Installation complete!"
p_sep
p_info "Configuration: /etc/ghostwire/server.toml"
echo ""
p_info "Useful commands:"
echo -e "  ${DIM}sudo systemctl status ${GW_SERVICE_NAME}${NC}"
echo -e "  ${DIM}sudo systemctl stop ${GW_SERVICE_NAME}${NC}"
echo -e "  ${DIM}sudo systemctl restart ${GW_SERVICE_NAME}${NC}"
echo -e "  ${DIM}sudo journalctl -u ${GW_SERVICE_NAME} -f${NC}"
echo ""
