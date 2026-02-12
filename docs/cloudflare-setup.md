# CloudFlare Setup Guide

CloudFlare integration provides additional obfuscation and helps bypass DNS-based censorship by connecting directly to CloudFlare IPs.

## Benefits

- **Hides origin server IP**: CloudFlare proxies traffic to your server
- **DDoS protection**: CloudFlare's network protects against attacks
- **Bypasses DNS blocking**: Direct IP connection bypasses DNS censorship
- **Geographic distribution**: Automatic routing to nearest CloudFlare edge
- **Appears as CDN traffic**: Traffic looks like normal CloudFlare CDN usage

## CloudFlare Configuration

### Step 1: Add Domain to CloudFlare

1. Go to [CloudFlare Dashboard](https://dash.cloudflare.com)
2. Click "Add a Site"
3. Enter your domain name
4. Select a plan (Free is sufficient)
5. Update your domain's nameservers to CloudFlare's

### Step 2: DNS Configuration

1. Add an A record:
   - Name: `tunnel` (or your preferred subdomain)
   - IPv4 address: Your server's IP
   - Proxy status: **Proxied** (orange cloud)
   - TTL: Auto

### Step 3: SSL/TLS Settings

1. Go to SSL/TLS → Overview
2. Set encryption mode to **Full (strict)**
3. Go to SSL/TLS → Edge Certificates
4. Enable these options:
   - Always Use HTTPS: On
   - Minimum TLS Version: TLS 1.2
   - Automatic HTTPS Rewrites: On

### Step 4: Network Settings (CRITICAL!)

1. Go to Network
2. Enable **WebSockets** ← THIS IS OFF BY DEFAULT AND WILL CAUSE DISCONNECTIONS!
3. HTTP/2: Enabled (default)

### Step 5: Speed Settings (CRITICAL!)

**Turn OFF these features that break WebSockets:**

1. Go to Speed → Optimization
2. **Rocket Loader**: OFF
3. **Auto Minify** → HTML: OFF
4. **Auto Minify** → CSS: OFF
5. **Auto Minify** → JavaScript: OFF
6. **Early Hints**: OFF

These optimizations are designed for HTTP, not WebSockets, and will cause disconnections.

### Step 6: Origin Rules (Optional)

If you want additional security:

1. Go to Security → WAF
2. Create firewall rules to restrict access if needed

## Server Configuration

Your nginx configuration remains the same. CloudFlare will handle TLS termination and proxy to your nginx server.

Make sure your origin server has a valid SSL certificate (Let's Encrypt is fine).

## Client Configuration

### Basic CloudFlare Setup

Edit `/etc/ghostwire/client.toml`:

```toml
[server]
url="wss://tunnel.example.com/ws"
token="YOUR_TOKEN"

[cloudflare]
enabled=false
ips=[]
host=""
check_interval=300
```

With `enabled=false`, the client connects normally to the CloudFlare domain.

### Advanced: Direct IP Connection

For maximum censorship resistance, connect directly to CloudFlare IPs:

```toml
[cloudflare]
enabled=true
ips=[
"104.16.0.0",
"104.16.1.0",
"104.16.2.0",
"172.64.0.0",
"172.64.1.0",
]
host="tunnel.example.com"
check_interval=300
```

**How it works:**

1. Client tests WebSocket connection to each CloudFlare IP
2. Measures latency to find the fastest IP
3. Connects to best IP with `Host: tunnel.example.com` header
4. Re-evaluates every 300 seconds and switches if a better IP is found

**Benefits:**

- Bypasses DNS-based blocking
- Optimizes for lowest latency
- Automatically adapts to network conditions

### Finding CloudFlare IPs

Get CloudFlare IPs for your domain:

```bash
nslookup tunnel.example.com
```

Or use CloudFlare's IP ranges:

```bash
curl https://www.cloudflare.com/ips-v4
```

Pick 5-10 IPs from different subnets for redundancy.

## Testing CloudFlare Setup

### Test DNS Resolution

```bash
nslookup tunnel.example.com
```

Should return CloudFlare IPs (not your origin server).

### Test WebSocket Connection

```bash
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
     -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: test" \
     https://tunnel.example.com/ws
```

Should return a 101 Switching Protocols response.

### Test with Client

```bash
sudo systemctl restart ghostwire-client
sudo journalctl -u ghostwire-client -f
```

Look for "Connected and authenticated to server" in logs.

## Troubleshooting

### CloudFlare Error 1000: DNS Points to Prohibited IP

**Cause**: Your A record points to a CloudFlare IP instead of your origin server.

**Solution**: Update the A record to point to your actual server IP.

### CloudFlare Error 522: Connection Timed Out

**Cause**: CloudFlare can't reach your origin server.

**Solution**:
- Verify your origin server is running
- Check firewall rules allow CloudFlare IPs
- Verify nginx is listening on port 443

### WebSocket Connection Fails

**Cause**: WebSockets not enabled or origin SSL issues.

**Solution**:
- Enable WebSockets in CloudFlare Network settings
- Set SSL mode to "Full (strict)"
- Verify origin certificate is valid

### High Latency with Direct IP Connection

**Cause**: Selected CloudFlare IP is far from your location.

**Solution**: Add more CloudFlare IPs to test, preferably from different geographic regions.

## Security Considerations

### Application-Layer Encryption

GhostWire encrypts all message payloads with AES-256-GCM **before** sending through WebSocket. This means:

- CloudFlare sees encrypted binary data
- CloudFlare cannot inspect tunnel contents
- End-to-end encryption between client and server
- Protection against intermediate inspection

### Traffic Analysis

While CloudFlare sees encrypted WebSocket frames, traffic patterns may still be observable:

- Connection duration
- Data volume
- Timing patterns

For additional obfuscation:

- Serve a decoy website on the same domain
- Use the tunnel intermittently rather than continuously
- Mix real browsing with tunneled traffic

## Performance Tips

1. **Use Direct IP Connection**: Reduces DNS lookup overhead
2. **Regular Latency Checks**: Keep `check_interval` at 300s for optimal routing
3. **Multiple IPs**: Configure 5-10 IPs for better redundancy
4. **Geographic Diversity**: Use IPs from different CloudFlare regions

## Advanced: Multiple Domains

For high-availability setups, configure multiple CloudFlare domains:

```toml
[server]
url="wss://tunnel1.example.com/ws"
token="YOUR_TOKEN"

[cloudflare]
enabled=true
ips=[
"104.16.0.0",
"104.17.0.0",
"172.64.0.0",
]
host="tunnel1.example.com"
```

If one domain is blocked, deploy to another domain and update client config.
