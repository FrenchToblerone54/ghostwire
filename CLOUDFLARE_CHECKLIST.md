# CloudFlare Configuration Checklist

Use this checklist to verify your CloudFlare settings are correct for GhostWire.

## 1. CloudFlare Dashboard Settings

### ✅ Network Settings
- [ ] Go to CloudFlare Dashboard → Your Domain → **Network**
- [ ] **WebSockets**: Enabled ← **CRITICAL! OFF by default**
- [ ] HTTP/2: Enabled (default is fine)

### ✅ SSL/TLS Settings
- [ ] Go to **SSL/TLS** → **Overview**
- [ ] Encryption mode: **Full (strict)** (NOT "Flexible")
- [ ] Your origin server must have a valid SSL certificate (Let's Encrypt works)

### ✅ Speed Settings (Turn OFF!)
- [ ] Go to **Speed** → **Optimization**
- [ ] **Rocket Loader**: OFF ← Breaks WebSockets
- [ ] **Auto Minify** → HTML: OFF
- [ ] **Auto Minify** → CSS: OFF
- [ ] **Auto Minify** → JavaScript: OFF
- [ ] **Early Hints**: OFF

### ✅ DNS Settings
- [ ] Go to **DNS** → **Records**
- [ ] A record exists for your subdomain (e.g., `tunnel.example.com`)
- [ ] Proxy status: **Proxied** (orange cloud icon)

## 2. Server Configuration

Check `/etc/ghostwire/server.toml`:

```toml
[server]
ping_interval=30    # Application-level ping
ping_timeout=60     # CloudFlare timeout tolerance
```

## 3. Client Configuration

Check `/etc/ghostwire/client.toml`:

```toml
[server]
url="wss://tunnel.example.com/ws"
ping_interval=30
ping_timeout=60

[cloudflare]
enabled=true              # Enable proactive reconnect
max_connection_time=1740  # 29 minutes (before 30min limit)
```

## 4. Test Connection

After applying all settings:

```bash
# Restart services
sudo systemctl restart ghostwire-server
sudo systemctl restart ghostwire-client

# Check logs
sudo journalctl -u ghostwire-server -f
sudo journalctl -u ghostwire-client -f
```

Look for:
- ✅ "Connected and authenticated to server"
- ✅ Stable connection (no frequent reconnects)
- ❌ Avoid: "Connection closed", "Timeout", frequent reconnects

## Common Issues

### Issue: Constant disconnections every 10-30 seconds
**Cause**: WebSockets not enabled in CloudFlare Dashboard
**Fix**: Network → Enable WebSockets

### Issue: Connection hangs or times out
**Cause**: Rocket Loader or Auto Minify enabled
**Fix**: Speed → Turn OFF all optimization features

### Issue: High latency (> 1 second)
**Cause**: CloudFlare routing or buffering
**Notes**:
- CloudFlare adds 5-500ms latency - this is normal
- GhostWire v0.9.3+ optimized with 64KB buffers for CloudFlare
- If latency > 500ms consistently, try different CloudFlare IPs (advanced)

### Issue: "SSL handshake failed"
**Cause**: SSL/TLS mode is "Flexible" or origin has invalid certificate
**Fix**: Set SSL/TLS to "Full (strict)" and ensure origin has valid cert

## 5. Verify It's Working

Test with curl through your tunnel:

```bash
# Should work without errors
curl -x http://localhost:8080 https://example.com
```

Check connection stability:

```bash
# Should stay connected for > 5 minutes
sudo journalctl -u ghostwire-client -f --since "5 minutes ago"
```

## Need Help?

If you've checked all items and still have issues:

1. Check server logs: `sudo journalctl -u ghostwire-server -n 100`
2. Check client logs: `sudo journalctl -u ghostwire-client -n 100`
3. Verify CloudFlare is actually proxying: `dig tunnel.example.com` (should show CloudFlare IPs)
4. Test direct connection (bypass CloudFlare temporarily to isolate issue)
