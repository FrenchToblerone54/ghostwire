# GhostWire - Anti-Censorship Reverse Tunnel

**[📖 فارسی / Persian](README_FA.md)**

GhostWire is a WebSocket-based reverse tunnel system designed to help users in censored countries access the internet freely. It uses secure WebSocket connections over TLS, making it difficult to detect and block.

## Features

- **Multiple protocol support** - WebSocket, HTTP/2, and gRPC transports
- **RSA-encrypted authentication** - Token invisible to TLS-terminating proxies (CloudFlare-proof)
- **End-to-end AES-256-GCM encryption** - All tunnel data encrypted with random 256-bit session keys
- **Reverse tunnel architecture** - Client connects TO server (bypasses outbound blocking)
- **Bidirectional streaming** - Single persistent connection over TLS
- **Flexible TCP port forwarding** - Port ranges, IP binding, custom mappings
- **Built-in heartbeat** - Transport and application-layer keepalive
- **CloudFlare compatible** - Works behind TLS-terminating proxies (with WebSocket/HTTP/2)
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
protocol="websocket"       # "websocket" (default), "http2", or "grpc"
listen_host="0.0.0.0"
listen_port=8443
listen_backlog=4096        # TCP listen queue depth
websocket_path="/ws"       # Only used for websocket protocol
ping_interval=30           # Application-level ping interval (seconds)
ping_timeout=60            # Connection timeout (seconds)
ws_pool_enabled=true       # Enable child channel pooling (default: true)
ws_pool_children=8         # Max child channels (default: 8)
ws_pool_min=2              # Min always-connected channels (default: 2)
ws_pool_stripe=false       # Stripe packets across channels (unstable, default: false)
udp_enabled=true           # Also listen for UDP on tunnel ports (default: true)
ws_send_batch_bytes=65536  # Max bytes per WebSocket frame (default: 65536)
auto_update=true
update_check_interval=300
update_check_on_startup=true

[auth]
token="V1StGXR8_Z5jdHi6B-my"

[tunnels]
ports=["8080=80", "8443=443"]

[panel]
enabled=true
host="127.0.0.1"
port=9090
path="aBcDeFgHiJkLmNoPqRsT"
threads=4                  # HTTP server worker threads

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

The panel is accessible at `http://127.0.0.1:9090/{path}/` where `path` is a randomly generated nanoid. Access is restricted to localhost by default for security. The `threads` parameter (default: 4) controls the number of worker threads for the panel's HTTP server - increase for high traffic.

**Performance Tuning for High Concurrency:**

For web browsing with hundreds of concurrent connections (typical modern websites load 50-200+ resources):

- **`ws_pool_enabled`** (server only, default: true): Enable dynamic multi-connection pool to mitigate TCP-over-TCP meltdown under heavy load
- **`ws_pool_children`** (server only, default: 8): Max parallel WebSocket connections
  - **2-4**: Light usage (< 50 concurrent connections)
  - **8**: Default, good for most deployments
  - **16-32**: Heavy usage (multiple simultaneous users)
- **`ws_pool_min`** (server only, default: 2): Minimum always-connected channels; pool scales between min and max based on load
- **`ws_pool_stripe`** (server only, default: false): Stripe individual packets across channels for higher throughput — disabled by default as it requires sequence reordering and is unstable under packet loss

- **`udp_enabled`** (server only, default: true): Also listen on the configured tunnel ports via UDP; set to `false` to disable UDP tunneling
- **`ws_send_batch_bytes`** (both, default: 65536): Max bytes batched into a single WebSocket frame
  - Lower values reduce latency under high load (speedtest, video) by preventing large frames from blocking smaller packets
  - **65536 (64KB)**: Default, best balance for most use cases
  - **262144 (256KB)**: Higher throughput, some latency increase under load
  - **16384 (16KB)**: Lowest latency, slightly lower throughput

- **`ping_interval`** and **`ping_timeout`**: Critical for CloudFlare stability (configure on both server and client)
  - **For low latency (< 50ms)**: `ping_interval=10`, `ping_timeout=10`
  - **For high latency (> 200ms, CloudFlare)**: `ping_interval=30`, `ping_timeout=60`
  - Aggressive timeouts (< 15s) cause constant reconnections on high-latency WAN links
  - CloudFlare adds 5-500ms latency and has 100s idle timeout, so 30s ping interval is recommended

