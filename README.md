# GhostWire - Anti-Censorship Reverse Tunnel

GhostWire is a WebSocket-based reverse tunnel system designed to help users in censored countries access the internet freely. It uses HTTP/2 over TLS to appear as normal HTTPS traffic, making it difficult to detect and block.

## Features

- **RSA-encrypted authentication** - Token invisible to TLS-terminating proxies (CloudFlare-proof)
- **End-to-end AES-256-GCM encryption** - All tunnel data encrypted with PBKDF2-derived keys
- **Reverse tunnel architecture** - Client connects TO server (bypasses outbound blocking)
- **Single persistent WebSocket** - Bidirectional communication over HTTP/2 with TLS
- **Flexible TCP port forwarding** - Port ranges, IP binding, custom mappings
- **Built-in heartbeat** - Transport and application-layer keepalive
- **CloudFlare compatible** - Works behind TLS-terminating proxies
- **Web management panel** - Real-time system monitoring, tunnel config, logs, service control
- **nginx reverse proxy** - Production-ready setup with Let's Encrypt
- **Compiled binaries** - Linux amd64 (Ubuntu 22.04+ compatible)
- **systemd services** - Automated start, restart, logging
- **Auto-update** - Configurable automatic binary updates via GitHub releases
- **Easy installation** - One-command setup scripts with interactive configuration

## Quick Start

### Step 1: Install Server (Censored Country - e.g., Iran)

The server runs in the **censored country** with a **public IP** that can receive incoming connections.

```bash
wget https://github.com/frenchtoblerone54/ghostwire/releases/latest/download/install-server.sh -O install-server.sh
chmod +x install-server.sh
sudo ./install-server.sh
```

**Note:** Save the authentication token - you'll need it for the client!

### Step 2: Install Client (Uncensored Country - e.g., Netherlands, USA)

The client runs on a **VPS in an uncensored country** with unrestricted internet access.

```bash
wget https://github.com/frenchtoblerone54/ghostwire/releases/latest/download/install-client.sh -O install-client.sh
chmod +x install-client.sh
sudo ./install-client.sh
```

Enter:
- Server URL pointing to your Iran server (e.g., `wss://iran-server.com/ws`)
- Authentication token from server
- The client will connect TO the Iran server

### Step 3: Use the Tunnel (In Iran)

Users in Iran connect to the server's local ports (e.g., `localhost:8080`) and traffic is tunneled through to the NL client which makes the actual internet requests.

## Documentation

- **[Installation Guide](docs/installation.md)** - Detailed setup instructions for server and client
- **[Configuration Reference](docs/configuration.md)** - Complete configuration options
- **[Troubleshooting](docs/troubleshooting.md)** - Common issues and solutions
- **[Security](docs/security.md)** - Encryption details and security considerations

## Architecture

**Reverse Tunnel for Bypassing Outbound Blocking:**

Designed for scenarios where **censored countries block outbound connections** to foreign servers (e.g., Iran blocks connections to international websites).

**Setup:**
- **Server**: Runs in **censored country** (Iran) with public IP
- **Client**: Runs in **uncensored country** (Netherlands) with unrestricted internet

**Why This Works:**
- Iran blocks **outbound** connections to foreign servers
- But Iran server has **public IP** and can receive **inbound** WebSocket connections
- NL client connects **TO** Iran server (inbound to Iran = allowed ✅)
- Once tunnel is established, traffic flows bidirectionally

**Data Flow:**
```
[User in Iran] → [Server localhost:8080] → [Server Iran]
                                              ↓ WebSocket Tunnel
                                          [Client NL] → [Internet: Port 80/443]
```

**Step-by-Step:**
1. Client (NL) initiates WebSocket connection TO server (Iran)
2. Server (Iran) listens on local ports (e.g., 8080) for users
3. User in Iran connects to `localhost:8080`
4. Traffic tunnels through WebSocket to NL client
5. NL client makes actual connection to blocked websites
6. Response travels back through tunnel to user in Iran

**CloudFlare/DNS:** Points to **Iran server IP** (where WebSocket server listens for client connections)

## Port Mapping Syntax

The server supports flexible port mapping configurations (server listens, client connects):

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

**Location:** Censored country (Iran) - has public IP, listens for client connections

