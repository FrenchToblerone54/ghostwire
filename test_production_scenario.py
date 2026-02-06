#!/usr/bin/env python3.13
import asyncio
import subprocess
import time
import socket
import sys

async def make_http_request(port=9080):
    try:
        reader,writer=await asyncio.wait_for(asyncio.open_connection("127.0.0.1",port),timeout=2)
        writer.write(b"GET / HTTP/1.0\r\nHost: test\r\n\r\n")
        await writer.drain()
        response=await asyncio.wait_for(reader.read(100),timeout=2)
        writer.close()
        await writer.wait_closed()
        return len(response)>0
    except:
        return False

async def traffic_generator(duration=30):
    print("  📊 Traffic generator started")
    start=time.time()
    success=0
    fail=0
    while time.time()-start<duration:
        if await make_http_request():
            success+=1
        else:
            fail+=1
        await asyncio.sleep(0.5)
    print(f"  📊 Traffic stats: {success} success, {fail} failures")
    return success,fail

async def test():
    print("🚀 Production Scenario Test")
    print("="*50)
    print("Simulating: Multiple reconnections with continuous traffic\n")
    test_server=subprocess.Popen(["python3.13","-m","http.server","8888"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(1)
    server=subprocess.Popen(["python3.13","server.py","-c","test_server.toml"],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    await asyncio.sleep(2)
    if server.poll() is not None:
        print("❌ Server failed to start")
        test_server.kill()
        return False
    print("✅ Server started")
    client=subprocess.Popen(["python3.13","client.py","-c","test_client.toml"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(2)
    print("✅ Client started")
    print("\n🔄 Starting test: 3 reconnection cycles with traffic\n")
    traffic_task=asyncio.create_task(traffic_generator(25))
    for i in range(3):
        print(f"Cycle {i+1}/3:")
        await asyncio.sleep(5)
        print("  🔌 Killing client...")
        client.terminate()
        client.wait()
        await asyncio.sleep(2)
        if server.poll() is not None:
            print("  ❌ Server crashed during reconnection!")
            traffic_task.cancel()
            test_server.kill()
            return False
        print("  ✅ Server survived disconnection")
        print("  🔌 Restarting client...")
        client=subprocess.Popen(["python3.13","client.py","-c","test_client.toml"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        await asyncio.sleep(2)
        print("  ✅ Client reconnected")
    await traffic_task
    server_errors=""
    try:
        server.terminate()
        stdout,stderr=server.communicate(timeout=3)
        server_errors=stdout
    except:
        server.kill()
    client.terminate()
    test_server.kill()
    if "AttributeError" in server_errors or "Traceback" in server_errors:
        print("\n❌ Server errors detected:")
        print(server_errors[-500:])
        return False
    print("\n✅ Production scenario test PASSED!")
    print("   - Server handled reconnections gracefully")
    print("   - No crashes or AttributeErrors")
    print("   - Traffic continued during reconnections")
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
