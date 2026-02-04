# Port Mapping Guide

GhostWire supports flexible port mapping configurations inspired by backhaul's syntax.

## Syntax Patterns

### Basic Syntax

```
[local_ip:]local_port[-local_port_end][=remote_ip:]remote_port
```

### Components

- `local_ip` - IP address to bind to (default: `0.0.0.0`)
- `local_port` - Local port to listen on
- `local_port_end` - End of port range (for ranges)
- `remote_ip` - Remote IP to connect to (default: `127.0.0.1`)
- `remote_port` - Remote port to connect to

## Examples

### Simple Port Forwarding

```toml
ports=["8080=80"]
```

- Listens on `0.0.0.0:8080`
- Forwards to `127.0.0.1:80` on server

### Same Port on Both Sides

```toml
ports=["443"]
```

- Listens on `0.0.0.0:443`
- Forwards to `127.0.0.1:443` on server

### Specific Local IP Binding

```toml
ports=["127.0.0.1:8080=80"]
```

- Listens on `127.0.0.1:8080` (localhost only)
- Forwards to `127.0.0.1:80` on server
- Prevents other devices on LAN from using the tunnel

### Forward to External IP

```toml
ports=["8080=1.1.1.1:80"]
```

- Listens on `0.0.0.0:8080`
- Forwards to `1.1.1.1:80` from server

### Complete Binding

```toml
ports=["192.168.1.10:8080=8.8.8.8:443"]
```

- Listens on `192.168.1.10:8080`
- Forwards to `8.8.8.8:443` from server

## Port Ranges

### Range with Same Ports

```toml
ports=["8000-8010"]
```

- Creates 11 listeners (8000, 8001, ..., 8010)
- Each forwards to the same port on remote (8000→8000, 8001→8001, etc.)

### Range to Single Port

```toml
ports=["8000-8010:3000"]
```

- Creates 11 listeners (8000, 8001, ..., 8010)
- All forward to remote port 3000

### Range with Specific Remote

```toml
ports=["8000-8010=1.1.1.1:443"]
```

- Creates 11 listeners (8000, 8001, ..., 8010)
- All forward to `1.1.1.1:443`

### Range with Local IP Binding

```toml
ports=["127.0.0.1:8000-8010=443"]
```

- Binds all ports in range to `127.0.0.1`
- Forwards to remote port 443

## Real-World Use Cases

### Web Browsing Setup

```toml
ports=[
"8080=proxy.example.com:80",
"8443=proxy.example.com:443",
]
```

Configure browser to use `localhost:8080` (HTTP) and `localhost:8443` (HTTPS) as proxy.

### SSH Access

```toml
ports=["2222=remote-server.example.com:22"]
```

Connect with: `ssh -p 2222 user@localhost`

### Multiple Services

```toml
ports=[
"8080=webserver.example.com:80",
"8443=webserver.example.com:443",
"3306=database.example.com:3306",
"6379=redis.example.com:6379",
]
```

### Multi-User Setup

```toml
ports=["8000-8100=proxy.example.com:443"]
```

Each user can use their own port (8000, 8001, 8002, etc.)

### Localhost-Only (Security)

```toml
ports=["127.0.0.1:8080=proxy.example.com:443"]
```

Prevents other devices on your network from using the tunnel.

## Configuration Tips

1. **Start Simple**: Begin with basic port forwarding and add complexity as needed

2. **Test Incrementally**: Test each port mapping individually before adding more

3. **Use Localhost Binding**: For single-user setups, bind to `127.0.0.1` to prevent unauthorized access

4. **Document Your Mappings**: Keep notes on what each port forwards to

5. **Avoid Port Conflicts**: Make sure local ports aren't already in use

## Troubleshooting

### Port Already in Use

```
Error: Address already in use
```

**Solution**: Choose a different local port or stop the service using that port

### Permission Denied (Ports < 1024)

```
Error: Permission denied
```

**Solution**: Run as root or use ports ≥ 1024

### Cannot Connect to Remote

```
Error: Connection refused
```

**Solution**: Verify the remote IP and port are correct and accessible from the server
