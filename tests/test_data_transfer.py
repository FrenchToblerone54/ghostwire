#!/usr/bin/env python3.13
import asyncio
import subprocess
import sys

async def test_http_request():
    print("Starting HTTP server...")
    http_server=subprocess.Popen(["python3.13","-m","http.server","8888"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(1)
    print("Starting GhostWire server...")
    server=subprocess.Popen(["python3.13","server.py","-c","test_server.toml"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(2)
    print("Starting GhostWire client...")
    client=subprocess.Popen(["python3.13","client.py","-c","test_client.toml"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(2)
    print("\nMaking 5 HTTP requests through tunnel...")
    success=0
    for i in range(5):
        try:
            reader,writer=await asyncio.wait_for(asyncio.open_connection("127.0.0.1",9080),timeout=5)
            writer.write(b"GET / HTTP/1.0\r\n\r\n")
            await writer.drain()
            response=await asyncio.wait_for(reader.read(1000),timeout=5)
            writer.close()
            if len(response)>0 and b"200" in response:
                print(f"  Request {i+1}: ✓ Success")
                success+=1
            else:
                print(f"  Request {i+1}: ✗ Failed (no response)")
        except Exception as e:
            print(f"  Request {i+1}: ✗ Failed ({e})")
    print(f"\nResult: {success}/5 successful")
    server.terminate()
    client.terminate()
    http_server.terminate()
    return success==5

try:
    result=asyncio.run(test_http_request())
    sys.exit(0 if result else 1)
except KeyboardInterrupt:
    print("\nInterrupted")
    subprocess.run(["killall","-9","python3.13"],stderr=subprocess.DEVNULL)
    sys.exit(1)
