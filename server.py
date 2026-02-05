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
        self.running=False
        self.websocket=None
        self.key=None
        self.tunnel_manager=TunnelManager()
        self.listeners=[]

    async def handle_client(self,websocket,path):
        client_id=f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"New connection from {client_id}")
        authenticated=False
        try:
            buffer=b""
            auth_msg=await asyncio.wait_for(websocket.recv(),timeout=10)
            buffer+=auth_msg
            if len(buffer)>=9:
                msg_type,conn_id,token,consumed=unpack_message(buffer,None)
                buffer=buffer[consumed:]
                if msg_type!=MSG_AUTH:
                    logger.warning(f"Expected AUTH message from {client_id}")
                    return
                if not validate_token(token,self.config.token):
                    logger.warning(f"Invalid token from {client_id}")
                    return
                authenticated=True
                self.key=derive_key(token,f"ws://{self.config.listen_host}:{self.config.listen_port}{self.config.websocket_path}")
                logger.info(f"Client {client_id} authenticated")
                self.websocket=websocket
                if not self.listeners:
                    await self.start_listeners()
            async for message in websocket:
                buffer+=message
                while len(buffer)>=9:
                    try:
                        msg_type,conn_id,payload,consumed=unpack_message(buffer,self.key)
                        buffer=buffer[consumed:]
                    except ValueError:
                        break
                    if msg_type==MSG_DATA:
                        await self.handle_data(conn_id,payload)
                    elif msg_type==MSG_CLOSE:
                        await self.handle_close(conn_id)
                    elif msg_type==MSG_ERROR:
                        logger.error(f"Client error for {conn_id}: {payload.decode()}")
                        self.tunnel_manager.remove_connection(conn_id)
                    elif msg_type==MSG_PONG:
                        pass
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client {client_id} disconnected")
        except Exception as e:
            logger.error(f"Error handling client {client_id}: {e}")
        finally:
            self.websocket=None
            self.tunnel_manager.close_all()

    async def start_listeners(self):
        for local_ip,local_port,remote_ip,remote_port in self.config.port_mappings:
            server=await asyncio.start_server(lambda r,w,rip=remote_ip,rport=remote_port:self.handle_local_connection(r,w,rip,rport),local_ip,local_port)
            self.listeners.append(server)
            logger.info(f"Listening on {local_ip}:{local_port} -> {remote_ip}:{remote_port}")

    async def handle_local_connection(self,reader,writer,remote_ip,remote_port):
        conn_id=self.tunnel_manager.generate_conn_id()
        self.tunnel_manager.add_connection(conn_id,(reader,writer))
        logger.info(f"New local connection {conn_id} -> {remote_ip}:{remote_port}")
        try:
            connect_msg=pack_connect(conn_id,remote_ip,remote_port,self.key)
            await self.websocket.send(connect_msg)
            asyncio.create_task(self.forward_local_to_websocket(conn_id,reader))
        except Exception as e:
            logger.error(f"Error sending CONNECT: {e}")
            self.tunnel_manager.remove_connection(conn_id)

    async def forward_local_to_websocket(self,conn_id,reader):
        try:
            while True:
                data=await reader.read(65536)
                if not data:
                    break
                message=pack_data(conn_id,data,self.key)
                await self.websocket.send(message)
        except Exception as e:
            logger.debug(f"Forward error for {conn_id}: {e}")
        finally:
            try:
                await self.websocket.send(pack_close(conn_id,0,self.key))
            except:
                pass
            self.tunnel_manager.remove_connection(conn_id)

    async def handle_data(self,conn_id,payload):
        connection=self.tunnel_manager.get_connection(conn_id)
        if connection:
            reader,writer=connection
            try:
                writer.write(payload)
                await writer.drain()
            except Exception as e:
                logger.error(f"Error writing to local connection {conn_id}: {e}")
                self.tunnel_manager.remove_connection(conn_id)

    async def handle_close(self,conn_id):
        logger.info(f"CLOSE from client: {conn_id}")
        self.tunnel_manager.remove_connection(conn_id)

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
