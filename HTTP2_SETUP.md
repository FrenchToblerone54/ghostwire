# HTTP/2 Protocol Setup Guide

## What is HTTP/2 Mode?

HTTP/2 mode uses **pure HTTP/2 bidirectional streaming** instead of WebSockets. This solves CloudFlare compatibility issues:

- ✅ No WebSocket upgrade handshake (which CloudFlare blocks with HTTP/2)
- ✅ Native HTTP/2 streams (CloudFlare optimized for this)
- ✅ Works perfectly with nginx + CloudFlare
- ✅ Same security (RSA + AES-GCM encryption)
- ✅ No protobuf overhead (unlike gRPC)

## How It Works

**WebSocket (old):**
```
Client → HTTP/1.1 Upgrade: websocket → [CloudFlare ERROR 426] → Server
```

**HTTP/2 (new):**
```
Client → HTTP/2 POST /tunnel (stream) → [CloudFlare ✅] → Server
```

## Configuration

### Server (`/etc/ghostwire/server.toml`)

```toml
[server]
protocol="http2"  # Changed from "websocket"
listen_host="0.0.0.0"
listen_port=8443
ping_interval=30
ping_timeout=60
```

### Client (`/etc/ghostwire/client.toml`)

```toml
[server]
protocol="http2"  # Changed from "websocket"
url="wss://tc2.digikalaservice32.store/ws"  # Same path as websocket
token="YOUR_TOKEN"
ping_interval=30
ping_timeout=60
```

**Note:** Uses same `/ws` path for both protocols (for consistency).

## nginx Configuration

Update your nginx config for HTTP/2:

```nginx
server {
    listen 443 ssl http2;  # Enable HTTP/2
    server_name tc2.digikalaservice32.store;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # HTTP/2 specific settings
    http2_max_concurrent_streams 128;
    http2_max_field_size 16k;
    http2_max_header_size 32k;

    # Timeouts for long-lived connections
    proxy_connect_timeout 7d;
    proxy_send_timeout 7d;
    proxy_read_timeout 7d;

    location /ws {
        proxy_pass http://127.0.0.1:8443;
        proxy_http_version 1.1;  # Backend uses HTTP/1.1

        # Preserve client info
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # No buffering for streaming
        proxy_buffering off;
        proxy_request_buffering off;

        # Long timeouts
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
```

**Key differences from WebSocket config:**
- No `Upgrade` headers needed
- Location is `/tunnel` not `/ws`
- `http2` enabled on listen directive
- Backend still uses HTTP/1.1 (proxy_http_version 1.1)

## CloudFlare Settings

Same as before:
- ✅ Network → WebSockets: Can be ON or OFF (doesn't matter for HTTP/2!)
- ✅ Speed → Rocket Loader: OFF
- ✅ Speed → Auto Minify: OFF
- ✅ SSL/TLS: Full (strict)

## Deployment

### 1. Update Server Config

```bash
sudo nano /etc/ghostwire/server.toml
# Change protocol="websocket" to protocol="http2"
```

### 2. Update Client Config

```bash
sudo nano /etc/ghostwire/client.toml
# Change protocol="websocket" to protocol="http2"
# Change url="wss://..." to url="https://..." (remove /ws)
```

### 3. Update nginx Config

```bash
sudo nano /etc/nginx/sites-available/ghostwire
# Update to HTTP/2 config above
sudo nginx -t
sudo systemctl reload nginx
```

### 4. Restart Services

```bash
# Server
sudo systemctl restart ghostwire-server
sudo journalctl -u ghostwire-server -f

# Client
sudo systemctl restart ghostwire-client
sudo journalctl -u ghostwire-client -f
```

## Testing

```bash
# Test HTTP/2 connection
curl -v --http2 https://tc2.digikalaservice32.store/tunnel

# Should see:
# * using HTTP/2
# < HTTP/2 200  (connection stays open)
```

## Advantages Over WebSocket

1. **CloudFlare Compatible**: No HTTP/2 + WebSocket upgrade conflict
2. **Simpler**: No upgrade handshake to fail
3. **Better Multiplexing**: HTTP/2 native streams
4. **Same Performance**: No overhead vs WebSocket
5. **Same Security**: RSA + AES-GCM encryption unchanged

## Troubleshooting

### "Connection failed"
- Check protocol="http2" in BOTH server and client configs
- Check URL has NO `/ws` path
- Check nginx has HTTP/2 enabled (`listen 443 ssl http2`)

### "Invalid HTTP header"
- Make sure nginx has `proxy_http_version 1.1` (backend is HTTP/1.1)
- Check nginx has `/tunnel` location block

### Still disconnecting
- Check CloudFlare Speed settings (Rocket Loader OFF, etc.)
- Check nginx timeouts are long (86400s)
- Check logs: `sudo journalctl -u ghostwire-server -f`

## Switching Back to WebSocket

If you need to switch back:

```toml
[server]
protocol="websocket"  # Change back
url="wss://tc2.digikalaservice32.store/ws"  # Add /ws back
```

And use WebSocket nginx config with Upgrade headers.
