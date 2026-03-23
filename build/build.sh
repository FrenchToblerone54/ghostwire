#!/bin/bash
set -e
echo "Building GhostWire binaries..."
cd "$(dirname "$0")/.."
ARCH=$(uname -m)
if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
    SUFFIX="-arm64"
else
    SUFFIX=""
fi
python3.13 -m PyInstaller --onefile --name "ghostwire-server${SUFFIX}" --add-data "frontend:frontend" server.py
python3.13 -m PyInstaller --onefile --name "ghostwire-client${SUFFIX}" client.py
echo "Generating checksums..."
cd dist
sha256sum "ghostwire-server${SUFFIX}" > "ghostwire-server${SUFFIX}.sha256"
sha256sum "ghostwire-client${SUFFIX}" > "ghostwire-client${SUFFIX}.sha256"
cd ..
echo "Build complete!"
echo "Binaries available in dist/"
ls -lh dist/
