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
        server=config["server"]
        self.protocol=config["server"].get("protocol","websocket")
        self.listen_host=config["server"].get("listen_host","0.0.0.0")
        self.listen_port=config["server"].get("listen_port",8443)
        self.listen_backlog=config["server"].get("listen_backlog",4096)
        self.websocket_path=config["server"].get("websocket_path","/ws")
        self.token=config["auth"]["token"]
        self.mode=config["server"].get("mode","reverse")
        self.direct_mode=config["server"].get("direct_mode","to_server")
        self.port_mappings=parse_port_mappings(config.get("tunnels",{}).get("ports",[]))
        self.log_level=config["logging"].get("level","info")
        self.log_file=config["logging"].get("file","/var/log/ghostwire-server.log")
        self.ping_timeout=config["server"].get("ping_timeout",10)
        self.ws_pool_enabled=config["server"].get("ws_pool_enabled",True)
        self.ws_pool_children=config["server"].get("ws_pool_children",8)
        self.ws_pool_min=config["server"].get("ws_pool_min",2)
        self.ws_pool_scale_interval=config["server"].get("ws_pool_scale_interval",5)
        self.ws_pool_scale_up=config["server"].get("ws_pool_scale_up",100)
        self.ws_pool_scale_down=config["server"].get("ws_pool_scale_down",16)
        self.ws_pool_stripe=config["server"].get("ws_pool_stripe",False)
        self.ws_pool_target_per_child=config["server"].get("ws_pool_target_per_child",8)
        self.ws_send_batch_bytes=config["server"].get("ws_send_batch_bytes",65536)
        self.http_request_min_upload_ms=config["server"].get("http_request_min_upload_ms",10)
        self.http_request_min_download_ms=config["server"].get("http_request_min_download_ms",25)
        self.http_request_max_upload_bytes=config["server"].get("http_request_max_upload_bytes",1048576)
        self.http_request_max_download_bytes=config["server"].get("http_request_max_download_bytes",1048576)
        self.http_request_poll_min_connections=config["server"].get("http_request_poll_min_connections",1)
        self.http_request_poll_connections=config["server"].get("http_request_poll_connections",4)
        self.http_request_body_param=config["server"].get("http_request_body_param","data")
        self.udp_enabled=config["server"].get("udp_enabled",True)
        self.auto_update=config["server"].get("auto_update",True)
        self.update_check_interval=config["server"].get("update_check_interval",300)
        self.update_check_on_startup=config["server"].get("update_check_on_startup",True)
        self.update_http_proxy=server.get("update_http_proxy","")
        self.update_https_proxy=server.get("update_https_proxy","")
        self.http_proxy=server.get("http_proxy","")
        self.https_proxy=server.get("https_proxy","")
        self.direct_http_proxy=server.get("direct_http_proxy","")
        self.direct_https_proxy=server.get("direct_https_proxy","")
        self.panel_enabled=config.get("panel",{}).get("enabled",False)
        self.panel_host=config.get("panel",{}).get("host","127.0.0.1")
        self.panel_port=config.get("panel",{}).get("port",9090)
        self.panel_path=config.get("panel",{}).get("path","")
        self.panel_threads=config.get("panel",{}).get("threads",4)
        self.ssl_cert=config["server"].get("ssl_cert","")
        self.ssl_key=config["server"].get("ssl_key","")
        self.service_name=config["server"].get("service_name","ghostwire-server")
        self.pinned_private_key=config["server"].get("pinned_private_key","")

class ClientConfig:
    def __init__(self,config_path):
        config=load_toml(config_path)
        server=config["server"]
        self.protocol=config["server"].get("protocol","websocket")
        self.server_url=config["server"]["url"]
        self.token=config["server"]["token"]
        self.ping_interval=config["server"].get("ping_interval",10)
        self.ping_timeout=config["server"].get("ping_timeout",10)
        self.ws_send_batch_bytes=config["server"].get("ws_send_batch_bytes",65536)
        self.http_request_min_upload_ms=config["server"].get("http_request_min_upload_ms",10)
        self.http_request_min_download_ms=config["server"].get("http_request_min_download_ms",25)
        self.http_request_max_upload_bytes=config["server"].get("http_request_max_upload_bytes",1048576)
        self.http_request_max_download_bytes=config["server"].get("http_request_max_download_bytes",1048576)
        self.http_request_poll_min_connections=config["server"].get("http_request_poll_min_connections",1)
        self.http_request_poll_connections=config["server"].get("http_request_poll_connections",4)
        self.ws_pool_enabled=config["server"].get("ws_pool_enabled",True)
        self.ws_pool_children=config["server"].get("ws_pool_children",8)
        self.ws_pool_min=config["server"].get("ws_pool_min",2)
        self.ws_pool_scale_interval=config["server"].get("ws_pool_scale_interval",5)
        self.ws_pool_scale_up=config["server"].get("ws_pool_scale_up",100)
        self.ws_pool_scale_down=config["server"].get("ws_pool_scale_down",16)
        self.ws_pool_stripe=config["server"].get("ws_pool_stripe",False)
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
        self.update_http_proxy=server.get("update_http_proxy","")
        self.update_https_proxy=server.get("update_https_proxy","")
        self.http_proxy=server.get("http_proxy","")
        self.https_proxy=server.get("https_proxy","")
        self.user_agent=server.get("user_agent","")
        self.allow_redirects=server.get("allow_redirects",True)
        self.direct_http_proxy=server.get("direct_http_proxy","")
        self.direct_https_proxy=server.get("direct_https_proxy","")
        self.mode=config["server"].get("mode","reverse")
        self.direct_mode=config["server"].get("direct_mode","to_server")
        self.port_mappings=parse_port_mappings(config.get("tunnels",{}).get("ports",[]))
        self.allow_insecure=config["server"].get("allow_insecure",False)
        _raw_resolve_ip=config["server"].get("resolve_ip","")
        if isinstance(_raw_resolve_ip,list):
            self.resolve_ips=[str(ip).strip() for ip in _raw_resolve_ip if str(ip).strip()]
        else:
            self.resolve_ips=[ip.strip() for ip in str(_raw_resolve_ip).split(",") if ip.strip()]
        self.resolve_ip=self.resolve_ips[0] if self.resolve_ips else ""
        self.resolve_ip_mode=config["server"].get("resolve_ip_mode","least_ping")
        self.resolve_ip_latency_interval=config["server"].get("resolve_ip_latency_interval",60)
        self.sni=config["server"].get("sni","")
        self.host_header=config["server"].get("host_header","")
        self.domain_fronting_host=config["server"].get("domain_fronting_host","")
        self.domain_fronting_target=config["server"].get("domain_fronting_target","")
        self.domain_fronting_sni=config["server"].get("domain_fronting_sni","")
        self.http_request_body_param=config["server"].get("http_request_body_param","data")
        self.http_request_body_method=config["server"].get("http_request_body_method","GET").upper()
        self.gas_script_id=config["server"].get("gas_script_id","")
        self.service_name=config["server"].get("service_name","ghostwire-client")
        self.pinned_server_public_key=config["server"].get("pinned_server_public_key","")
