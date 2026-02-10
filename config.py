import tomllib
import ipaddress

def load_toml(config_path):
    with open(config_path,"rb") as f:
        return tomllib.load(f)

def parse_port_mapping(port_spec):
    mappings=[]
    has_equals="=" in port_spec
    if has_equals:
        local_part,remote_part=port_spec.split("=",1)
    else:
        if ":" in port_spec:
            parts=port_spec.rsplit(":",1)
            if "-" in parts[0] or parts[1].isdigit():
                local_part=parts[0]
                remote_part=":"+parts[1]
            else:
                local_part=port_spec
                remote_part=""
        else:
            local_part=port_spec
            remote_part=""
    local_ip="0.0.0.0"
    local_port_str=local_part
    if ":" in local_part and not ("-" in local_part and ":" in local_part):
        parts=local_part.rsplit(":",1)
        if not "-" in parts[1]:
            local_ip,local_port_str=parts
    remote_ip="127.0.0.1"
    remote_port=None
    if remote_part:
        if remote_part.startswith(":"):
            remote_port=int(remote_part[1:])
        elif ":" in remote_part:
            remote_ip,remote_port_str=remote_part.rsplit(":",1)
            remote_port=int(remote_port_str)
        else:
            try:
                remote_port=int(remote_part)
            except ValueError:
                remote_ip=remote_part
    if "-" in local_port_str:
        start,end=local_port_str.split("-")
        start_port=int(start)
        end_port=int(end)
        for port in range(start_port,end_port+1):
            target_port=remote_port if remote_port else port
            mappings.append((local_ip,port,remote_ip,target_port))
    else:
        local_port=int(local_port_str)
        target_port=remote_port if remote_port else local_port
        mappings.append((local_ip,local_port,remote_ip,target_port))
    return mappings

def parse_port_mappings(port_specs):
    all_mappings=[]
    for spec in port_specs:
        all_mappings.extend(parse_port_mapping(spec))
    return all_mappings

class ServerConfig:
    def __init__(self,config_path):
        config=load_toml(config_path)
        self.listen_host=config["server"].get("listen_host","0.0.0.0")
        self.listen_port=config["server"].get("listen_port",8443)
        self.listen_backlog=config["server"].get("listen_backlog",4096)
        self.websocket_path=config["server"].get("websocket_path","/ws")
        self.token=config["auth"]["token"]
        self.port_mappings=parse_port_mappings(config["tunnels"]["ports"])
        self.log_level=config["logging"].get("level","info")
        self.log_file=config["logging"].get("file","/var/log/ghostwire-server.log")
        self.ping_timeout=config["server"].get("ping_timeout",60)
        self.auto_update=config["server"].get("auto_update",True)
        self.update_check_interval=config["server"].get("update_check_interval",300)
        self.update_check_on_startup=config["server"].get("update_check_on_startup",True)
        self.panel_enabled=config.get("panel",{}).get("enabled",False)
        self.panel_host=config.get("panel",{}).get("host","127.0.0.1")
        self.panel_port=config.get("panel",{}).get("port",9090)
        self.panel_path=config.get("panel",{}).get("path","")
        self.panel_threads=config.get("panel",{}).get("threads",4)

class ClientConfig:
    def __init__(self,config_path):
        config=load_toml(config_path)
        self.server_url=config["server"]["url"]
        self.token=config["server"]["token"]
        self.initial_delay=config["reconnect"].get("initial_delay",1)
        self.max_delay=config["reconnect"].get("max_delay",60)
        self.multiplier=config["reconnect"].get("multiplier",2)
        self.cloudflare_enabled=config["cloudflare"].get("enabled",False)
        self.cloudflare_ips=config["cloudflare"].get("ips",[])
        self.cloudflare_host=config["cloudflare"].get("host","")
        self.cloudflare_check_interval=config["cloudflare"].get("check_interval",300)
        self.cloudflare_max_connection_time=config["cloudflare"].get("max_connection_time",1740)
        self.log_level=config["logging"].get("level","info")
        self.log_file=config["logging"].get("file","/var/log/ghostwire-client.log")
        self.auto_update=config["server"].get("auto_update",True)
        self.update_check_interval=config["server"].get("update_check_interval",300)
        self.update_check_on_startup=config["server"].get("update_check_on_startup",True)
