#!/usr/bin/env python3.13
import asyncio
import logging
import signal
import sys
import time
import argparse
import websockets
from protocol import *
from config import ServerConfig
from auth import validate_token
from tunnel import TunnelManager

logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(message)s")
logger=logging.getLogger(__name__)

class GhostWireServer:
    def __init__(self,config):
        self.config=config
        self.clients={}
        self.running=False

    async def handle_client(self,websocket,path):
        client_id=f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"New connection from {client_id}")
        tunnel_manager=TunnelManager()
        key=None
        authenticated=False
        try:
            buffer=b""
            async for message in websocket:
                buffer+=message
                while len(buffer)>=9:
                    if not authenticated:
                        msg_type,conn_id,token,consumed=unpack_message(buffer,None)
                        buffer=buffer[consumed:]
                        if msg_type!=MSG_AUTH:
                            logger.warning(f"Expected AUTH message from {client_id}")
                            return
                        if not validate_token(token,self.config.token):
                            logger.warning(f"Invalid token from {client_id}")
                            return
                        authenticated=True
                        key=derive_key(token,f"ws://{self.config.listen_host}:{self.config.listen_port}{self.config.websocket_path}")
                        logger.info(f"Client {client_id} authenticated")
                        continue
                    try:
                        msg_type,conn_id,payload,consumed=unpack_message(buffer,key)
                        buffer=buffer[consumed:]
                    except ValueError:
                        break
                    if msg_type==MSG_CONNECT:
                        await self.handle_connect(websocket,conn_id,payload,tunnel_manager,key)
                    elif msg_type==MSG_DATA:
                        await self.handle_data(conn_id,payload,tunnel_manager)
                    elif msg_type==MSG_CLOSE:
                        await self.handle_close(conn_id,tunnel_manager)
                    elif msg_type==MSG_PING:
                        timestamp=struct.unpack("!Q",payload)[0]
                        await websocket.send(pack_pong(timestamp,key))
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client {client_id} disconnected")
        except Exception as e:
            logger.error(f"Error handling client {client_id}: {e}")
        finally:
            tunnel_manager.close_all()

    async def handle_connect(self,websocket,conn_id,payload,tunnel_manager,key):
        try:
            remote_ip,remote_port=unpack_connect(payload)
            logger.info(f"CONNECT request: {conn_id} -> {remote_ip}:{remote_port}")
            reader,writer=await asyncio.wait_for(asyncio.open_connection(remote_ip,remote_port),timeout=10)
            tunnel_manager.add_connection(conn_id,(reader,writer))
            asyncio.create_task(self.forward_remote_to_websocket(conn_id,reader,websocket,tunnel_manager,key))
        except Exception as e:
            logger.error(f"Failed to connect to {remote_ip}:{remote_port}: {e}")
            error_msg=pack_error(conn_id,str(e),key)
            await websocket.send(error_msg)

    async def handle_data(self,conn_id,payload,tunnel_manager):
        connection=tunnel_manager.get_connection(conn_id)
        if connection:
            reader,writer=connection
            try:
                writer.write(payload)
                await writer.drain()
            except Exception as e:
                logger.error(f"Error writing to connection {conn_id}: {e}")
                tunnel_manager.remove_connection(conn_id)

    async def handle_close(self,conn_id,tunnel_manager):
        logger.info(f"CLOSE request: {conn_id}")
        tunnel_manager.remove_connection(conn_id)

    async def forward_remote_to_websocket(self,conn_id,reader,websocket,tunnel_manager,key):
        try:
            while True:
                data=await reader.read(65536)
                if not data:
                    break
                message=pack_data(conn_id,data,key)
                await websocket.send(message)
        except Exception as e:
            logger.debug(f"Forward error for {conn_id}: {e}")
        finally:
            tunnel_manager.remove_connection(conn_id)
            try:
                await websocket.send(pack_close(conn_id,0,key))
            except:
                pass

    async def start(self):
        self.running=True
        logger.info(f"Starting GhostWire server on {self.config.listen_host}:{self.config.listen_port}")
        async with websockets.serve(self.handle_client,self.config.listen_host,self.config.listen_port,max_size=None):
            await asyncio.Future()

    def stop(self):
        self.running=False

def signal_handler(server):
    logger.info("Received shutdown signal")
    server.stop()

def main():
    parser=argparse.ArgumentParser(description="GhostWire Server")
    parser.add_argument("-c","--config",help="Path to configuration file")
    parser.add_argument("--generate-token",action="store_true",help="Generate authentication token and exit")
    args=parser.parse_args()
    if args.generate_token:
        from auth import generate_token
        print(generate_token())
        sys.exit(0)
    if not args.config:
        parser.error("--config is required")
        sys.exit(1)
    try:
        config=ServerConfig(args.config)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)
    server=GhostWireServer(config)
    loop=asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGTERM,signal.SIGINT):
        loop.add_signal_handler(sig,lambda:signal_handler(server))
    try:
        loop.run_until_complete(server.start())
    except KeyboardInterrupt:
        logger.info("Server stopped")
    finally:
        loop.close()

if __name__=="__main__":
    main()
