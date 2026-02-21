#!/usr/bin/env python3.13
import asyncio
import subprocess
import time
import sys

class DataServer:
    def __init__(self,port,response_size=10000):
        self.port=port
        self.response_size=response_size
        self.server=None
        self.request_count=0
    async def start(self):
        async def handle(reader,writer):
            try:
                await reader.read(1024)
                self.request_count+=1
                data=b"X"*self.response_size
                writer.write(b"HTTP/1.0 200 OK\r\nContent-Length: %d\r\n\r\n"%len(data))
                writer.write(data)
                await writer.drain()
                writer.close()
            except:
                pass
        self.server=await asyncio.start_server(handle,"127.0.0.1",self.port)
    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()

async def download_data(port,size=10000):
    """Make request and download data through tunnel"""
    start=time.time()
    try:
        reader,writer=await asyncio.wait_for(asyncio.open_connection("127.0.0.1",port),timeout=10)
        writer.write(b"GET / HTTP/1.0\r\n\r\n")
        await writer.drain()
        total=0
        while total<size:
            chunk=await asyncio.wait_for(reader.read(8192),timeout=10)
            if not chunk:
                break
            total+=len(chunk)
        writer.close()
        elapsed=time.time()-start
        return total,elapsed
    except Exception as e:
        return 0,time.time()-start

async def test():
    print("⚡ Concurrent Throughput Benchmark")
    print("="*60)
    print("Measuring: Performance with many concurrent connections\n")
    data_server=DataServer(8888,response_size=50000)
    await data_server.start()
    print("✅ Data server started (50KB responses)\n")
    server=subprocess.Popen(["python3.13","server.py","-c","test_server.toml"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(2)
    if server.poll() is not None:
        print("❌ Server failed to start")
        await data_server.stop()
        return False
    client=subprocess.Popen(["python3.13","client.py","-c","test_client.toml"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(2)
    print("✅ GhostWire started\n")
    test_cases=[
        (10,"10 connections"),
        (25,"25 connections"),
        (50,"50 connections"),
    ]
    for num_conn,label in test_cases:
        print(f"🧪 Test: {label}")
        start=time.time()
        tasks=[download_data(9080) for _ in range(num_conn)]
        results=await asyncio.gather(*tasks)
        elapsed=time.time()-start
        total_bytes=sum(size for size,_ in results)
        successful=sum(1 for size,_ in results if size>0)
        throughput_mbps=(total_bytes*8/1000000)/elapsed
        avg_latency=sum(t for _,t in results)/len(results)
        print(f"   ✓ Successful: {successful}/{num_conn}")
        print(f"   ✓ Total time: {elapsed:.2f}s")
        print(f"   ✓ Throughput: {throughput_mbps:.2f} Mbps")
        print(f"   ✓ Avg latency: {avg_latency:.2f}s")
        print()
        await asyncio.sleep(1)
    print(f"📊 Server processed {data_server.request_count} total requests")
    server.terminate()
    client.terminate()
    await data_server.stop()
    await asyncio.sleep(1)
    print("\n✅ Benchmark complete!")
    print("   Save these numbers to compare with concurrent receive implementation")
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
