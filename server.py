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

def setup_logging(config):
    level=getattr(logging,config.log_level.upper(),logging.INFO)
    logging.getLogger().setLevel(level)
    if config.log_file:
        handler=logging.FileHandler(config.log_file)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(handler)

class GhostWireServer:
    def __init__(self,config):
        self.config=config
        self.running=False
        self.websocket=None
        self.key=None
        self.tunnel_manager=TunnelManager()
        self.listeners=[]
        self.send_queue=None
        self.control_queue=None
        self.shutdown_event=asyncio.Event()
        self.auth_lock=asyncio.Lock()
        self.last_ping_time=0
        self.ping_timeout=config.ping_timeout
        self.conn_write_queues={}
        self.conn_write_tasks={}
        self.client_version=None
        logger.info("Generating RSA key pair for secure authentication...")
        self.private_key,self.public_key=generate_rsa_keypair()
        self.updater=Updater("server",check_interval=config.update_check_interval,check_on_startup=config.update_check_on_startup)

    def clear_conn_writers(self):
        for conn_id,task in list(self.conn_write_tasks.items()):
            if not task.done():
                task.cancel()
        self.conn_write_tasks.clear()
        self.conn_write_queues.clear()

    async def close_conn_writer(self,conn_id,flush=False):
        queue=self.conn_write_queues.get(conn_id)
        task=self.conn_write_tasks.get(conn_id)
        if not queue or not task:
            self.conn_write_queues.pop(conn_id,None)
            self.conn_write_tasks.pop(conn_id,None)
            return
        if flush:
            try:
                await asyncio.wait_for(queue.join(),timeout=5)
            except:
                pass
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            task.cancel()
        try:
            await asyncio.wait_for(task,timeout=2)
        except:
            task.cancel()
        self.conn_write_queues.pop(conn_id,None)
        self.conn_write_tasks.pop(conn_id,None)

    async def conn_writer_loop(self,conn_id,writer,queue):
        try:
            while True:
                payload=await queue.get()
                if payload is None:
                    queue.task_done()
                    break
                writer.write(payload)
                await asyncio.wait_for(writer.drain(),timeout=15)
                queue.task_done()
        except asyncio.TimeoutError:
            logger.warning(f"Write timeout for local connection {conn_id}")
        except Exception as e:
            logger.debug(f"Writer loop error for {conn_id}: {e}")
        finally:
            self.conn_write_queues.pop(conn_id,None)
            self.conn_write_tasks.pop(conn_id,None)
            self.tunnel_manager.remove_connection(conn_id)

    async def sender_task(self,websocket,send_queue,control_queue,stop_event):
        try:
            while not stop_event.is_set() or not send_queue.empty() or not control_queue.empty():
                try:
                    message=control_queue.get_nowait()
                except asyncio.QueueEmpty:
                    try:
                        message=await asyncio.wait_for(send_queue.get(),timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                try:
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
        send_queue=asyncio.Queue(maxsize=32768)
        control_queue=asyncio.Queue(maxsize=16384)
        stop_event=asyncio.Event()
        self.last_ping_time=time.time()
        try:
            pubkey_msg=pack_pubkey(self.public_key)
            await websocket.send(pubkey_msg)
            buffer=b""
            auth_msg=await asyncio.wait_for(websocket.recv(),timeout=30)
            buffer+=auth_msg
            async with self.auth_lock:
                if self.websocket is not None:
                    logger.warning(f"Rejecting {client_id}: client already connected")
                    return
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
                    self.control_queue=control_queue
                    sender=asyncio.create_task(self.sender_task(websocket,send_queue,control_queue,stop_event))
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
                    elif msg_type==MSG_INFO:
                        self.client_version=payload.decode()
                        logger.info(f"Client version: {self.client_version}")
                    elif msg_type==MSG_PING:
                        timestamp=struct.unpack("!Q",payload)[0]
                        try:
                            control_queue.put_nowait(pack_pong(timestamp,self.key))
                        except asyncio.QueueFull:
                            logger.warning(f"Control queue full, dropping PONG")
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
            if authenticated:
                self.clear_conn_writers()
                self.websocket=None
                self.send_queue=None
                self.control_queue=None
                self.client_version=None
                self.tunnel_manager.close_all()

    async def ping_monitor_loop(self):
        interval=max(2,self.ping_timeout//2)
        while self.running and not self.shutdown_event.is_set():
            await asyncio.sleep(interval)
            if time.time()-self.last_ping_time>self.ping_timeout:
                logger.warning("Client ping timeout, closing connection")
                if self.websocket:
                    await self.websocket.close()
                break

    async def start_listeners(self):
        for local_ip,local_port,remote_ip,remote_port in self.config.port_mappings:
            server=await asyncio.start_server(lambda r,w,rip=remote_ip,rport=remote_port:self.handle_local_connection(r,w,rip,rport),local_ip,local_port,backlog=self.config.listen_backlog)
            self.listeners.append(server)
            logger.info(f"Listening on {local_ip}:{local_port} -> {remote_ip}:{remote_port}")

    async def handle_local_connection(self,reader,writer,remote_ip,remote_port):
        conn_id=self.tunnel_manager.generate_conn_id()
        self.tunnel_manager.add_connection(conn_id,(reader,writer))
        logger.info(f"New local connection {conn_id} -> {remote_ip}:{remote_port}")
        try:
            if not self.websocket or not self.send_queue or not self.control_queue:
                logger.error(f"No client connected, dropping connection {conn_id}")
                self.tunnel_manager.remove_connection(conn_id)
                writer.close()
                await writer.wait_closed()
                return
            connect_msg=pack_connect(conn_id,remote_ip,remote_port,self.key)
            try:
                self.control_queue.put_nowait(connect_msg)
            except (asyncio.QueueFull,AttributeError):
                logger.error(f"Control queue unavailable, dropping connection {conn_id}")
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
                data=await reader.read(65536)
                if not data:
                    break
                if not self.websocket or not self.send_queue:
                    logger.debug(f"Client disconnected, stopping forward for {conn_id}")
                    break
                message=pack_data(conn_id,data,self.key)
                try:
                    while self.running and self.send_queue:
                        try:
                            await asyncio.wait_for(self.send_queue.put(message),timeout=1)
                            break
                        except asyncio.TimeoutError:
                            continue
                except AttributeError:
                    logger.warning(f"Send queue unavailable for {conn_id}")
                    break
        except Exception as e:
            logger.debug(f"Forward error for {conn_id}: {e}")
        finally:
            try:
                if self.websocket and self.control_queue:
                    self.control_queue.put_nowait(pack_close(conn_id,0,self.key))
            except:
                pass
            self.tunnel_manager.remove_connection(conn_id)

    async def handle_data(self,conn_id,payload):
        connection=self.tunnel_manager.get_connection(conn_id)
        if connection:
            _,writer=connection
            try:
                queue=self.conn_write_queues.get(conn_id)
                if not queue:
                    queue=asyncio.Queue(maxsize=1024)
                    self.conn_write_queues[conn_id]=queue
                    self.conn_write_tasks[conn_id]=asyncio.create_task(self.conn_writer_loop(conn_id,writer,queue))
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning(f"Write queue full for local connection {conn_id}")
                await self.close_conn_writer(conn_id,flush=False)
            except Exception as e:
                logger.error(f"Error writing to local connection {conn_id}: {e}")
                self.tunnel_manager.remove_connection(conn_id)

    async def handle_close(self,conn_id):
        logger.info(f"CLOSE from client: {conn_id}")
        await self.close_conn_writer(conn_id,flush=True)
        self.tunnel_manager.remove_connection(conn_id)

    async def process_request(self,connection,request):
        if request.path!=self.config.websocket_path:
            return connection.respond(HTTPStatus.NOT_FOUND,"")
    async def start(self):
        self.running=True
        logger.info(f"Starting GhostWire server on {self.config.listen_host}:{self.config.listen_port}")
        start_panel(self.config,self)
        update_task=None
        if self.config.auto_update:
            update_task=asyncio.create_task(self.updater.update_loop(self.shutdown_event))
        async with websockets.serve(self.handle_client,self.config.listen_host,self.config.listen_port,max_size=None,max_queue=32768,ping_interval=None,compression=None,write_limit=16777216,process_request=self.process_request):
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
    parser.add_argument("--version",action="store_true",help="Print version and exit")
    args=parser.parse_args()
    if args.version:
        print(Updater("server").current_version)
        sys.exit(0)
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
    setup_logging(config)
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
