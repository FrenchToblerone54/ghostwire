#!/usr/bin/env python3.13
import asyncio
import subprocess
import time
import socket
import sys
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
protocol="grpc"
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
file="/tmp/ghostwire-bench-server.log"
"""
    client_cfg=f"""[server]
protocol="grpc"
url="http://127.0.0.1:{ws_port}/ws"
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
file="/tmp/ghostwire-bench-client.log"
"""
    server_path=f"/tmp/ghostwire-bench-server-{ws_port}.toml"
    client_path=f"/tmp/ghostwire-bench-client-{ws_port}.toml"
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
                req=await asyncio.wait_for(reader.read(2048),timeout=5)
                if b"/slow" in req:
                    body=b"S"*2000000
                elif b"/bulk" in req:
                    body=b"B"*500000
                else:
                    body=b"OK"
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: "+str(len(body)).encode()+b"\r\nConnection: close\r\n\r\n")
                await writer.drain()
                chunk_size=8192
                for i in range(0,len(body),chunk_size):
                    writer.write(body[i:i+chunk_size])
                    await writer.drain()
                    if b"/slow" in req:
                        await asyncio.sleep(0.001)
                writer.close()
                await writer.wait_closed()
            except:
                pass
        self.server=await asyncio.start_server(handle,"127.0.0.1",self.port)
    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()

async def http_request(port,path,slow_read=False):
    start=time.time()
    try:
        reader,writer=await asyncio.wait_for(asyncio.open_connection("127.0.0.1",port),timeout=5)
        writer.write(f"GET {path} HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n".encode())
        await writer.drain()
        total=0
        while True:
            chunk=await asyncio.wait_for(reader.read(8192),timeout=20)
            if not chunk:
                break
            total+=len(chunk)
            if slow_read:
                await asyncio.sleep(0.01)
        writer.close()
        await writer.wait_closed()
        return total,time.time()-start,None
    except Exception as e:
        return 0,None,type(e).__name__

async def run_fast_batch(port,total,concurrency,path="/fast"):
    sem=asyncio.Semaphore(concurrency)
    latencies=[]
    success=0
    errors=Counter()
    async def one():
        nonlocal success
        async with sem:
            size,lat,err=await http_request(port,path,slow_read=False)
            if size>0 and lat is not None:
                success+=1
                latencies.append(lat)
            else:
                errors[err or "Unknown"]+=1
    await asyncio.gather(*[one() for _ in range(total)])
    return success,latencies,errors

async def run_bulk_batch(port,total,concurrency):
    sem=asyncio.Semaphore(concurrency)
    total_bytes=0
    errors=Counter()
    async def one():
        nonlocal total_bytes
        async with sem:
            size,_,err=await http_request(port,"/bulk",slow_read=False)
            total_bytes+=size
            if size==0:
                errors[err or "Unknown"]+=1
    start=time.time()
    await asyncio.gather(*[one() for _ in range(total)])
    elapsed=time.time()-start
    return total_bytes,elapsed,errors

async def run_benchmark():
    print("⚡ Concurrent Receive Speed Test")
    print("="*60)
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
    print(f"✅ Tunnel active on {tunnel_port}\n")
    print("1) Baseline fast latency")
    for _ in range(10):
        await http_request(tunnel_port,"/fast")
    base_success,base_lats,base_errors=await run_fast_batch(tunnel_port,total=100,concurrency=20,path="/fast")
    base_p95=percentile(base_lats,0.95)
    base_avg=(sum(base_lats)/len(base_lats)) if base_lats else 0.0
    print(f"   success={base_success}/100 avg={base_avg:.4f}s p95={base_p95:.4f}s errors={dict(base_errors)}")
    print("\n2) Mixed load: slow readers + fast requests")
    slow_tasks=[asyncio.create_task(http_request(tunnel_port,"/slow",slow_read=True)) for _ in range(8)]
    await asyncio.sleep(0.5)
    mix_success,mix_lats,mix_errors=await run_fast_batch(tunnel_port,total=140,concurrency=28,path="/fast")
    await asyncio.gather(*slow_tasks)
    mix_p95=percentile(mix_lats,0.95)
    mix_avg=(sum(mix_lats)/len(mix_lats)) if mix_lats else 0.0
    print(f"   success={mix_success}/140 avg={mix_avg:.4f}s p95={mix_p95:.4f}s errors={dict(mix_errors)}")
    print("\n3) High-concurrency bulk throughput")
    total_bytes,elapsed,bulk_errors=await run_bulk_batch(tunnel_port,total=60,concurrency=24)
    mbps=(total_bytes*8/1000000)/elapsed if elapsed>0 else 0.0
    print(f"   data={total_bytes} bytes time={elapsed:.2f}s throughput={mbps:.2f} Mbps errors={dict(bulk_errors)}")
    server.terminate()
    client.terminate()
    await backend.stop()
    await asyncio.sleep(1)
    mixed_success_rate=mix_success/140
    latency_ok=(base_p95==0 and mix_p95==0) or (base_p95>0 and mix_p95<=base_p95*6.0)
    if mixed_success_rate<0.90:
        print(f"\n❌ FAIL: mixed success rate too low ({mixed_success_rate*100:.1f}%)")
        return False
    if not latency_ok:
        print(f"\n❌ FAIL: mixed p95 too high vs baseline ({mix_p95:.4f}s vs {base_p95:.4f}s)")
        return False
    print("\n✅ PASS: concurrent receive path handles mixed slow/fast load")
    return True

try:
    result=asyncio.run(run_benchmark())
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
