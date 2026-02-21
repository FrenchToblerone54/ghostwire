#!/usr/bin/env python3.13
import asyncio
import subprocess
import time
import socket
import sys
import argparse
from collections import Counter

def get_free_port():
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.bind(("127.0.0.1",0))
    port=s.getsockname()[1]
    s.close()
    return port

def percentile(values,p):
    if not values:
        return 0.0
    values=sorted(values)
    idx=max(0,min(len(values)-1,int((len(values)-1)*p)))
    return values[idx]

def write_test_configs(ws_port,tunnel_port,target_port):
    server_cfg=f"""[server]
listen_host="127.0.0.1"
listen_port={ws_port}
websocket_path="/ws"
auto_update=false
ping_timeout=30

[auth]
token="test_token_123456"

[tunnels]
ports=["{tunnel_port}={target_port}"]

[logging]
level="info"
file="/tmp/ghostwire-cap-server.log"
"""
    client_cfg=f"""[server]
url="ws://127.0.0.1:{ws_port}/ws"
token="test_token_123456"
auto_update=false

[reconnect]
initial_delay=1
max_delay=10
multiplier=2

[cloudflare]
enabled=false
ips=[]
host=""
check_interval=300

[logging]
level="info"
file="/tmp/ghostwire-cap-client.log"
"""
    server_path=f"/tmp/ghostwire-cap-server-{ws_port}.toml"
    client_path=f"/tmp/ghostwire-cap-client-{ws_port}.toml"
    with open(server_path,"w") as f:
        f.write(server_cfg)
    with open(client_path,"w") as f:
        f.write(client_cfg)
    return server_path,client_path

class BackendServer:
    def __init__(self,port):
        self.port=port
        self.server=None
    async def start(self):
        async def handle(reader,writer):
            try:
                await asyncio.wait_for(reader.read(2048),timeout=10)
                body=b"OK"
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n"+body)
                await writer.drain()
                writer.close()
                await writer.wait_closed()
            except:
                pass
        self.server=await asyncio.start_server(handle,"127.0.0.1",self.port,backlog=20000)
    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()

async def one_request(port,start_event,timeout):
    await start_event.wait()
    begin=time.time()
    try:
        reader,writer=await asyncio.wait_for(asyncio.open_connection("127.0.0.1",port),timeout=timeout)
        writer.write(b"GET / HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n")
        await asyncio.wait_for(writer.drain(),timeout=timeout)
        data=await asyncio.wait_for(reader.read(256),timeout=timeout)
        writer.close()
        await writer.wait_closed()
        if data:
            return True,time.time()-begin,None
        return False,None,"EmptyResponse"
    except Exception as e:
        return False,None,type(e).__name__

async def warmup_request(port,timeout):
    begin=time.time()
    try:
        reader,writer=await asyncio.wait_for(asyncio.open_connection("127.0.0.1",port),timeout=timeout)
        writer.write(b"GET / HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n")
        await asyncio.wait_for(writer.drain(),timeout=timeout)
        data=await asyncio.wait_for(reader.read(256),timeout=timeout)
        writer.close()
        await writer.wait_closed()
        if data:
            return True,time.time()-begin,None
        return False,None,"EmptyResponse"
    except Exception as e:
        return False,None,type(e).__name__

async def run_test(total_requests,timeout):
    print("🚧 GhostWire Concurrency Cap Test")
    print("="*60)
    print(f"Simultaneous requests: {total_requests}")
    ws_port=get_free_port()
    tunnel_port=get_free_port()
    target_port=get_free_port()
    server_cfg,client_cfg=write_test_configs(ws_port,tunnel_port,target_port)
    backend=BackendServer(target_port)
    await backend.start()
    print(f"✅ Backend started on {target_port}")
    server=subprocess.Popen(["python3.13","server.py","-c",server_cfg],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(2)
    if server.poll() is not None:
        print("❌ GhostWire server failed to start")
        await backend.stop()
        return False
    client=subprocess.Popen(["python3.13","client.py","-c",client_cfg],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(3)
    if client.poll() is not None:
        print("❌ GhostWire client failed to start")
        server.terminate()
        await backend.stop()
        return False
    print(f"✅ Tunnel active on {tunnel_port}")
    for _ in range(20):
        try:
            ok,_,_=await warmup_request(tunnel_port,1)
        except:
            ok=False
        if ok:
            break
    start_event=asyncio.Event()
    tasks=[asyncio.create_task(one_request(tunnel_port,start_event,timeout)) for _ in range(total_requests)]
    await asyncio.sleep(0.2)
    start=time.time()
    start_event.set()
    results=await asyncio.gather(*tasks)
    elapsed=time.time()-start
    success=0
    lats=[]
    errors=Counter()
    for ok,lat,err in results:
        if ok:
            success+=1
            lats.append(lat)
        else:
            errors[err or "Unknown"]+=1
    fail=total_requests-success
    rps=success/elapsed if elapsed>0 else 0.0
    p50=percentile(lats,0.50)
    p95=percentile(lats,0.95)
    p99=percentile(lats,0.99)
    print("\n📊 Results")
    print(f"total={total_requests} success={success} fail={fail} success_rate={((success/total_requests)*100):.2f}%")
    print(f"duration={elapsed:.2f}s success_rps={rps:.2f}")
    print(f"latency_p50={p50:.4f}s latency_p95={p95:.4f}s latency_p99={p99:.4f}s")
    print(f"errors={dict(errors)}")
    server.terminate()
    client.terminate()
    await backend.stop()
    await asyncio.sleep(1)
    print("\n🔎 Verdict")
    if success==total_requests:
        print("No observable concurrent request cap at this load profile")
    else:
        print("Concurrent cap or resource saturation observed")
    return True

def parse_args():
    parser=argparse.ArgumentParser(description="GhostWire concurrent request cap test")
    parser.add_argument("--requests",type=int,default=10000,help="Number of simultaneous requests")
    parser.add_argument("--timeout",type=float,default=8.0,help="Per-request timeout in seconds")
    return parser.parse_args()

try:
    args=parse_args()
    result=asyncio.run(run_test(args.requests,args.timeout))
    sys.exit(0 if result else 1)
except KeyboardInterrupt:
    print("\nInterrupted")
    subprocess.run(["killall","-9","python3.13"],stderr=subprocess.DEVNULL)
    sys.exit(1)
except Exception as e:
    print(f"\nError: {e}")
    import traceback
    traceback.print_exc()
    subprocess.run(["killall","-9","python3.13"],stderr=subprocess.DEVNULL)
    sys.exit(1)
