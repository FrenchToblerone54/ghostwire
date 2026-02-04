#!/bin/bash
set -e

echo "GhostWire Client Uninstallation"
echo "================================"

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (use sudo)"
    exit 1
fi

echo "Stopping and disabling service..."
systemctl stop ghostwire-client || true
systemctl disable ghostwire-client || true

echo "Removing systemd service..."
rm -f /etc/systemd/system/ghostwire-client.service
systemctl daemon-reload

echo "Removing binary..."
rm -f /usr/local/bin/ghostwire-client

read -p "Remove configuration files? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf /etc/ghostwire
    echo "Configuration removed"
fi

read -p "Remove ghostwire user? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    userdel ghostwire || true
    echo "User removed"
fi

echo "Uninstallation complete!"
