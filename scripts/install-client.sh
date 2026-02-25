#!/bin/bash
set -e

GITHUB_REPO="frenchtoblerone54/ghostwire"
VERSION="latest"
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

clear
echo -e "${CYAN}${BOLD}"
echo "  ============================================================"
echo "    GhostWire Client Installation                           "
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
if [ "$ARCH" != "x86_64" ]; then
    p_err "Only x86_64 (amd64) architecture is supported"
    exit 1
fi
p_ok "CPU: x86_64 — OK"

OS=$(uname -s)
if [ "$OS" != "Linux" ]; then
    p_err "Only Linux is supported"
    exit 1
fi
p_ok "OS: Linux — OK"

p_step "Downloading GhostWire client..."
wget -q --show-progress "https://github.com/${GITHUB_REPO}/releases/${VERSION}/download/ghostwire-client" -O /tmp/ghostwire-client
wget -q "https://github.com/${GITHUB_REPO}/releases/${VERSION}/download/ghostwire-client.sha256" -O /tmp/ghostwire-client.sha256

p_step "Verifying checksum..."
cd /tmp
sha256sum -c ghostwire-client.sha256
p_ok "Checksum verified"

p_step "Installing binary..."
install -m 755 /tmp/ghostwire-client /usr/local/bin/ghostwire-client
p_ok "Binary installed to /usr/local/bin/ghostwire-client"

p_step "Creating configuration directory..."
mkdir -p /etc/ghostwire
p_ok "Directory ready: /etc/ghostwire"

if [ ! -f /etc/ghostwire/client.toml ]; then
    p_sep
    p_step "Client Configuration"
    while true; do
        p_ask "Server URL (e.g., wss://tunnel.example.com/ws or https://tunnel.example.com/ws): "; read -r SERVER_URL
        if [ -z "$SERVER_URL" ]; then
            p_err "This field is required"
            continue
        fi
        if [[ ! "$SERVER_URL" =~ ^(wss?|https?):// ]]; then
            p_err "URL must start with ws://, wss://, http://, or https://"
            continue
        fi
        break
    done
    while true; do
        p_ask "Authentication token: "; read -r TOKEN
        if [ -z "$TOKEN" ]; then
            p_err "This field is required"
            continue
        fi
        break
    done
    p_ask "Enable auto-update? [Y/n]: "; read -r AUTO_UPDATE
    AUTO_UPDATE=${AUTO_UPDATE:-y}
    if [[ $AUTO_UPDATE =~ ^[Yy]$ ]]; then
        AUTO_UPDATE="true"
    else
        AUTO_UPDATE="false"
    fi
    p_sep
    p_step "Configuration Summary:"
    p_info "Server URL: ${SERVER_URL}"
    p_info "Token: ${TOKEN:0:10}..."
    p_info "Auto-update: ${AUTO_UPDATE}"
    echo ""
    p_ask "Confirm and save configuration? [Y/n]: "; read -r CONFIRM
    CONFIRM=${CONFIRM:-y}
    if [[ ! $CONFIRM =~ ^[Yy]$ ]]; then
        p_err "Installation cancelled"
        exit 1
    fi

    cat > /etc/ghostwire/client.toml <<EOF
[server]
protocol="websocket"
url="${SERVER_URL}"
token="${TOKEN}"
ping_interval=30
ping_timeout=60
ws_send_batch_bytes=65536
auto_update=${AUTO_UPDATE}
update_check_interval=300
update_check_on_startup=true

[reconnect]
initial_delay=1
max_delay=60
multiplier=2

[cloudflare]
enabled=false
ips=[]
host=""
check_interval=300
max_connection_time=1740

[logging]
level="info"
file="/var/log/ghostwire-client.log"
EOF

    p_ok "Configuration created at /etc/ghostwire/client.toml"
fi

p_step "Installing systemd service..."
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
p_ok "Systemd service installed"

p_step "Enabling and starting GhostWire client..."
systemctl enable ghostwire-client
if systemctl is-active --quiet ghostwire-client; then
    p_warn "Restarting existing service..."
    systemctl restart ghostwire-client
else
    systemctl start ghostwire-client
fi
p_ok "GhostWire client is running"

p_sep
p_ok "Installation complete!"
p_sep
p_info "Client is running and listening on configured ports"
p_info "Configuration: /etc/ghostwire/client.toml"
p_info "Tip: If connection is unreliable, enable Cloudflare proxy for your domain to improve stability."
echo ""
p_info "Useful commands:"
echo -e "  ${DIM}sudo systemctl status ghostwire-client${NC}"
echo -e "  ${DIM}sudo systemctl stop ghostwire-client${NC}"
echo -e "  ${DIM}sudo systemctl restart ghostwire-client${NC}"
echo -e "  ${DIM}sudo journalctl -u ghostwire-client -f${NC}"
echo ""
