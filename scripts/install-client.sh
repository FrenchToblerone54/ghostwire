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
    read -p "Enter server URL (e.g., wss://tunnel.example.com/ws): " SERVER_URL
    read -p "Enter authentication token: " TOKEN
    read -p "Enter local port to forward (e.g., 8080): " LOCAL_PORT
    read -p "Enter remote port to connect to (e.g., 80): " REMOTE_PORT

    cat > /etc/ghostwire/client.toml <<EOF
[server]
url="${SERVER_URL}"
token="${TOKEN}"

[reconnect]
initial_delay=1
max_delay=60
multiplier=2

[tunnels]
ports=[
"${LOCAL_PORT}=${REMOTE_PORT}",
]

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

echo "Creating system user..."
if ! id -u ghostwire >/dev/null 2>&1; then
    useradd -r -s /bin/false ghostwire
fi

echo "Installing systemd service..."
cat > /etc/systemd/system/ghostwire-client.service <<EOF
[Unit]
Description=GhostWire Client
After=network.target

[Service]
Type=simple
User=ghostwire
ExecStart=/usr/local/bin/ghostwire-client -c /etc/ghostwire/client.toml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

echo "Enabling and starting GhostWire client..."
systemctl enable ghostwire-client
systemctl start ghostwire-client

echo ""
echo "Installation complete!"
echo ""
echo "Client is running and listening on configured ports"
echo "Configuration: /etc/ghostwire/client.toml"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status ghostwire-client"
echo "  sudo systemctl stop ghostwire-client"
echo "  sudo systemctl restart ghostwire-client"
echo "  sudo journalctl -u ghostwire-client -f"
echo ""
