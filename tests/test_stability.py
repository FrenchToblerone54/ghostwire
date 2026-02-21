#!/usr/bin/env python3.13
import asyncio
import subprocess
import time
import socket
import sys
import signal
import os

server_proc=None
client_proc=None
test_server_proc=None

def cleanup():
    global server_proc,client_proc,test_server_proc
    print("\n🧹 Cleaning up processes...")
    for proc in [server_proc,client_proc,test_server_proc]:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

def signal_handler(sig,frame):
    print("\n⚠️  Interrupted by user")
    cleanup()
    sys.exit(0)

signal.signal(signal.SIGINT,signal_handler)

async def wait_for_port(port,host="127.0.0.1",timeout=10):
    start=time.time()
    while time.time()-start<timeout:
        try:
            sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            sock.settimeout(1)
            sock.connect((host,port))
            sock.close()
            return True
        except:
            await asyncio.sleep(0.1)
    return False

async def test_connection(port=9080):
    try:
        sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        sock.settimeout(2)
        sock.connect(("127.0.0.1",port))
        sock.close()
        return True
    except Exception as e:
        return False

async def run_stability_test():
    global server_proc,client_proc,test_server_proc
    print("🚀 GhostWire Stability Test")
    print("="*50)
    print("\n📝 Test Plan:")
    print("  1. Start test HTTP server on port 8888")
    print("  2. Start GhostWire server on port 9443")
    print("  3. Start GhostWire client")
    print("  4. Test tunnel stability for 60 seconds")
    print("  5. Monitor for crashes and reconnections")
    print()
    print("🔧 Starting test HTTP server...")
    test_server_proc=subprocess.Popen(["python3.13","-m","http.server","8888"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(1)
    if not await wait_for_port(8888):
        print("❌ Failed to start test HTTP server")
        cleanup()
        return False
    print("✅ Test HTTP server running on port 8888")
    print("\n🔧 Starting GhostWire server...")
    server_proc=subprocess.Popen(["python3.13","server.py","-c","test_server.toml"],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
    await asyncio.sleep(2)
    if server_proc.poll() is not None:
        print("❌ Server crashed on startup")
        print("Output:",server_proc.stdout.read())
        cleanup()
        return False
    print("✅ GhostWire server started")
    print("\n🔧 Starting GhostWire client...")
    client_proc=subprocess.Popen(["python3.13","client.py","-c","test_client.toml"],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
    await asyncio.sleep(3)
    if client_proc.poll() is not None:
        print("❌ Client crashed on startup")
        print("Output:",client_proc.stdout.read())
        cleanup()
        return False
    print("✅ GhostWire client started")
    print("\n🧪 Testing tunnel connectivity...")
    if not await wait_for_port(9080):
        print("❌ Tunnel port 9080 not accessible")
        cleanup()
        return False
    print("✅ Tunnel port 9080 is accessible")
    print("\n⏱️  Running 60-second stability test...")
    print("   Monitoring for crashes, errors, and connection stability...")
    start_time=time.time()
    success_count=0
    failure_count=0
    test_interval=2
    while time.time()-start_time<60:
        if server_proc.poll() is not None:
            print(f"\n❌ Server crashed after {time.time()-start_time:.1f}s")
            cleanup()
            return False
        if client_proc.poll() is not None:
            print(f"\n❌ Client crashed after {time.time()-start_time:.1f}s")
            cleanup()
            return False
        if await test_connection(9080):
            success_count+=1
            print(f"✓ {int(time.time()-start_time)}s",end=" ",flush=True)
        else:
            failure_count+=1
            print(f"✗ {int(time.time()-start_time)}s",end=" ",flush=True)
        await asyncio.sleep(test_interval)
    elapsed=time.time()-start_time
    success_rate=(success_count/(success_count+failure_count))*100 if (success_count+failure_count)>0 else 0
    print(f"\n\n📊 Test Results:")
    print(f"   Duration: {elapsed:.1f}s")
    print(f"   Successful connections: {success_count}")
    print(f"   Failed connections: {failure_count}")
    print(f"   Success rate: {success_rate:.1f}%")
    print(f"   Server status: {'✅ Running' if server_proc.poll() is None else '❌ Crashed'}")
    print(f"   Client status: {'✅ Running' if client_proc.poll() is None else '❌ Crashed'}")
    if success_rate>=95:
        print("\n🎉 Stability test PASSED!")
        result=True
    else:
        print("\n⚠️  Stability test FAILED - success rate below 95%")
        result=False
    cleanup()
    return result

if __name__=="__main__":
    try:
        result=asyncio.run(run_stability_test())
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        cleanup()
        sys.exit(1)
