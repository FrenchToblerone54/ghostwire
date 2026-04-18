#!/bin/bash
set -e

GITHUB_REPO="frenchtoblerone54/ghostwire"
VERSION="latest"
GW_SERVICE_NAME="ghostwire-client"
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
p_step "Downloading GhostWire client..."
wget -q --show-progress "${GW_BASE_URL}/ghostwire-client${BINARY_SUFFIX}" -O /tmp/ghostwire-client${BINARY_SUFFIX}
wget -q "${GW_BASE_URL}/ghostwire-client${BINARY_SUFFIX}.sha256" -O /tmp/ghostwire-client${BINARY_SUFFIX}.sha256

p_step "Verifying checksum..."
cd /tmp
sha256sum -c "ghostwire-client${BINARY_SUFFIX}.sha256"
p_ok "Checksum verified"

p_step "Installing binary..."
install -m 755 /tmp/ghostwire-client${BINARY_SUFFIX} /usr/local/bin/ghostwire-client
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
    p_ok "Server URL: ${SERVER_URL}"
    while true; do
        p_ask "Authentication token: "; read -r TOKEN
        [ -z "$TOKEN" ] && { p_err "This field is required"; continue; }
        break
    done
    p_ok "Token: ${TOKEN:0:8}... (accepted)"
    p_sep
    p_info "Tunnel Mode — must match the server's mode:"
    p_info "  reverse — server listens, client connects out (default)"
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
    if [ "$GW_MODE" = "direct" ]; then
        p_info "Port Mapping Configuration (client listens on these ports in direct mode):"
        p_info "  8080=80,8443=443              — Simple port forwarding"
        p_info "  8000-8010=3000                — Port range to single destination"
        p_info "  9000=1.1.1.1:443              — Forward to remote IP"
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
        p_info "Reverse mode: port mappings are defined on the server side."
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
    p_info "Service Name — the systemd service name used for auto-restart after updates."
    p_ask "Service name [ghostwire-client]: "; read -r GW_SERVICE_NAME
    GW_SERVICE_NAME=${GW_SERVICE_NAME:-ghostwire-client}
    p_ok "Service name: ${GW_SERVICE_NAME}"
    p_sep
    p_step "Configuration Summary:"
    p_info "Server URL: ${SERVER_URL}"
    p_info "Mode: ${GW_MODE}"
    [ "$GW_MODE" = "direct" ] && p_info "Tunnels: ${TUNNEL_ARRAY}"
    p_info "Token: ${TOKEN:0:8}..."
    p_info "Auto-update: ${AUTO_UPDATE}"
    p_info "Service name: ${GW_SERVICE_NAME}"
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
mode="${GW_MODE}"
ping_interval=30
ping_timeout=60
ws_send_batch_bytes=65536
auto_update=${AUTO_UPDATE}
update_check_interval=300
update_check_on_startup=true
service_name="${GW_SERVICE_NAME}"

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
EOF
    if [ "$GW_MODE" = "direct" ]; then
        cat >> /etc/ghostwire/client.toml <<EOF

[tunnels]
ports=${TUNNEL_ARRAY}
EOF
    fi
    cat >> /etc/ghostwire/client.toml <<EOF

[logging]
level="info"
file="/var/log/ghostwire-client.log"
EOF

    p_ok "Configuration created at /etc/ghostwire/client.toml"
fi

p_step "Installing systemd service..."
cat > /etc/systemd/system/${GW_SERVICE_NAME}.service <<EOF
[Unit]
Description=GhostWire Client
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/ghostwire-client -c /etc/ghostwire/client.toml
Restart=always
RestartSec=5
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
p_ok "Systemd service installed: ${GW_SERVICE_NAME}"

p_step "Enabling and starting GhostWire client..."
systemctl enable ${GW_SERVICE_NAME}
if systemctl is-active --quiet ${GW_SERVICE_NAME}; then
    p_warn "Restarting existing service..."
    systemctl restart ${GW_SERVICE_NAME}
else
    systemctl start ${GW_SERVICE_NAME}
fi
p_ok "GhostWire client is running"

p_sep
p_ok "Installation complete!"
p_sep
p_info "Client is running and connecting to the server"
p_info "Configuration: /etc/ghostwire/client.toml"
p_info "Tip: If connection is unreliable, enable Cloudflare proxy for your domain to improve stability."
echo ""
p_info "Useful commands:"
echo -e "  ${DIM}sudo systemctl status ${GW_SERVICE_NAME}${NC}"
echo -e "  ${DIM}sudo systemctl stop ${GW_SERVICE_NAME}${NC}"
echo -e "  ${DIM}sudo systemctl restart ${GW_SERVICE_NAME}${NC}"
echo -e "  ${DIM}sudo journalctl -u ${GW_SERVICE_NAME} -f${NC}"
echo ""
