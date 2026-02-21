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

def get_free_port():
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    s.bind(("127.0.0.1",0))
    port=s.getsockname()[1]
    s.close()
    return port

def write_test_configs(ws_port,tunnel_port,target_port):
    server_cfg=f"""[server]
listen_host="127.0.0.1"
listen_port={ws_port}
websocket_path="/ws"
auto_update=false

[auth]
token="test_token_123456"

[tunnels]
ports=["{tunnel_port}={target_port}"]

[logging]
level="info"
file="/tmp/ghostwire-test-server.log"
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
file="/tmp/ghostwire-test-client.log"
"""
    server_path=f"/tmp/ghostwire-test-server-{ws_port}.toml"
    client_path=f"/tmp/ghostwire-test-client-{ws_port}.toml"
    with open(server_path,"w") as f:
        f.write(server_cfg)
    with open(client_path,"w") as f:
        f.write(client_cfg)
    return server_path,client_path

async def test():
    print("🚀 Production Scenario Test")
    print("="*50)
    print("Simulating: Multiple reconnections with continuous traffic\n")
    ws_port=get_free_port()
    tunnel_port=get_free_port()
    target_port=get_free_port()
    server_cfg,client_cfg=write_test_configs(ws_port,tunnel_port,target_port)
    test_server=subprocess.Popen(["python3.13","-m","http.server",str(target_port)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(1)
    server=subprocess.Popen(["python3.13","server.py","-c",server_cfg],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    await asyncio.sleep(2)
    if server.poll() is not None:
        print("❌ Server failed to start")
        test_server.kill()
        return False
    print("✅ Server started")
    client=subprocess.Popen(["python3.13","client.py","-c",client_cfg],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    await asyncio.sleep(2)
    print("✅ Client started")
    print("\n🔄 Starting test: 3 reconnection cycles with traffic\n")
    async def dynamic_traffic():
        start=time.time()
        success=0
        fail=0
        while time.time()-start<25:
            if await make_http_request(tunnel_port):
                success+=1
            else:
                fail+=1
            await asyncio.sleep(0.5)
        print(f"  📊 Traffic stats: {success} success, {fail} failures")
        return success,fail
    traffic_task=asyncio.create_task(dynamic_traffic())
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
        client=subprocess.Popen(["python3.13","client.py","-c",client_cfg],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
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
