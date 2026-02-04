# Troubleshooting Guide

## Common Issues

### Client Cannot Connect to Server

**Symptoms:**
- Client logs show "Connection failed"
- Repeated reconnection attempts

**Solutions:**

1. **Check server is running:**
```bash
sudo systemctl status ghostwire-server
```

2. **Verify server URL is correct:**
```bash
# Test WebSocket endpoint
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
     -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: test" \
     https://tunnel.example.com/ws
```

3. **Check firewall rules:**
```bash
sudo ufw status
sudo iptables -L -n
```

4. **Verify DNS resolution:**
```bash
nslookup tunnel.example.com
```

5. **Test network connectivity:**
```bash
ping tunnel.example.com
telnet tunnel.example.com 443
```

### Authentication Failed

**Symptoms:**
- "Invalid token" in server logs
- Client disconnects immediately after connecting

**Solutions:**

1. **Verify tokens match:**
```bash
# Server token
sudo cat /etc/ghostwire/server.toml | grep token

# Client token
sudo cat /etc/ghostwire/client.toml | grep token
```

2. **Check for whitespace:**
Tokens should have no leading/trailing spaces in configuration files.

3. **Regenerate token if needed:**
```bash
python3.13 -c "from nanoid import generate; print(generate(size=20))"
```

Update both server and client configurations with the new token.

### Port Already in Use

**Symptoms:**
- "Address already in use" error
- Client fails to start

**Solutions:**

1. **Check what's using the port:**
```bash
sudo netstat -tulpn | grep :8080
sudo ss -tulpn | grep :8080
```

2. **Stop conflicting service:**
```bash
sudo systemctl stop <service-name>
```

3. **Use different port:**
Edit `/etc/ghostwire/client.toml` and change the port mapping.

### High Latency

**Symptoms:**
- Slow connection speeds
- High ping times

**Solutions:**

1. **Check server resources:**
```bash
top
htop
```

2. **Test network latency:**
```bash
ping tunnel.example.com
mtr tunnel.example.com
```

3. **Enable CloudFlare IP optimization:**
```toml
[cloudflare]
enabled=true
ips=["104.16.0.0", "104.16.1.0", "172.64.0.0"]
host="tunnel.example.com"
```

4. **Check for bandwidth throttling:**
Test with different ports and protocols.

### Connection Drops Frequently

**Symptoms:**
- Client reconnects every few minutes
- "Connection closed by server" in logs

**Solutions:**

1. **Check server logs:**
```bash
sudo journalctl -u ghostwire-server -f
```

2. **Increase connection timeout:**
Edit `/etc/ghostwire/server.toml`:
```toml
[security]
connection_timeout=600
```

3. **Adjust reconnection settings:**
Edit `/etc/ghostwire/client.toml`:
```toml
[reconnect]
initial_delay=2
max_delay=120
```

4. **Check network stability:**
```bash
ping -c 100 tunnel.example.com
```

### Cannot Access Remote Service

**Symptoms:**
- Connection to local port works but remote service unreachable
- "Connection refused" from server

**Solutions:**

1. **Verify remote service is running:**
From the server machine:
```bash
telnet <remote-ip> <remote-port>
curl http://<remote-ip>:<remote-port>
```

2. **Check server firewall:**
```bash
sudo ufw status
```

3. **Verify port mapping:**
```bash
sudo cat /etc/ghostwire/client.toml
```

4. **Check destination whitelist:**
Edit `/etc/ghostwire/server.toml`:
```toml
[security]
allowed_destinations=["0.0.0.0/0"]
```

## Debugging Steps

### Enable Debug Logging

**Server:**
Edit `/etc/ghostwire/server.toml`:
```toml
[logging]
level="debug"
```

**Client:**
Edit `/etc/ghostwire/client.toml`:
```toml
[logging]
level="debug"
```

Restart services:
```bash
sudo systemctl restart ghostwire-server
sudo systemctl restart ghostwire-client
```

### View Real-Time Logs

**Server:**
```bash
sudo journalctl -u ghostwire-server -f
```

**Client:**
```bash
sudo journalctl -u ghostwire-client -f
```

### Test Individual Components

**Test WebSocket Connection:**
```bash
websocat wss://tunnel.example.com/ws
```

**Test Local Port:**
```bash
telnet localhost 8080
curl -v http://localhost:8080
```

**Test Remote Port from Server:**
```bash
telnet remote-ip remote-port
```

### Check System Resources

**Memory:**
```bash
free -h
```

**CPU:**
```bash
top
```

**Disk:**
```bash
df -h
```

**Network:**
```bash
netstat -i
```

## Performance Issues

### Slow Transfer Speeds

1. **Check MTU settings:**
```bash
ip link show
```

2. **Test with iperf3:**
```bash
iperf3 -s  # On server
iperf3 -c tunnel.example.com  # On client
```

3. **Monitor bandwidth:**
```bash
iftop
nethogs
```

### High CPU Usage

1. **Check process:**
```bash
top -p $(pidof ghostwire-server)
```

2. **Reduce connection limit:**
Edit `/etc/ghostwire/server.toml`:
```toml
[security]
max_connections_per_client=50
```

### Memory Leaks

1. **Monitor memory:**
```bash
watch -n 1 'ps aux | grep ghostwire'
```

2. **Restart service periodically:**
Add to crontab:
```bash
0 3 * * * systemctl restart ghostwire-server
```

## Error Messages

### "Message too short"

**Cause:** Incomplete WebSocket message received.

**Solution:** Usually transient, check network stability.

### "Incomplete message"

**Cause:** WebSocket frame fragmentation.

**Solution:** Check for MTU issues or network fragmentation.

### "Failed to connect to X:Y"

**Cause:** Remote host unreachable from server.

**Solution:**
- Verify remote IP/port is correct
- Check server network access
- Verify firewall rules

### "Permission denied"

**Cause:** Trying to bind to privileged port (<1024) without root.

**Solution:**
- Run as root, or
- Use ports ≥1024, or
- Grant capability: `sudo setcap 'cap_net_bind_service=+ep' /usr/local/bin/ghostwire-client`

## Getting Help

### Collect Information

When reporting issues, include:

1. **System information:**
```bash
uname -a
cat /etc/os-release
```

2. **Service status:**
```bash
sudo systemctl status ghostwire-server
sudo systemctl status ghostwire-client
```

3. **Configuration files:**
```bash
sudo cat /etc/ghostwire/server.toml
sudo cat /etc/ghostwire/client.toml
```

4. **Recent logs:**
```bash
sudo journalctl -u ghostwire-server -n 100
sudo journalctl -u ghostwire-client -n 100
```

5. **Network tests:**
```bash
ping tunnel.example.com
traceroute tunnel.example.com
```

### Report Issues

Open an issue on GitHub with:
- Detailed description of the problem
- Steps to reproduce
- System information
- Relevant logs
- Configuration (remove sensitive tokens)

## Advanced Troubleshooting

### Packet Capture

**Capture WebSocket traffic:**
```bash
sudo tcpdump -i any -w capture.pcap port 443
```

Analyze with Wireshark.

### Test Encryption

**Verify encrypted payloads:**
Check that DATA messages in logs don't show plaintext content.

### Profile Performance

**Use strace:**
```bash
sudo strace -p $(pidof ghostwire-server)
```

**Use perf:**
```bash
sudo perf record -p $(pidof ghostwire-server)
sudo perf report
```
