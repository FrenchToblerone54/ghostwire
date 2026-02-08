#!/bin/bash
set -e

GITHUB_REPO="frenchtoblerone54/ghostwire"
VERSION="latest"

echo "GhostWire Client Installation"
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

echo "Downloading GhostWire client..."
wget -q --show-progress "https://github.com/${GITHUB_REPO}/releases/${VERSION}/download/ghostwire-client" -O /tmp/ghostwire-client
wget -q "https://github.com/${GITHUB_REPO}/releases/${VERSION}/download/ghostwire-client.sha256" -O /tmp/ghostwire-client.sha256

echo "Verifying checksum..."
cd /tmp
sha256sum -c ghostwire-client.sha256

echo "Installing binary..."
install -m 755 /tmp/ghostwire-client /usr/local/bin/ghostwire-client

echo "Creating configuration directory..."
mkdir -p /etc/ghostwire

if [ ! -f /etc/ghostwire/client.toml ]; then
    echo ""
    echo "Client Configuration"
    echo "===================="
    while true; do
        read -p "Server URL (e.g., wss://tunnel.example.com/ws): " SERVER_URL
        if [ -z "$SERVER_URL" ]; then
            echo "❌ This field is required"
            continue
        fi
        if [[ ! "$SERVER_URL" =~ ^wss?:// ]]; then
            echo "❌ URL must start with ws:// or wss://"
            continue
        fi
        break
    done
    while true; do
        read -p "Authentication token: " TOKEN
        if [ -z "$TOKEN" ]; then
            echo "❌ This field is required"
            continue
        fi
        break
    done
    read -p "Enable auto-update? [Y/n]: " AUTO_UPDATE
    AUTO_UPDATE=${AUTO_UPDATE:-y}
    if [[ $AUTO_UPDATE =~ ^[Yy]$ ]]; then
        AUTO_UPDATE="true"
    else
        AUTO_UPDATE="false"
    fi
    echo ""
    echo "Configuration Summary:"
    echo "  Server URL: ${SERVER_URL}"
    echo "  Token: ${TOKEN:0:10}..."
    echo "  Auto-update: ${AUTO_UPDATE}"
    echo ""
    read -p "Confirm and save configuration? [Y/n]: " CONFIRM
    CONFIRM=${CONFIRM:-y}
    if [[ ! $CONFIRM =~ ^[Yy]$ ]]; then
        echo "Installation cancelled"
        exit 1
    fi

    cat > /etc/ghostwire/client.toml <<EOF
[server]
url="${SERVER_URL}"
token="${TOKEN}"
auto_update=${AUTO_UPDATE}

[reconnect]
initial_delay=1
max_delay=60
multiplier=2

[cloudflare]
enabled=false
ips=[]
host=""
check_interval=300

[logging]
level="info"
file="/var/log/ghostwire-client.log"
EOF

    echo "Configuration created at /etc/ghostwire/client.toml"
fi

echo "Installing systemd service..."
cat > /etc/systemd/system/ghostwire-client.service <<EOF
[Unit]
Description=GhostWire Client
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/ghostwire-client -c /etc/ghostwire/client.toml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

echo "Enabling and starting GhostWire client..."
systemctl enable ghostwire-client
if systemctl is-active --quiet ghostwire-client; then
    echo "Restarting existing service..."
    systemctl restart ghostwire-client
else
    systemctl start ghostwire-client
fi

echo ""
echo "Installation complete!"
echo ""
echo "Client is running and listening on configured ports"
echo "Configuration: /etc/ghostwire/client.toml"
echo ""
echo "💡 Tip: If connection is unreliable, enable CloudFlare proxy"
echo "   for your domain to improve stability and reduce latency."
echo ""
echo "Useful commands:"
echo "  sudo systemctl status ghostwire-client"
echo "  sudo systemctl stop ghostwire-client"
echo "  sudo systemctl restart ghostwire-client"
echo "  sudo journalctl -u ghostwire-client -f"
echo ""
