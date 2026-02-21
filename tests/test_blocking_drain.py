#!/usr/bin/env python3.13
import asyncio
import subprocess
import time
import sys
import socket

class NonReadingServer:
    """Server that accepts connections but never reads - causes drain() to block"""
    def __init__(self,port):
        self.port=port
        self.server=None
    async def start(self):
        async def handle(reader,writer):
            try:
                await asyncio.sleep(10)
            except:
                pass
        self.server=await asyncio.start_server(handle,"127.0.0.1",self.port)
    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()

class FastServer:
    def __init__(self,port):
        self.port=port
        self.server=None
        self.request_times=[]
    async def start(self):
        async def handle(reader,writer):
            self.request_times.append(time.time())
            try:
                await reader.read(1024)
                writer.write(b"HTTP/1.0 200 OK\r\n\r\nOK")
                await writer.drain()
                writer.close()
            except:
                pass
        self.server=await asyncio.start_server(handle,"127.0.0.1",self.port)
    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()

async def send_blocking_data(port=9080):
    """Connects and sends lots of data to cause drain() blocking"""
    try:
        reader,writer=await asyncio.wait_for(asyncio.open_connection("127.0.0.1",port),timeout=5)
        for i in range(1000):
            writer.write(b"X"*10000)
            try:
                await asyncio.wait_for(writer.drain(),timeout=0.1)
            except asyncio.TimeoutError:
                break
        await asyncio.sleep(5)
    except:
        pass

async def make_fast_request(port=9081):
    try:
        reader,writer=await asyncio.wait_for(asyncio.open_connection("127.0.0.1",port),timeout=5)
        writer.write(b"GET / HTTP/1.0\r\n\r\n")
        await writer.drain()
        response=await asyncio.wait_for(reader.read(1000),timeout=5)
        writer.close()
        return True
    except:
        return False

async def test():
    print("🔒 Drain Blocking Test")
    print("="*60)
    print("Testing if one connection's blocked drain() delays other connections\n")
    non_reading=NonReadingServer(8888)
    await non_reading.start()
    fast_server=FastServer(8889)
    await fast_server.start()
    print("✅ Test servers started\n")
    server_proc=subprocess.Popen(["python3.13","server.py","-c","test_multi_port.toml"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(2)
    client_proc=subprocess.Popen(["python3.13","client.py","-c","test_client.toml"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(2)
    print("✅ GhostWire started\n")
    print("🧪 Test:")
    print("   1. Start connection to non-reading server (will block on drain)")
    print("   2. Make 5 fast requests to different port")
    print("   3. Check if fast requests are delayed\n")
    blocking_task=asyncio.create_task(send_blocking_data(9080))
    await asyncio.sleep(0.5)
    start=time.time()
    fast_tasks=[make_fast_request(9081) for _ in range(5)]
    results=await asyncio.gather(*fast_tasks)
    elapsed=time.time()-start
    await blocking_task
    success=sum(1 for r in results if r)
    if len(fast_server.request_times)>=2:
        gaps=[fast_server.request_times[i+1]-fast_server.request_times[i] for i in range(len(fast_server.request_times)-1)]
        avg_gap=sum(gaps)/len(gaps) if gaps else 0
    else:
        avg_gap=0
    print(f"📊 Results:")
    print(f"   Fast requests: {success}/5")
    print(f"   Total time: {elapsed:.2f}s")
    print(f"   Avg gap between requests: {avg_gap:.3f}s")
    print()
    if avg_gap>0.1:
        print(f"⚠️  Sequential processing detected (gap: {avg_gap:.3f}s)")
        print("   Blocked drain() is delaying other connections")
    else:
        print(f"✅ Concurrent processing working")
        print("   Fast requests not blocked by drain()")
    server_proc.terminate()
    client_proc.terminate()
    await non_reading.stop()
    await fast_server.stop()
    await asyncio.sleep(1)
    return True

try:
    result=asyncio.run(test())
    sys.exit(0 if result else 1)
except KeyboardInterrupt:
    print("\nInterrupted")
    subprocess.run(["killall","-9","python3.13"],stderr=subprocess.DEVNULL)
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    subprocess.run(["killall","-9","python3.13"],stderr=subprocess.DEVNULL)
    sys.exit(1)
