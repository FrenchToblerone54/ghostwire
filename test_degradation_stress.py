#!/usr/bin/env python3.13
import asyncio
import subprocess
import time
import socket
import sys
import argparse
import random
from collections import Counter,defaultdict

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
file="/tmp/ghostwire-degrade-server.log"
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
file="/tmp/ghostwire-degrade-client.log"
"""
    server_path=f"/tmp/ghostwire-degrade-server-{ws_port}.toml"
    client_path=f"/tmp/ghostwire-degrade-client-{ws_port}.toml"
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
                req=await asyncio.wait_for(reader.read(4096),timeout=10)
                path="/ok"
                if b"GET " in req:
                    first=req.split(b"\r\n",1)[0].decode(errors="ignore")
                    parts=first.split(" ")
                    if len(parts)>=2:
                        path=parts[1]
                if path=="/ok":
                    body=b"OK"
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n"+body)
                    await writer.drain()
                elif path=="/large":
                    body=b"L"*250000
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: "+str(len(body)).encode()+b"\r\nConnection: close\r\n\r\n")
                    await writer.drain()
                    for i in range(0,len(body),8192):
                        writer.write(body[i:i+8192])
                        await writer.drain()
                elif path=="/slow":
                    body=b"S"*120000
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: "+str(len(body)).encode()+b"\r\nConnection: close\r\n\r\n")
                    await writer.drain()
                    for i in range(0,len(body),4096):
                        writer.write(body[i:i+4096])
                        await writer.drain()
                        await asyncio.sleep(0.01)
                elif path=="/stall":
                    await asyncio.sleep(12)
                    body=b"STALL"
                    writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\n"+body)
                    await writer.drain()
                elif path=="/drop":
                    writer.close()
                    await writer.wait_closed()
                    return
                else:
                    body=b"NF"
                    writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 2\r\nConnection: close\r\n\r\n"+body)
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

async def http_request(port,path,timeout,slow_read=False):
    begin=time.time()
    try:
        reader,writer=await asyncio.wait_for(asyncio.open_connection("127.0.0.1",port),timeout=timeout)
        writer.write(f"GET {path} HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n".encode())
        await asyncio.wait_for(writer.drain(),timeout=timeout)
        data_len=0
        while True:
            chunk=await asyncio.wait_for(reader.read(8192),timeout=timeout)
            if not chunk:
                break
            data_len+=len(chunk)
            if slow_read:
                await asyncio.sleep(0.01)
        writer.close()
        await writer.wait_closed()
        if data_len>0:
            return True,time.time()-begin,None
        return False,None,"EmptyResponse"
    except Exception as e:
        return False,None,type(e).__name__

async def browser_worker(port,end_time,timeout,result_queue):
    while time.time()<end_time:
        path=random.choices(["/ok","/slow","/large","/stall","/drop"],weights=[56,18,16,6,4],k=1)[0]
        slow_read=(path=="/slow" and random.random()<0.7)
        ok,lat,err=await http_request(port,path,timeout,slow_read=slow_read)
        await result_queue.put((time.time(),path,ok,lat,err))
        await asyncio.sleep(random.uniform(0.01,0.15))

async def streamer_worker(port,end_time,timeout,result_queue):
    while time.time()<end_time:
        ok,lat,err=await http_request(port,"/slow",timeout,slow_read=True)
        await result_queue.put((time.time(),"/slowstream",ok,lat,err))
        await asyncio.sleep(0.05)

async def aggregate_metrics(result_queue,start_time,end_time,window):
    by_window=defaultdict(list)
    while time.time()<end_time or not result_queue.empty():
        try:
            ts,path,ok,lat,err=await asyncio.wait_for(result_queue.get(),timeout=0.5)
        except asyncio.TimeoutError:
            continue
        idx=int((ts-start_time)//window)
        by_window[idx].append((path,ok,lat,err))
    return by_window

def summarize_window(entries):
    total=len(entries)
    success=0
    lats=[]
    errors=Counter()
    paths=Counter()
    for path,ok,lat,err in entries:
        paths[path]+=1
        if ok:
            success+=1
            if lat is not None:
                lats.append(lat)
        else:
            errors[err or "Unknown"]+=1
    fail=total-success
    rate=(success/total*100) if total>0 else 0.0
    p95=percentile(lats,0.95)
    avg=(sum(lats)/len(lats)) if lats else 0.0
    return total,success,fail,rate,avg,p95,errors,paths

async def run_test(duration,workers,streamers,timeout,window):
    print("🧪 GhostWire Degradation Stress Test")
    print("="*60)
    print(f"duration={duration}s workers={workers} streamers={streamers} timeout={timeout}s window={window}s")
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
    result_queue=asyncio.Queue()
    start_time=time.time()
    end_time=start_time+duration
    worker_tasks=[asyncio.create_task(browser_worker(tunnel_port,end_time,timeout,result_queue)) for _ in range(workers)]
    streamer_tasks=[asyncio.create_task(streamer_worker(tunnel_port,end_time,timeout,result_queue)) for _ in range(streamers)]
    agg_task=asyncio.create_task(aggregate_metrics(result_queue,start_time,end_time,window))
    await asyncio.gather(*worker_tasks,*streamer_tasks)
    by_window=await agg_task
    print("\n📈 Window Metrics")
    ordered=sorted(by_window.keys())
    baseline_rate=None
    baseline_p95=None
    last_rate=0.0
    last_p95=0.0
    bad_windows=0
    for idx in ordered:
        total,success,fail,rate,avg,p95,errors,paths=summarize_window(by_window[idx])
        if baseline_rate is None and total>0:
            baseline_rate=rate
            baseline_p95=p95
        last_rate=rate
        last_p95=p95
        if total>0 and rate<80:
            bad_windows+=1
        print(f"window={idx} total={total} success={success} fail={fail} rate={rate:.2f}% avg={avg:.4f}s p95={p95:.4f}s errors={dict(errors)}")
    server.terminate()
    client.terminate()
    await backend.stop()
    await asyncio.sleep(1)
    if baseline_rate is None:
        print("\n❌ FAIL: no traffic recorded")
        return False
    degrade_rate_drop=baseline_rate-last_rate
    degrade_latency=((last_p95>baseline_p95*2.5) if baseline_p95>0 else False)
    print("\n🔎 Verdict")
    print(f"baseline_rate={baseline_rate:.2f}% last_rate={last_rate:.2f}% drop={degrade_rate_drop:.2f}%")
    print(f"baseline_p95={baseline_p95:.4f}s last_p95={last_p95:.4f}s")
    if degrade_rate_drop>20 or degrade_latency or bad_windows>=2:
        print("DEGRADED")
    else:
        print("STABLE")
    return True

def parse_args():
    parser=argparse.ArgumentParser(description="GhostWire degradation soak stress test")
    parser.add_argument("--duration",type=int,default=300,help="Total test duration in seconds")
    parser.add_argument("--workers",type=int,default=220,help="Concurrent mixed browsing workers")
    parser.add_argument("--streamers",type=int,default=32,help="Concurrent slow stream workers")
    parser.add_argument("--timeout",type=float,default=10.0,help="Per-request timeout")
    parser.add_argument("--window",type=int,default=30,help="Window size for degradation metrics")
    return parser.parse_args()

try:
    args=parse_args()
    result=asyncio.run(run_test(args.duration,args.workers,args.streamers,args.timeout,args.window))
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
