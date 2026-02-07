#!/bin/bash
set -e

GITHUB_REPO="frenchtoblerone54/ghostwire"
VERSION="latest"

echo "GhostWire Server Installation"
echo "=============================="

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (use sudo)"
    exit 1
fi

ARCH=$(uname -m)
if [ "$ARCH" != "x86_64" ]; then
    echo "Error: Only x86_64 (amd64) architecture is supported"
    exit 1
fi

OS=$(uname -s)
if [ "$OS" != "Linux" ]; then
    echo "Error: Only Linux is supported"
    exit 1
fi

echo "Downloading GhostWire server..."
wget -q --show-progress "https://github.com/${GITHUB_REPO}/releases/${VERSION}/download/ghostwire-server" -O /tmp/ghostwire-server
wget -q "https://github.com/${GITHUB_REPO}/releases/${VERSION}/download/ghostwire-server.sha256" -O /tmp/ghostwire-server.sha256

echo "Verifying checksum..."
cd /tmp
sha256sum -c ghostwire-server.sha256

echo "Installing binary..."
install -m 755 /tmp/ghostwire-server /usr/local/bin/ghostwire-server

echo "Creating configuration directory..."
mkdir -p /etc/ghostwire

if [ ! -f /etc/ghostwire/server.toml ]; then
    echo "Generating authentication token..."
    TOKEN=$(/usr/local/bin/ghostwire-server --generate-token)

    echo ""
    echo "WebSocket Configuration (client connects to this):"
    echo "Note: Default is 127.0.0.1 for security (use with nginx/proxy)"
    read -p "  WebSocket listen host [127.0.0.1]: " WS_HOST
    WS_HOST=${WS_HOST:-127.0.0.1}
    read -p "  WebSocket listen port [8443]: " WS_PORT
    WS_PORT=${WS_PORT:-8443}

    echo ""
    echo "Port Mapping Configuration (users in Iran connect to this):"
    echo "Examples: 8080=80, 8443=443, 8000-8010=3000, 9000=1.1.1.1:443"
    TUNNELS=()
    while true; do
        while true; do
            read -p "  Local port to listen on (e.g., 8080 or 8000-8010): " LOCAL_PORT
            if [ -z "$LOCAL_PORT" ]; then
                echo "❌ This field is required"
                continue
            fi
            break
        done
        read -p "  Remote destination (e.g., 80 or 1.1.1.1:443) [same as local]: " REMOTE_DEST
        if [ -z "$REMOTE_DEST" ]; then
            TUNNELS+=("${LOCAL_PORT}")
        else
            TUNNELS+=("${LOCAL_PORT}=${REMOTE_DEST}")
        fi
        read -p "  Add another tunnel? [y/N]: " ADD_MORE
        if [[ ! $ADD_MORE =~ ^[Yy]$ ]]; then
            break
        fi
    done

    echo ""
    read -p "Enable auto-update? [Y/n]: " AUTO_UPDATE
    AUTO_UPDATE=${AUTO_UPDATE:-y}
    if [[ $AUTO_UPDATE =~ ^[Yy]$ ]]; then
        AUTO_UPDATE="true"
    else
        AUTO_UPDATE="false"
    fi

    echo ""
    read -p "Enable web management panel? [Y/n]: " ENABLE_PANEL
    ENABLE_PANEL=${ENABLE_PANEL:-y}
    PANEL_ENABLED="false"
    PANEL_CONFIG=""
    if [[ $ENABLE_PANEL =~ ^[Yy]$ ]]; then
        PANEL_ENABLED="true"
        read -p "  Panel listen host [127.0.0.1]: " PANEL_HOST
        PANEL_HOST=${PANEL_HOST:-127.0.0.1}
        read -p "  Panel listen port [9090]: " PANEL_PORT
        PANEL_PORT=${PANEL_PORT:-9090}
        PANEL_PATH=$(/usr/local/bin/ghostwire-server --generate-token)
        PANEL_CONFIG="
[panel]
enabled=true
host=\"${PANEL_HOST}\"
port=${PANEL_PORT}
path=\"${PANEL_PATH}\""
    fi

    TUNNEL_ARRAY=$(printf ',"%s"' "${TUNNELS[@]}")
    TUNNEL_ARRAY="[${TUNNEL_ARRAY:1}]"

    echo ""
    echo "Configuration Summary:"
    echo "  WebSocket: ${WS_HOST}:${WS_PORT}/ws"
    echo "  Tunnels: ${TUNNEL_ARRAY}"
    echo "  Auto-update: ${AUTO_UPDATE}"
    if [[ $PANEL_ENABLED == "true" ]]; then
        echo "  Web panel: http://${PANEL_HOST}:${PANEL_PORT}/${PANEL_PATH}/"
    fi
    echo ""
    read -p "Confirm and save configuration? [Y/n]: " CONFIRM
    CONFIRM=${CONFIRM:-y}
    if [[ ! $CONFIRM =~ ^[Yy]$ ]]; then
        echo "Installation cancelled"
        exit 1
    fi

    cat > /etc/ghostwire/server.toml <<EOF
