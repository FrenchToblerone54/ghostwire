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

    cat > /etc/ghostwire/server.toml <<EOF
[server]
listen_host="0.0.0.0"
listen_port=8443
websocket_path="/ws"

[auth]
token="${TOKEN}"

[security]
max_connections_per_client=100
connection_timeout=300
allowed_destinations=["0.0.0.0/0"]

[logging]
level="info"
file="/var/log/ghostwire-server.log"
EOF

    echo "Configuration created at /etc/ghostwire/server.toml"
    echo ""
    echo "IMPORTANT: Save this authentication token:"
    echo "  ${TOKEN}"
    echo ""
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
        proxy_pass http://127.0.0.1:8443;
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

    ln -sf /etc/nginx/sites-available/ghostwire /etc/nginx/sites-enabled/

    read -p "Generate TLS certificate with Let's Encrypt? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        certbot certonly --nginx -d ${DOMAIN}
    fi

    systemctl restart nginx
    echo "nginx configured for ${DOMAIN}"
else
    echo "Skipping nginx setup. Example configuration available at /usr/share/doc/ghostwire/nginx.conf.example"
fi

echo "Enabling and starting GhostWire server..."
systemctl enable ghostwire-server
systemctl start ghostwire-server

echo ""
echo "Installation complete!"
echo ""
echo "Server is running on port 8443"
echo "Configuration: /etc/ghostwire/server.toml"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status ghostwire-server"
echo "  sudo systemctl stop ghostwire-server"
echo "  sudo systemctl restart ghostwire-server"
echo "  sudo journalctl -u ghostwire-server -f"
echo ""
