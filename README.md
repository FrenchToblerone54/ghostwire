# GhostWire - Anti-Censorship Reverse Tunnel

GhostWire is a WebSocket-based reverse tunnel system designed to help users in censored countries access the internet freely. It uses HTTP/2 over TLS to appear as normal HTTPS traffic, making it difficult to detect and block.

## Features

- Single persistent WebSocket connection for bidirectional communication
- TCP port forwarding with flexible mapping syntax
- HTTP/2 with TLS encryption
- Application-layer AES-256-GCM encryption
- nginx reverse proxy support
- CloudFlare compatibility for additional obfuscation
- Compiled binary distribution (Linux amd64)
- TOML configuration files
- systemd service management
- Automated installation scripts

## Quick Start

### Server (Uncensored Country)

```bash
wget https://github.com/frenchtoblerone54/ghostwire/releases/latest/download/install-server.sh
chmod +x install-server.sh
sudo ./install-server.sh
```

### Client (Censored Country)

```bash
wget https://github.com/frenchtoblerone54/ghostwire/releases/latest/download/install-client.sh
chmod +x install-client.sh
sudo ./install-client.sh
```

## Architecture

```
[Application] --> [Local Port] --> [Client] <--WebSocket/HTTP2/TLS--> [Server] --> [Remote Port/IP]
```

## Port Mapping Syntax

The client supports flexible port mapping configurations:

```toml
ports=[
"443-600",                     # Listen on all ports 443-600, forward to same port on remote
"443-600:5201",                # Listen on all ports 443-600, forward all to remote port 5201
"443-600=1.1.1.1:5201",       # Listen on all ports 443-600, forward all to 1.1.1.1:5201
"443",                         # Listen on local port 443, forward to remote port 443
"4000=5000",                   # Listen on local port 4000, forward to remote port 5000
"127.0.0.2:443=5201",         # Bind to 127.0.0.2:443, forward to remote port 5201
"443=1.1.1.1:5201",           # Listen on local port 443, forward to 1.1.1.1:5201
"127.0.0.2:443=1.1.1.1:5201", # Bind to 127.0.0.2:443, forward to 1.1.1.1:5201
]
```

## Configuration

### Server Configuration (`/etc/ghostwire/server.toml`)

```toml
[server]
listen_host="0.0.0.0"
listen_port=8443
websocket_path="/ws"

[auth]
token="V1StGXR8_Z5jdHi6B-my"

[security]
max_connections_per_client=100
connection_timeout=300
allowed_destinations=["0.0.0.0/0"]

[logging]
level="info"
file="/var/log/ghostwire-server.log"
```

### Client Configuration (`/etc/ghostwire/client.toml`)

```toml
[server]
url="wss://tunnel.example.com/ws"
token="V1StGXR8_Z5jdHi6B-my"

[reconnect]
initial_delay=1
max_delay=60
multiplier=2

[tunnels]
ports=["8080=80", "8443=443"]

[cloudflare]
enabled=false
ips=[]
host=""
check_interval=300

[logging]
level="info"
file="/var/log/ghostwire-client.log"
```

## systemd Management

```bash
sudo systemctl start ghostwire-server
sudo systemctl stop ghostwire-server
sudo systemctl restart ghostwire-server
sudo systemctl status ghostwire-server
sudo journalctl -u ghostwire-server -f
```

## Building from Source

```bash
pip install -r requirements.txt
cd build
chmod +x build.sh
./build.sh
```

Binaries will be created in the `dist/` directory.

## Security

GhostWire implements two layers of encryption:

1. **TLS Layer**: WebSocket over HTTPS protects against network eavesdropping
2. **Application Layer**: AES-256-GCM encryption protects against intermediate inspection (including CloudFlare)

All message payloads are encrypted end-to-end using keys derived from the authentication token with PBKDF2-HMAC-SHA256 (100,000 iterations).

## License

MIT License - See LICENSE file for details

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## Support

For issues and questions, please open an issue on GitHub.
