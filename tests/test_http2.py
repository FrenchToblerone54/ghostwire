#!/usr/bin/env python3.13
import asyncio
import logging
from config import ServerConfig,ClientConfig
from server import GhostWireServer
from client import GhostWireClient

logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(message)s")

async def test_http2():
    print("Testing HTTP/2 protocol...")
    server_config=ServerConfig("server.toml")
    server_config.protocol="http2"
    server_config.listen_port=9999
    server=GhostWireServer(server_config)
    server_task=asyncio.create_task(server.start())
    await asyncio.sleep(2)
    client_config=ClientConfig("test_config.toml")
    client_config.protocol="http2"
    client_config.server_url="http://localhost:9999"
    client=GhostWireClient(client_config)
    success=await client.connect()
    if success:
        print("✅ HTTP/2 connection successful!")
    else:
        print("❌ HTTP/2 connection failed")
    await asyncio.sleep(2)
    server.stop()
    await server_task

if __name__=="__main__":
    asyncio.run(test_http2())