[server]
listen_host="${WS_HOST}"
listen_port=${WS_PORT}
websocket_path="/ws"
auto_update=${AUTO_UPDATE}

[auth]
token="${TOKEN}"

[tunnels]
ports=${TUNNEL_ARRAY}

[logging]
level="info"
file="/var/log/ghostwire-server.log"${PANEL_CONFIG}
EOF

    echo ""
    echo "Configuration created at /etc/ghostwire/server.toml"
    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║                 AUTHENTICATION TOKEN                       ║"
    echo "║                                                            ║"
    echo "║  ${TOKEN}  ║"
    echo "║                                                            ║"
    echo "║  ⚠️  Save this token! You'll need it for the client.      ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
    if [[ $PANEL_ENABLED == "true" ]]; then
        echo "╔════════════════════════════════════════════════════════════╗"
        echo "║                   WEB MANAGEMENT PANEL                     ║"
        echo "║                                                            ║"
        echo "║  URL: http://${PANEL_HOST}:${PANEL_PORT}/${PANEL_PATH}/      "
        echo "║                                                            ║"
        echo "║  📝 Bookmark this URL - it's your admin panel!            ║"
        echo "╚════════════════════════════════════════════════════════════╝"
        echo ""
    fi
    echo "💡 Tip: If using a domain, enable CloudFlare proxy for better"
    echo "   reliability and DDoS protection."
    echo ""
else
    echo "Configuration already exists at /etc/ghostwire/server.toml"
    WS_PORT=$(grep "listen_port" /etc/ghostwire/server.toml | cut -d'=' -f2 | tr -d ' ')
    WS_PORT=${WS_PORT:-8443}
fi

echo "Creating system user..."
if ! id -u ghostwire >/dev/null 2>&1; then
    useradd -r -s /bin/false ghostwire
fi

echo "Configuring sudoers for auto-update and panel..."
cat > /etc/sudoers.d/ghostwire <<EOF
ghostwire ALL=(ALL) NOPASSWD: /bin/mv /usr/local/bin/ghostwire-*
ghostwire ALL=(ALL) NOPASSWD: /bin/systemctl restart ghostwire-server
EOF
chmod 440 /etc/sudoers.d/ghostwire

echo "Installing systemd service..."
cat > /etc/systemd/system/ghostwire-server.service <<EOF
[Unit]
Description=GhostWire Server
After=network.target

[Service]
Type=simple
User=ghostwire
ExecStart=/usr/local/bin/ghostwire-server -c /etc/ghostwire/server.toml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

read -p "Setup nginx now? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Installing nginx..."
    apt-get update && apt-get install -y nginx certbot python3-certbot-nginx

    read -p "Enter your domain name: " DOMAIN

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

    read -p "Generate TLS certificate with Let's Encrypt? [y/N] " -n 1 -r
    echo
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
    }

    location / {
        root /var/www/html;
        index index.html;
    }
}
EOF

    systemctl reload nginx
    echo "nginx configured for ${DOMAIN}"
    if [[ $PANEL_ENABLED == "true" ]]; then
        echo ""
        read -p "Setup nginx for panel on another domain? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            read -p "Enter panel domain name: " PANEL_DOMAIN
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
            read -p "Generate TLS certificate for ${PANEL_DOMAIN}? [y/N] " -n 1 -r
            echo
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
            echo "nginx configured for panel: https://${PANEL_DOMAIN}/${PANEL_PATH}/"
        fi
    fi
else
    echo "Skipping nginx setup. Example configuration available at /usr/share/doc/ghostwire/nginx.conf.example"
fi

echo "Enabling and starting GhostWire server..."
systemctl enable ghostwire-server
if systemctl is-active --quiet ghostwire-server; then
    echo "Restarting existing service..."
    systemctl restart ghostwire-server
else
    systemctl start ghostwire-server
fi

echo ""
echo "Installation complete!"
echo ""
echo "Configuration: /etc/ghostwire/server.toml"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status ghostwire-server"
echo "  sudo systemctl stop ghostwire-server"
echo "  sudo systemctl restart ghostwire-server"
echo "  sudo journalctl -u ghostwire-server -f"
echo ""
