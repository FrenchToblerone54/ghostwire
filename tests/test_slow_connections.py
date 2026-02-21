#!/usr/bin/env python3.13
import asyncio
import subprocess
import time
import sys

async def slow_reader(port=9080,read_delay=0.2):
    """Connects and reads very slowly to cause drain() blocking"""
    start=time.time()
    try:
        reader,writer=await asyncio.wait_for(asyncio.open_connection("127.0.0.1",port),timeout=10)
        writer.write(b"GET /slow HTTP/1.0\r\nHost: test\r\n\r\n")
        await writer.drain()
        total=0
        while total<10000:
            chunk=await asyncio.wait_for(reader.read(1000),timeout=10)
            if not chunk:
                break
            total+=len(chunk)
            await asyncio.sleep(read_delay)
        writer.close()
        return time.time()-start
    except Exception as e:
        return time.time()-start

async def fast_reader(port=9080):
    """Makes quick request to measure if blocked by slow reader"""
    start=time.time()
    try:
        reader,writer=await asyncio.wait_for(asyncio.open_connection("127.0.0.1",port),timeout=5)
        writer.write(b"GET /fast HTTP/1.0\r\nHost: test\r\n\r\n")
        await writer.drain()
        response=await asyncio.wait_for(reader.read(1000),timeout=5)
        writer.close()
        elapsed=time.time()-start
        return elapsed if len(response)>0 else None
    except Exception as e:
        return None

class TestServer:
    def __init__(self,port):
        self.port=port
        self.server=None
    async def start(self):
        async def handle(reader,writer):
            try:
                request=await reader.read(1024)
                if b"/slow" in request:
                    for _ in range(100):
                        writer.write(b"X"*100)
                        await writer.drain()
                else:
                    writer.write(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nOK")
                    await writer.drain()
                writer.close()
            except:
                pass
        self.server=await asyncio.start_server(handle,"127.0.0.1",self.port)
    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()

async def test():
    print("🐢 Sequential Receive Blocking Test")
    print("="*60)
    print("Shows: Sequential receive blocks fast requests behind slow ones\n")
    test_server=TestServer(8888)
    await test_server.start()
    print("✅ Test server started\n")
    server=subprocess.Popen(["python3.13","server.py","-c","test_server.toml"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(2)
    client=subprocess.Popen(["python3.13","client.py","-c","test_client.toml"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(2)
    print("✅ GhostWire server+client started\n")
    print("🧪 Test scenario:")
    print("   1. Start slow reader (reads 10KB slowly)")
    print("   2. After 0.5s, make 5 fast requests")
    print("   3. Measure if fast requests are blocked\n")
    slow_task=asyncio.create_task(slow_reader())
    await asyncio.sleep(0.5)
    fast_start=time.time()
    fast_tasks=[fast_reader() for _ in range(5)]
    fast_results=await asyncio.gather(*fast_tasks)
    fast_total=time.time()-fast_start
    slow_time=await slow_task
    successful_fast=sum(1 for r in fast_results if r is not None)
    avg_fast=sum(r for r in fast_results if r is not None)/max(successful_fast,1)
    print(f"📊 Results:")
    print(f"   Slow reader: {slow_time:.2f}s")
    print(f"   Fast requests: {successful_fast}/5 successful")
    print(f"   Fast total time: {fast_total:.2f}s")
    print(f"   Fast avg latency: {avg_fast:.2f}s")
    print()
    if fast_total>1.0 or avg_fast>0.5:
        print(f"⚠️  High latency for fast requests!")
        print("   Sequential receive is blocking fast requests behind slow one")
        print("   Expected with sequential: slow reader blocks message processing")
    else:
        print(f"✅ Low latency for fast requests")
        print("   Concurrent receive is working - fast requests not blocked")
    server.terminate()
    client.terminate()
    await test_server.stop()
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
