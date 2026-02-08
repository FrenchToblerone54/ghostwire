#!/usr/bin/env python3.13
import asyncio
import logging
import signal
import sys
import time
import struct
import argparse
import websockets
from http import HTTPStatus
from protocol import *
from config import ServerConfig
from auth import validate_token
from tunnel import TunnelManager
from updater import Updater
from panel import start_panel

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
        self.send_queue=None
        self.shutdown_event=asyncio.Event()
        self.last_ping_time=0
        self.ping_timeout=45
        logger.info("Generating RSA key pair for secure authentication...")
        self.private_key,self.public_key=generate_rsa_keypair()
        self.updater=Updater("server")

    async def sender_task(self,websocket,send_queue,stop_event):
        try:
            while not stop_event.is_set():
                try:
                    message=await asyncio.wait_for(send_queue.get(),timeout=0.1)
                    await websocket.send(message)
                except asyncio.TimeoutError:
                    continue
        except Exception as e:
            logger.debug(f"Sender task error: {e}")
        finally:
            logger.debug("Sender task stopped")
    async def handle_client(self,websocket):
        client_id=f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"New connection from {client_id}")
        authenticated=False
        sender=None
        ping_monitor=None
        send_queue=asyncio.Queue(maxsize=50000)
        stop_event=asyncio.Event()
        self.last_ping_time=time.time()
        try:
            pubkey_msg=pack_pubkey(self.public_key)
            await websocket.send(pubkey_msg)
            buffer=b""
            auth_msg=await asyncio.wait_for(websocket.recv(),timeout=30)
            buffer+=auth_msg
            if len(buffer)>=9:
                msg_type,conn_id,encrypted_token,consumed=unpack_message(buffer,None)
                buffer=buffer[consumed:]
                if msg_type!=MSG_AUTH:
                    logger.warning(f"Expected AUTH message from {client_id}")
                    return
                try:
                    token=rsa_decrypt(self.private_key,encrypted_token).decode()
                except Exception as e:
                    logger.warning(f"Failed to decrypt token from {client_id}: {e}")
                    return
                if not validate_token(token,self.config.token):
                    logger.warning(f"Invalid token from {client_id}")
                    return
                authenticated=True
                self.key=derive_key(token)
                logger.info(f"Client {client_id} authenticated")
                self.websocket=websocket
                self.send_queue=send_queue
                sender=asyncio.create_task(self.sender_task(websocket,send_queue,stop_event))
                ping_monitor=asyncio.create_task(self.ping_monitor_loop())
                if not self.listeners:
                    await self.start_listeners()
            async for message in websocket:
                self.last_ping_time=time.time()
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
                    elif msg_type==MSG_PING:
                        timestamp=struct.unpack("!Q",payload)[0]
                        try:
                            send_queue.put_nowait(pack_pong(timestamp,self.key))
                        except asyncio.QueueFull:
                            logger.warning(f"Send queue full, dropping PONG")
                    elif msg_type==MSG_PONG:
                        pass
        except asyncio.TimeoutError:
            logger.warning(f"Client {client_id} authentication timeout")
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client {client_id} disconnected")
        except Exception as e:
            logger.error(f"Error handling client {client_id}: {e}",exc_info=True)
        finally:
            if sender:
                stop_event.set()
                try:
                    await asyncio.wait_for(sender,timeout=2)
                except:
                    sender.cancel()
            if ping_monitor:
                ping_monitor.cancel()
            self.websocket=None
            self.send_queue=None
            self.tunnel_manager.close_all()

    async def ping_monitor_loop(self):
        while self.running and not self.shutdown_event.is_set():
            await asyncio.sleep(15)
            if time.time()-self.last_ping_time>self.ping_timeout:
                logger.warning("Client ping timeout, closing connection")
                if self.websocket:
                    await self.websocket.close()
                break

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
            if not self.websocket or not self.send_queue:
                logger.error(f"No client connected, dropping connection {conn_id}")
                self.tunnel_manager.remove_connection(conn_id)
                writer.close()
                await writer.wait_closed()
                return
            connect_msg=pack_connect(conn_id,remote_ip,remote_port,self.key)
            try:
                self.send_queue.put_nowait(connect_msg)
            except (asyncio.QueueFull,AttributeError):
                logger.error(f"Send queue unavailable, dropping connection {conn_id}")
                self.tunnel_manager.remove_connection(conn_id)
                writer.close()
                await writer.wait_closed()
                return
            asyncio.create_task(self.forward_local_to_websocket(conn_id,reader))
        except Exception as e:
            logger.error(f"Error sending CONNECT: {e}")
            self.tunnel_manager.remove_connection(conn_id)
            writer.close()
            await writer.wait_closed()

    async def forward_local_to_websocket(self,conn_id,reader):
        try:
            while True:
                data=await reader.read(131072)
                if not data:
                    break
                if not self.websocket or not self.send_queue:
                    logger.debug(f"Client disconnected, stopping forward for {conn_id}")
                    break
                message=pack_data(conn_id,data,self.key)
                try:
                    await self.send_queue.put(message)
                except (asyncio.QueueFull,AttributeError):
                    logger.warning(f"Send queue unavailable, stopping forward for {conn_id}")
                    break
        except Exception as e:
            logger.debug(f"Forward error for {conn_id}: {e}")
        finally:
            try:
                if self.websocket and self.send_queue:
                    self.send_queue.put_nowait(pack_close(conn_id,0,self.key))
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

    async def process_request(self,connection,request):
        if request.path!=self.config.websocket_path:
            return connection.respond(HTTPStatus.NOT_FOUND,"")
    async def start(self):
        self.running=True
        logger.info(f"Starting GhostWire server on {self.config.listen_host}:{self.config.listen_port}")
        start_panel(self.config)
        update_task=None
        if self.config.auto_update:
            update_task=asyncio.create_task(self.updater.update_loop(self.shutdown_event))
        async with websockets.serve(self.handle_client,self.config.listen_host,self.config.listen_port,max_size=None,ping_interval=None,process_request=self.process_request):
            await self.shutdown_event.wait()
        if update_task:
            update_task.cancel()
        logger.info("Server shutting down")

    def stop(self):
        self.running=False
        self.shutdown_event.set()

def signal_handler(server,loop):
    logger.info("Received shutdown signal")
    loop.call_soon_threadsafe(server.stop)

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
        loop.add_signal_handler(sig,lambda:signal_handler(server,loop))
    try:
        loop.run_until_complete(server.start())
    except KeyboardInterrupt:
        logger.info("Server stopped")
    finally:
        loop.close()

if __name__=="__main__":
    main()