### Client Configuration (`/etc/ghostwire/client.toml`)

**Location:** Uncensored country (Netherlands) - connects TO server, makes internet requests

```toml
[server]
protocol="websocket"       # "websocket" (default), "http2", or "grpc"
url="wss://tunnel.example.com/ws"  # Use wss:// for websocket, https:// for http2/grpc
token="V1StGXR8_Z5jdHi6B-my"
ping_interval=30           # Application-level ping interval (seconds)
ping_timeout=60            # Connection timeout (seconds)
ws_send_batch_bytes=65536  # Max bytes per WebSocket frame (default: 65536)
auto_update=true
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
```

### Auto-Update Configuration

Both server and client support automatic updates from GitHub releases:

- **`auto_update`** (default: `true`): Enable/disable automatic updates
- **`update_check_interval`** (default: `300`): Seconds between update checks
- **`update_check_on_startup`** (default: `true`): Check for updates immediately on startup

When an update is found, the binary is downloaded, verified with SHA-256 checksum, and the service restarts automatically via systemd.

**HTTP/HTTPS Proxy for Updates:** If your server or client needs to use a proxy to reach GitHub for auto-updates, add these options to the `[server]` section:

```toml
update_http_proxy="http://127.0.0.1:8080"
update_https_proxy="http://127.0.0.1:8080"
```

These proxy settings **only affect auto-update downloads** from GitHub. They do not affect tunnel traffic. Leave empty (or omit) if no proxy is needed.

## Protocol Options

GhostWire supports three transport protocols, each with different trade-offs:

### WebSocket Protocol (`protocol="websocket"`) - Default

**Best for:** CloudFlare, general-purpose use, maximum compatibility

- ✅ Works with CloudFlare (requires WebSockets enabled)
- ✅ Simple browser-based debugging tools available
- ✅ Widely supported by proxies and load balancers
- ❌ HTTP/2-only proxies may block WebSocket upgrade (causes HTTP 426)
- ❌ Requires special `Upgrade` header handling in nginx

**Configuration:**
```toml
[server]
protocol="websocket"
url="wss://tunnel.example.com/ws"
```

### HTTP/2 Protocol (`protocol="http2"`) - Direct Connection

**Best for:** Direct connections without CloudFlare, custom proxy setups

- ✅ Native HTTP/2 streams (no WebSocket upgrade handshake)
- ✅ Simple protocol debugging tools available
- ✅ No protobuf overhead
- ❌ **NOT compatible with CloudFlare** (raw HTTP/2 streams not supported)
- ❌ Requires HTTP/2-capable proxy or direct connection

**Configuration:**
```toml
[server]
protocol="http2"
url="https://tunnel.example.com/tunnel"  # Use /tunnel path
```

**Note:** Can also use `/ws` path for HTTP/2 (kept for consistency with WebSocket mode)

**nginx config:**
```nginx
location /tunnel {
    proxy_pass http://127.0.0.1:8443;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 86400s;
}
```

### gRPC Protocol (`protocol="grpc"`) - CloudFlare Optimized

**Best for:** CloudFlare with gRPC enabled, high-performance scenarios

- ✅ **Compatible with CloudFlare** (requires Network → gRPC enabled)
- ✅ Highest throughput efficiency (protobuf serialization)
- ✅ Built-in streaming multiplexing
- ✅ Lowest protocol overhead
- ❌ Requires CloudFlare gRPC toggle or gRPC-aware proxy
- ❌ More complex debugging

**Configuration:**
```toml
[server]
protocol="grpc"
url="https://tunnel.example.com/tunnel"  # Use /tunnel path, not /ws
```

**nginx config for CloudFlare:**
```nginx
location /tunnel {
    grpc_pass grpc://127.0.0.1:8443;
    grpc_set_header Host $host;
    grpc_read_timeout 86400s;
    grpc_send_timeout 86400s;
}
```

**Protocol Selection Guide:**
- **Use WebSocket** if: Running through CloudFlare (most common), need maximum compatibility
- **Use gRPC** if: Running through CloudFlare with gRPC enabled, want best performance
- **Use HTTP/2** if: Direct connection without CloudFlare, custom proxy setup

## Proxy Configuration

### nginx (manual setup)

**For WebSocket protocol:**
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

**For HTTP/2 protocol:**
```nginx
location /tunnel {
    proxy_pass http://127.0.0.1:8443;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 86400s;
}
```

