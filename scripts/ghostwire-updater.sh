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

        systemctl restart "ghostwire-$COMPONENT"
        echo "Updated and restarted ghostwire-$COMPONENT"
    fi
done

rm -rf "$UPDATE_DIR"
