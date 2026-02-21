#!/usr/bin/env python3.13
import asyncio
import subprocess
import time
import signal
import sys

server_proc=None
client_proc=None

def cleanup():
    global server_proc,client_proc
    for proc in [server_proc,client_proc]:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except:
                proc.kill()

def signal_handler(sig,frame):
    cleanup()
    sys.exit(0)

signal.signal(signal.SIGINT,signal_handler)

async def run_reconnection_test():
    global server_proc,client_proc
    print("🔄 GhostWire Reconnection Stress Test")
    print("="*50)
    print("\n📝 Test Plan:")
    print("  1. Start server")
    print("  2. Repeatedly kill and restart client (10 cycles)")
    print("  3. Monitor for AttributeError and crashes")
    print()
    print("🔧 Starting GhostWire server...")
    server_proc=subprocess.Popen(["python3.13","server.py","-c","test_server.toml"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    await asyncio.sleep(2)
    if server_proc.poll() is not None:
        print("❌ Server crashed on startup")
        stdout,stderr=server_proc.communicate()
        print("STDOUT:",stdout)
        print("STDERR:",stderr)
        return False
    print("✅ Server started")
    cycles=10
    errors_found=False
    for i in range(cycles):
        print(f"\n🔄 Cycle {i+1}/{cycles}")
        print("  Starting client...")
        client_proc=subprocess.Popen(["python3.13","client.py","-c","test_client.toml"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        await asyncio.sleep(3)
        print("  Killing client...")
        client_proc.terminate()
        try:
            stdout,stderr=client_proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            client_proc.kill()
            stdout,stderr=client_proc.communicate()
        await asyncio.sleep(1)
        if server_proc.poll() is not None:
            print("\n❌ Server crashed!")
            stdout,stderr=server_proc.communicate()
            print("STDOUT:",stdout)
            print("STDERR:",stderr)
            cleanup()
            return False
        server_stderr=""
        if server_proc.stderr:
            try:
                import select
                if select.select([server_proc.stderr],[],[],0)[0]:
                    server_stderr=server_proc.stderr.read()
            except:
                pass
        if "AttributeError" in server_stderr or "NoneType" in server_stderr:
            print(f"  ❌ AttributeError detected in server output!")
            print(f"  Server error: {server_stderr}")
            errors_found=True
        else:
            print(f"  ✅ No errors detected")
    print(f"\n📊 Test Results:")
    print(f"   Cycles completed: {cycles}")
    print(f"   Server status: {'✅ Running' if server_proc.poll() is None else '❌ Crashed'}")
    print(f"   Errors found: {'❌ Yes' if errors_found else '✅ No'}")
    if not errors_found and server_proc.poll() is None:
        print("\n🎉 Reconnection stress test PASSED!")
        result=True
    else:
        print("\n⚠️  Reconnection stress test FAILED!")
        result=False
    cleanup()
    return result

if __name__=="__main__":
    try:
        result=asyncio.run(run_reconnection_test())
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        cleanup()
        sys.exit(1)
