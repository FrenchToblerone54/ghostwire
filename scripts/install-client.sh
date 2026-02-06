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

    cat > /etc/ghostwire/client.toml <<EOF
[server]
url="${SERVER_URL}"
token="${TOKEN}"

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

echo "Installing auto-updater..."
if [ ! -f /usr/local/bin/ghostwire-updater.sh ]; then
    cat > /usr/local/bin/ghostwire-updater.sh <<'UPDATER_EOF'
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
UPDATER_EOF
    chmod +x /usr/local/bin/ghostwire-updater.sh
fi

if [ ! -f /etc/systemd/system/ghostwire-updater.service ]; then
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
fi

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
echo "Auto-updater: Enabled (checks hourly)"
echo "Manual update: sudo /usr/local/bin/ghostwire-updater.sh"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status ghostwire-client"
echo "  sudo systemctl stop ghostwire-client"
echo "  sudo systemctl restart ghostwire-client"
echo "  sudo journalctl -u ghostwire-client -f"
echo ""