```toml
[server]
listen_host="0.0.0.0"
listen_port=8443
websocket_path="/ws"
auto_update=true

[auth]
token="V1StGXR8_Z5jdHi6B-my"

[tunnels]
ports=["8080=80", "8443=443"]

[panel]
enabled=true
host="127.0.0.1"
port=9090
path="aBcDeFgHiJkLmNoPqRsT"

[logging]
level="info"
file="/var/log/ghostwire-server.log"
```

**Web Management Panel:** The server includes an optional web-based management panel for:
- Real-time system monitoring (CPU, RAM, disk, network usage)
- Tunnel configuration and management
- Log viewing
- Service control (restart/stop)
- Configuration editor

The panel is accessible at `http://127.0.0.1:9090/{path}/` where `path` is a randomly generated nanoid. Access is restricted to localhost by default for security.

### Client Configuration (`/etc/ghostwire/client.toml`)

**Location:** Uncensored country (Netherlands) - connects TO server, makes internet requests

```toml
[server]
url="wss://tunnel.example.com/ws"
token="V1StGXR8_Z5jdHi6B-my"
auto_update=true

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
```

## Proxy Configuration

### nginx (manual setup)

For WebSocket proxying, ensure the nginx config includes these critical directives:

```nginx
location /ws {
    proxy_pass http://127.0.0.1:8443;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 86400;
    proxy_send_timeout 86400;
    proxy_buffering off;
    proxy_request_buffering off;
    tcp_nodelay on;
}
```

`proxy_buffering off` and `proxy_request_buffering off` are critical — without these, nginx buffers WebSocket frames causing significant throughput degradation.

### nginx Proxy Manager (NPM)

1. Create a new Proxy Host pointing to `127.0.0.1:8443`
2. Enable **"Websockets Support"** toggle on the Details tab
3. Under the **Advanced** tab, add these custom directives:

```nginx
proxy_read_timeout 86400;
proxy_send_timeout 86400;
proxy_buffering off;
proxy_request_buffering off;
tcp_nodelay on;
```

Without these timeouts, NPM will drop the persistent WebSocket connection after ~60 seconds.

### CloudFlare

1. Enable **WebSockets** in CloudFlare Dashboard → Network
2. Set SSL/TLS mode to **Full (Strict)** if using Let's Encrypt on your server
3. CloudFlare's free tier has a 100-second idle timeout and a **30-minute hard connection limit** — set `enabled=true` in the client's `[cloudflare]` section to enable proactive reconnect before the limit (`max_connection_time=1740` by default = 29 minutes)
4. With `enabled=true` and empty `ips`/`host`, the IP selection is skipped but the proactive reconnect still applies

**If experiencing authentication timeouts behind CloudFlare:** This is caused by CloudFlare's edge adding latency to the initial WebSocket handshake. GhostWire allows 30 seconds for authentication which should be sufficient.

## systemd Management

**Server:**
```bash
sudo systemctl start ghostwire-server
sudo systemctl stop ghostwire-server
sudo systemctl restart ghostwire-server
sudo systemctl status ghostwire-server
sudo journalctl -u ghostwire-server -f
```

**Client:**
```bash
sudo systemctl start ghostwire-client
sudo systemctl stop ghostwire-client
sudo systemctl restart ghostwire-client
sudo systemctl status ghostwire-client
sudo journalctl -u ghostwire-client -f
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

GhostWire implements multiple layers of security:

1. **RSA-2048 Token Exchange**: Authentication tokens are encrypted with server's public key before transmission
   - Protects tokens from TLS-terminating proxies (CloudFlare, nginx)
   - Only server can decrypt token with its private key

2. **TLS Layer**: WebSocket over HTTPS (WSS) protects transport
   - Prevents network eavesdropping
   - Standard HTTPS encryption

3. **Application Layer**: AES-256-GCM end-to-end encryption
   - All tunnel data encrypted with keys derived from token (PBKDF2-HMAC-SHA256, 100k iterations)
   - Protects against intermediate inspection
   - Even CloudFlare cannot read tunnel contents

4. **Built-in Heartbeat**: WebSocket ping/pong every 20 seconds
   - Detects dead connections quickly
   - Prevents timeout issues

## License

MIT License - See LICENSE file for details

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## Support

For issues and questions, please open an issue on GitHub.
