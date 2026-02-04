# GhostWire Setup Guide

## Server Setup (Uncensored Country)

### Prerequisites

- Linux amd64 server
- Public IP address or domain name
- Root access

### Installation Steps

1. **Download and run the installation script:**

```bash
wget https://github.com/frenchtoblerone54/ghostwire/releases/latest/download/install-server.sh
chmod +x install-server.sh
sudo ./install-server.sh
```

2. **Save the authentication token** displayed during installation. You'll need this for client configuration.

3. **Optional: Configure nginx** (prompted during installation)
   - Enter your domain name
   - Optionally generate Let's Encrypt certificate

4. **Verify the service is running:**

```bash
sudo systemctl status ghostwire-server
```

5. **Check logs:**

```bash
sudo journalctl -u ghostwire-server -f
```

### Manual Installation

If you prefer to install manually:

1. Download the binary:

```bash
wget https://github.com/frenchtoblerone54/ghostwire/releases/latest/download/ghostwire-server
sudo install -m 755 ghostwire-server /usr/local/bin/
```

2. Create configuration:

```bash
sudo mkdir -p /etc/ghostwire
sudo nano /etc/ghostwire/server.toml
```

3. Generate authentication token:

```bash
python3.13 -c "from nanoid import generate; print(generate(size=20))"
```

4. Install systemd service:

```bash
sudo cp systemd/ghostwire-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ghostwire-server
sudo systemctl start ghostwire-server
```

## Client Setup (Censored Country)

### Prerequisites

- Linux amd64 machine
- Root access
- Server URL and authentication token

### Installation Steps

1. **Download and run the installation script:**

```bash
wget https://github.com/frenchtoblerone54/ghostwire/releases/latest/download/install-client.sh
chmod +x install-client.sh
sudo ./install-client.sh
```

2. **Enter configuration details** when prompted:
   - Server URL (e.g., `wss://tunnel.example.com/ws`)
   - Authentication token (from server setup)
   - Local port to forward
   - Remote port to connect to

3. **Verify the service is running:**

```bash
sudo systemctl status ghostwire-client
```

4. **Check logs:**

```bash
sudo journalctl -u ghostwire-client -f
```

### Manual Installation

1. Download the binary:

```bash
wget https://github.com/frenchtoblerone54/ghostwire/releases/latest/download/ghostwire-client
sudo install -m 755 ghostwire-client /usr/local/bin/
```

2. Create configuration:

```bash
sudo mkdir -p /etc/ghostwire
sudo nano /etc/ghostwire/client.toml
```

3. Install systemd service:

```bash
sudo cp systemd/ghostwire-client.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ghostwire-client
sudo systemctl start ghostwire-client
```

## nginx Configuration

If you're setting up nginx manually, use this configuration:

```nginx
server {
    listen 443 ssl http2;
    server_name tunnel.example.com;

    ssl_certificate /etc/letsencrypt/live/tunnel.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/tunnel.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location /ws {
        proxy_pass http://127.0.0.1:8443;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }

    location / {
        root /var/www/html;
        index index.html;
    }
}
```

## Testing the Connection

1. **On the client machine:**

```bash
curl -x http://localhost:8080 http://example.com
```

2. **Check server logs:**

```bash
sudo journalctl -u ghostwire-server -f
```

3. **Check client logs:**

```bash
sudo journalctl -u ghostwire-client -f
```

## Next Steps

- See [Port Mapping Guide](port-mapping.md) for advanced port configurations
- See [CloudFlare Setup](cloudflare-setup.md) for CloudFlare integration
- See [Troubleshooting Guide](troubleshooting.md) for common issues