**For gRPC protocol:**
```nginx
location /tunnel {
    grpc_pass grpc://127.0.0.1:8443;
    grpc_set_header Host $host;
    grpc_set_header X-Real-IP $remote_addr;
    grpc_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    grpc_read_timeout 86400s;
    grpc_send_timeout 86400s;
}
```

**For gRPC with CloudFlare:**
```nginx
server {
    listen 443 ssl http2;
    server_name tunnel.example.com;

    ssl_certificate /etc/letsencrypt/live/tunnel.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/tunnel.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location /tunnel {
        grpc_pass grpc://127.0.0.1:8443;
        grpc_set_header Host $host;
        grpc_set_header X-Real-IP $remote_addr;
        grpc_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        grpc_read_timeout 86400s;
        grpc_send_timeout 86400s;
    }
}
```

Important notes for gRPC with nginx:
- nginx 1.13.10+ required for gRPC support
- Use `grpc_pass` instead of `proxy_pass`
- Use `grpc_*` timeout directives instead of `proxy_*`
- CloudFlare requires **Network → gRPC** toggle enabled
- URL path is `/tunnel` for gRPC (not `/ws`)

**Note:** `proxy_buffering off` and `proxy_request_buffering off` are critical for WebSocket — without these, nginx buffers frames causing significant throughput degradation.

### nginx Proxy Manager (NPM)

**For WebSocket protocol:**
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

**For HTTP/2 or gRPC protocol:**
- Use the same timeout directives
- Do NOT enable "Websockets Support" toggle
- For gRPC, NPM must support gRPC proxying (nginx 1.13.10+)

Without these timeouts, NPM will drop the persistent connection after ~60 seconds.

### CloudFlare

**Protocol Compatibility with CloudFlare:**

| Protocol | CloudFlare Support | Notes |
|-----------|-------------------|-------|
| WebSocket | ✅ Yes (with config) | Requires Network → WebSockets ON |
| gRPC | ✅ Yes (with config) | Requires Network → gRPC ON |
| HTTP/2 | ❌ No | Not compatible - use direct connection |

**CRITICAL: Required CloudFlare Dashboard Settings**

For **WebSocket protocol**:
1. **Network → WebSockets**: MUST be enabled (OFF by default - will cause disconnections!)
2. **SSL/TLS → Overview**: Set to **Full (Strict)** (not "Flexible")
3. **Speed → Rocket Loader**: Turn OFF (breaks WebSocket connections)
4. **Speed → Auto Minify**: Disable all (HTML, CSS, JS)
5. **Speed → Early Hints**: Turn OFF

For **gRPC protocol**:
1. **Network → gRPC**: MUST be enabled (OFF by default)
2. **SSL/TLS → Overview**: Set to **Full (Strict)** (not "Flexible")
3. **Speed → Rocket Loader**: Turn OFF
4. **Speed → Auto Minify**: Disable all (HTML, CSS, JS)
5. **Speed → Early Hints**: Turn OFF

**Client Configuration for CloudFlare:**

CloudFlare's free tier has a 100-second idle timeout and a **30-minute hard connection limit**. Enable proactive reconnect:

```toml
[cloudflare]
enabled=true
max_connection_time=1740  # 29 minutes - reconnect before 30min limit
```

With `enabled=true` and empty `ips`/`host`, the IP selection is skipped but the proactive reconnect still applies.

**Performance Notes:**
- GhostWire v0.9.3+ is optimized for CloudFlare with 64KB buffers (reduced from 16MB)
- Application-level ping (30s) replaces WebSocket ping for CloudFlare reliability
- CloudFlare adds 5-500ms latency - this is normal and handled by the implementation

## CLI Commands

**Update (manual):**
```bash
sudo ghostwire-server update
sudo ghostwire-client update
```
Checks GitHub for a newer release, downloads and verifies it, installs in place, then restarts the service automatically.

**Panel setup:**
```bash
sudo ghostwire-server panel configure
```
Interactive wizard: enables the web panel in `server.toml` (if not already configured) and optionally sets up nginx with a TLS certificate.

**Other:**
```bash
ghostwire-server --version
ghostwire-server --generate-token
```

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
   - Server generates 256-bit random session key
   - Session key sent to client via RSA-2048 encrypted exchange
   - All tunnel data encrypted with this session key
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
