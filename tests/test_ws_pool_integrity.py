#!/usr/bin/env python3.13
import asyncio
import subprocess
import time
import socket
import sys
import struct
import hashlib
import os
import traceback

def get_free_port():
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.bind(("127.0.0.1",0))
    port=s.getsockname()[1]
    s.close()
    return port

def write_test_configs(ws_port,tunnel_port,target_port):
    server_cfg=f"""[server]
protocol="websocket"
listen_host="127.0.0.1"
listen_port={ws_port}
websocket_path="/ws"
auto_update=false
ping_timeout=60
ws_pool_enabled=true
ws_pool_children=3

[auth]
token="test_token_123456"

[tunnels]
ports=["{tunnel_port}={target_port}"]

[logging]
level="info"
file="/tmp/ghostwire-integrity-server.log"
"""
    client_cfg=f"""[server]
protocol="websocket"
url="ws://127.0.0.1:{ws_port}/ws"
token="test_token_123456"
auto_update=false
ping_interval=15
ping_timeout=60

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
file="/tmp/ghostwire-integrity-client.log"
"""
    server_path=f"/tmp/ghostwire-integrity-server-{ws_port}.toml"
    client_path=f"/tmp/ghostwire-integrity-client-{ws_port}.toml"
    with open(server_path,"w") as f:
        f.write(server_cfg)
    with open(client_path,"w") as f:
        f.write(client_cfg)
    return server_path,client_path

class EchoServer:
    def __init__(self,port):
        self.port=port
        self.server=None
    async def start(self):
        async def handle(reader,writer):
            try:
                while True:
                    hdr=await reader.readexactly(4)
                    size=struct.unpack("!I",hdr)[0]
                    if size==0:
                        break
                    data=await reader.readexactly(size)
                    writer.write(hdr)
                    writer.write(data)
                    await writer.drain()
            except:
                pass
            finally:
                try:
                    writer.close()
                    await writer.wait_closed()
                except:
                    pass
        self.server=await asyncio.start_server(handle,"127.0.0.1",self.port,backlog=4096)
    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()

def make_payload(size,seed):
    block=hashlib.sha256(f"{seed}".encode()).digest()
    out=bytearray()
    while len(out)<size:
        out.extend(block)
        block=hashlib.sha256(block).digest()
    return bytes(out[:size])

async def echo_once(port,payload,timeout=20):
    try:
        reader,writer=await asyncio.wait_for(asyncio.open_connection("127.0.0.1",port),timeout=timeout)
        writer.write(struct.pack("!I",len(payload)))
        writer.write(payload)
        await asyncio.wait_for(writer.drain(),timeout=timeout)
        hdr=await asyncio.wait_for(reader.readexactly(4),timeout=timeout)
        size=struct.unpack("!I",hdr)[0]
        data=await asyncio.wait_for(reader.readexactly(size),timeout=timeout)
        try:
            writer.write(struct.pack("!I",0))
            await asyncio.wait_for(writer.drain(),timeout=3)
        except:
            pass
        writer.close()
        await writer.wait_closed()
        return data==payload,None
    except Exception as e:
        return False,type(e).__name__

async def wait_tunnel_ready(port,timeout=15):
    deadline=time.time()+timeout
    while time.time()<deadline:
        ok,_=await echo_once(port,b"hello",timeout=2)
        if ok:
            return True
        await asyncio.sleep(0.2)
    return False

async def wait_children(log_file,min_count=2,timeout=12):
    deadline=time.time()+timeout
    while time.time()<deadline:
        try:
            with open(log_file,"r") as f:
                data=f.read()
            if data.count("Child channel established")>=min_count:
                return True
        except:
            pass
        await asyncio.sleep(0.3)
    return False

async def concurrent_integrity(port,total,concurrency,payload_size):
    sem=asyncio.Semaphore(concurrency)
    ok_count=0
    errors={}
    async def one(i):
        nonlocal ok_count
        async with sem:
            payload=make_payload(payload_size,i)
            ok,err=await echo_once(port,payload,timeout=25)
            if ok:
                ok_count+=1
                return
            errors[err]=errors.get(err,0)+1
    start=time.time()
    await asyncio.gather(*[one(i) for i in range(total)])
    elapsed=time.time()-start
    total_bytes=payload_size*total*2
    mbps=(total_bytes*8/1000000)/elapsed if elapsed>0 else 0.0
    return ok_count,elapsed,mbps,errors

async def single_large_integrity(port,payload_size):
    payload=make_payload(payload_size,999999)
    start=time.time()
    ok,err=await echo_once(port,payload,timeout=90)
    elapsed=time.time()-start
    mbps=((payload_size*2)*8/1000000)/elapsed if elapsed>0 else 0.0
    return ok,elapsed,mbps,err

async def run_test():
    print("🔒 WS Pool Striping Integrity Test")
    print("="*60)
    ws_port=get_free_port()
    tunnel_port=get_free_port()
    target_port=get_free_port()
    server_cfg,client_cfg=write_test_configs(ws_port,tunnel_port,target_port)
    for p in ("/tmp/ghostwire-integrity-server.log","/tmp/ghostwire-integrity-client.log"):
        try:
            os.remove(p)
        except:
            pass
    backend=EchoServer(target_port)
    await backend.start()
    print(f"✅ Echo backend started on {target_port}")
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
    ready=await wait_tunnel_ready(tunnel_port,timeout=20)
    if not ready:
        print("❌ Tunnel did not become ready")
        server.terminate()
        client.terminate()
        await backend.stop()
        return False
    print(f"✅ Tunnel active on {tunnel_port}")
    child_ok=await wait_children("/tmp/ghostwire-integrity-client.log",min_count=2,timeout=12)
    print(f"✅ Child channels established: {child_ok}")
    if not child_ok:
        print("❌ Expected child websocket channels for striping were not established")
        server.terminate()
        client.terminate()
        await backend.stop()
        return False
    print("\n1) Concurrent integrity under load")
    ok_count,elapsed,mbps,errors=await concurrent_integrity(tunnel_port,total=120,concurrency=24,payload_size=262144)
    print(f"   success={ok_count}/120 duration={elapsed:.2f}s throughput={mbps:.2f} Mbps errors={errors}")
    print("\n2) Single large-stream integrity")
    single_ok,single_elapsed,single_mbps,single_err=await single_large_integrity(tunnel_port,payload_size=32*1024*1024)
    print(f"   success={single_ok} duration={single_elapsed:.2f}s throughput={single_mbps:.2f} Mbps error={single_err}")
    server.terminate()
    client.terminate()
    await backend.stop()
    await asyncio.sleep(1)
    if ok_count!=120:
        print("\n❌ FAIL: concurrent integrity failed")
        return False
    if not single_ok:
        print("\n❌ FAIL: large-stream integrity failed")
        return False
    print("\n✅ PASS: integrity maintained under ws-pool striping and high load")
    return True

try:
    result=asyncio.run(run_test())
    sys.exit(0 if result else 1)
except KeyboardInterrupt:
    print("\nInterrupted")
    subprocess.run(["killall","-9","python3.13"],stderr=subprocess.DEVNULL)
    sys.exit(1)
except Exception as e:
    print(f"\nError: {e}")
    traceback.print_exc()
    subprocess.run(["killall","-9","python3.13"],stderr=subprocess.DEVNULL)
    sys.exit(1)
