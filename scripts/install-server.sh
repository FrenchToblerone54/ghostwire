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
    read -p "  WebSocket listen host [0.0.0.0]: " WS_HOST
    WS_HOST=${WS_HOST:-0.0.0.0}
    read -p "  WebSocket listen port [8443]: " WS_PORT
    WS_PORT=${WS_PORT:-8443}

    echo ""
    echo "Port Mapping Configuration (users in Iran connect to this):"
    read -p "  Local port to listen on (e.g., 8080): " LOCAL_PORT
    read -p "  Remote destination to forward to (e.g., 80 or 1.1.1.1:443): " REMOTE_DEST

    cat > /etc/ghostwire/server.toml <<EOF
[server]
listen_host="${WS_HOST}"
listen_port=${WS_PORT}
websocket_path="/ws"

[auth]
token="${TOKEN}"

[tunnels]
ports=["${LOCAL_PORT}=${REMOTE_DEST}"]

[logging]
level="info"
file="/var/log/ghostwire-server.log"
EOF

    echo ""
    echo "Configuration created at /etc/ghostwire/server.toml"
    echo ""
    echo "IMPORTANT: Save this authentication token:"
    echo "  ${TOKEN}"
    echo ""
    echo "Server Configuration:"
    echo "  WebSocket listens on: ${WS_HOST}:${WS_PORT}/ws"
    echo "  Users connect to: localhost:${LOCAL_PORT} (forwards to ${REMOTE_DEST})"
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
else
    echo "Skipping nginx setup. Example configuration available at /usr/share/doc/ghostwire/nginx.conf.example"
fi

echo "Installing auto-updater..."
install -m 755 /dev/null /usr/local/bin/ghostwire-updater.sh
cat > /usr/local/bin/ghostwire-updater.sh <<'EOF'
#!/bin/bash
set -e
UPDATE_DIR="/tmp/ghostwire-update"
MARKER="$UPDATE_DIR/update.marker"
if [ ! -f "$MARKER" ]; then
    exit 0
fi
NEW_VERSION=$(cat "$MARKER")
for COMPONENT in server client; do
    BINARY="$UPDATE_DIR/ghostwire-$COMPONENT"
    DEST="/usr/local/bin/ghostwire-$COMPONENT"
    if [ -f "$BINARY" ]; then
        echo "Updating ghostwire-$COMPONENT to $NEW_VERSION..."
        if [ -f "$DEST" ]; then
            mv "$DEST" "$DEST.old"
        fi
        mv "$BINARY" "$DEST"
        chmod +x "$DEST"
        systemctl restart "ghostwire-$COMPONENT" 2>/dev/null || true
        echo "Updated ghostwire-$COMPONENT"
    fi
done
rm -rf "$UPDATE_DIR"
EOF

cat > /etc/systemd/system/ghostwire-updater.service <<'EOF'
[Unit]
Description=GhostWire Auto-Updater
After=network.target

[Service]
Type=oneshot
User=root
ExecStart=/usr/local/bin/ghostwire-updater.sh
EOF

cat > /etc/systemd/system/ghostwire-updater.timer <<'EOF'
[Unit]
Description=GhostWire Auto-Updater Timer
Requires=ghostwire-updater.service

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable ghostwire-updater.timer
systemctl start ghostwire-updater.timer

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
echo "Auto-updater: Enabled (checks hourly)"
echo "Manual update: sudo /usr/local/bin/ghostwire-updater.sh"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status ghostwire-server"
echo "  sudo systemctl stop ghostwire-server"
echo "  sudo systemctl restart ghostwire-server"
echo "  sudo journalctl -u ghostwire-server -f"
echo ""
