#!/usr/bin/env python3.13
import asyncio
import subprocess
import time

async def test():
    print("🔄 Quick Reconnection Test")
    print("="*40)
    server=subprocess.Popen(["python3.13","server.py","-c","test_server.toml"])
    await asyncio.sleep(2)
    for i in range(5):
        print(f"Cycle {i+1}/5: Starting client...")
        client=subprocess.Popen(["python3.13","client.py","-c","test_client.toml"])
        await asyncio.sleep(2)
        print(f"  Killing client...")
        client.terminate()
        client.wait()
        await asyncio.sleep(1)
        if server.poll() is not None:
            print("❌ Server crashed!")
            return False
        print(f"  ✅ Server still running")
    server.terminate()
    server.wait()
    print("\n✅ All cycles completed successfully!")
    return True

try:
    result=asyncio.run(test())
except KeyboardInterrupt:
    print("\nInterrupted")
    subprocess.run(["killall","-9","ghostwire-server","ghostwire-client"],stderr=subprocess.DEVNULL)
