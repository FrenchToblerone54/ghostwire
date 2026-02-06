#!/bin/bash
set -e

UPDATE_DIR="/tmp/ghostwire-update"
MARKER="$UPDATE_DIR/update.marker"

if [ ! -f "$MARKER" ]; then
    echo "No update pending"
    exit 0
fi

NEW_VERSION=$(cat "$MARKER")
COMPONENT=${1:-server}

echo "Applying update to $NEW_VERSION..."

if [ "$COMPONENT" = "server" ]; then
    BINARY="$UPDATE_DIR/ghostwire-server"
    DEST="/usr/local/bin/ghostwire-server"
elif [ "$COMPONENT" = "client" ]; then
    BINARY="$UPDATE_DIR/ghostwire-client"
    DEST="/usr/local/bin/ghostwire-client"
else
    echo "Invalid component: $COMPONENT"
    exit 1
fi

if [ ! -f "$BINARY" ]; then
    echo "Update binary not found: $BINARY"
    exit 1
fi

if [ -f "$DEST" ]; then
    mv "$DEST" "$DEST.old"
fi

mv "$BINARY" "$DEST"
chmod +x "$DEST"

rm -rf "$UPDATE_DIR"

echo "Updated to $NEW_VERSION, restarting ghostwire-$COMPONENT..."
systemctl restart "ghostwire-$COMPONENT"
