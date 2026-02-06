#!/usr/bin/env python3.13
import asyncio
import logging
import signal
import sys
import time
import argparse
import websockets
from protocol import *
from config import ClientConfig
from tunnel import TunnelManager

logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(message)s")
logger=logging.getLogger(__name__)

class GhostWireClient:
    def __init__(self,config):
        self.config=config
        self.tunnel_manager=TunnelManager()
        self.websocket=None
        self.key=None
        self.running=False
        self.reconnect_delay=config.initial_delay
        self.send_queue=asyncio.Queue(maxsize=10000)
        self.shutdown_event=asyncio.Event()

    async def sender_task(self):
        try:
            while True:
                message=await self.send_queue.get()
                if message is None:
                    break
                if self.websocket:
                    await self.websocket.send(message)
        except Exception as e:
            logger.debug(f"Sender task error: {e}")
    async def connect(self):
        try:
            server_url=self.config.server_url
            if self.config.cloudflare_enabled and self.config.cloudflare_ips:
                best_ip=await self.find_best_cloudflare_ip()
                if best_ip:
                    server_url=self.config.server_url.replace(self.config.cloudflare_host,best_ip)
                    logger.info(f"Using CloudFlare IP: {best_ip}")
            self.websocket=await websockets.connect(server_url,max_size=None,ping_interval=None)
            pubkey_msg=await asyncio.wait_for(self.websocket.recv(),timeout=10)
            if len(pubkey_msg)<9:
                raise ValueError("Invalid public key message")
            msg_type,_,pubkey_bytes,_=unpack_message(pubkey_msg,None)
            if msg_type!=MSG_PUBKEY:
                raise ValueError("Expected public key from server")
            server_public_key=deserialize_public_key(pubkey_bytes)
            auth_msg=pack_auth_message(self.config.token,server_public_key)
            await self.websocket.send(auth_msg)
            self.key=derive_key(self.config.token)
            logger.info("Connected and authenticated to server")
            self.reconnect_delay=self.config.initial_delay
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    async def find_best_cloudflare_ip(self):
        best_ip=None
        best_latency=float("inf")
        for ip in self.config.cloudflare_ips:
            try:
                test_url=self.config.server_url.replace(self.config.cloudflare_host,ip)
                start=time.time()
                ws=await asyncio.wait_for(websockets.connect(test_url,max_size=None,ping_interval=None),timeout=5)
                latency=time.time()-start
                await ws.close()
                if latency<best_latency:
                    best_latency=latency
                    best_ip=ip
            except:
                continue
        return best_ip

    async def handle_connect(self,conn_id,remote_ip,remote_port):
        try:
            logger.info(f"CONNECT request: {conn_id} -> {remote_ip}:{remote_port}")
            reader,writer=await asyncio.wait_for(asyncio.open_connection(remote_ip,remote_port),timeout=10)
            self.tunnel_manager.add_connection(conn_id,(reader,writer))
            asyncio.create_task(self.forward_remote_to_websocket(conn_id,reader))
        except Exception as e:
            logger.error(f"Failed to connect to {remote_ip}:{remote_port}: {e}")
            error_msg=pack_error(conn_id,str(e),self.key)
            try:
                self.send_queue.put_nowait(error_msg)
            except asyncio.QueueFull:
                logger.warning(f"Send queue full, dropping error message")

    async def forward_remote_to_websocket(self,conn_id,reader):
        try:
            while True:
                data=await reader.read(65536)
                if not data:
                    break
                message=pack_data(conn_id,data,self.key)
                try:
                    self.send_queue.put_nowait(message)
                except asyncio.QueueFull:
                    logger.warning(f"Send queue full, dropping data for {conn_id}")
                    break
        except Exception as e:
            logger.debug(f"Forward error for {conn_id}: {e}")
        finally:
            try:
                self.send_queue.put_nowait(pack_close(conn_id,0,self.key))
            except:
                pass
            self.tunnel_manager.remove_connection(conn_id)

    async def receive_messages(self):
        buffer=b""
        try:
            async for message in self.websocket:
                buffer+=message
                while len(buffer)>=9:
                    try:
                        msg_type,conn_id,payload,consumed=unpack_message(buffer,self.key)
                        buffer=buffer[consumed:]
                    except ValueError:
                        break
                    if msg_type==MSG_CONNECT:
                        remote_ip,remote_port=unpack_connect(payload)
                        await self.handle_connect(conn_id,remote_ip,remote_port)
                    elif msg_type==MSG_DATA:
                        await self.handle_data(conn_id,payload)
                    elif msg_type==MSG_CLOSE:
                        self.tunnel_manager.remove_connection(conn_id)
                    elif msg_type==MSG_ERROR:
                        logger.error(f"Server error for {conn_id}: {payload.decode()}")
                        self.tunnel_manager.remove_connection(conn_id)
                    elif msg_type==MSG_PONG:
                        pass
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Connection closed by server")
        except Exception as e:
            logger.error(f"Receive error: {e}",exc_info=True)

    async def handle_data(self,conn_id,payload):
        connection=self.tunnel_manager.get_connection(conn_id)
        if connection:
            reader,writer=connection
            try:
                writer.write(payload)
                await writer.drain()
            except Exception as e:
                logger.error(f"Error writing to remote connection {conn_id}: {e}")
                self.tunnel_manager.remove_connection(conn_id)

    async def ping_loop(self):
        while self.running:
            try:
                await asyncio.sleep(30)
                if self.websocket:
                    timestamp=int(time.time()*1000)
                    try:
                        self.send_queue.put_nowait(pack_ping(timestamp,self.key))
                    except asyncio.QueueFull:
                        logger.warning(f"Send queue full, skipping ping")
            except Exception as e:
                logger.debug(f"Ping error: {e}")
                break

    async def run(self):
        self.running=True
        while self.running and not self.shutdown_event.is_set():
            if await self.connect():
                try:
                    while not self.send_queue.empty():
                        try:
                            self.send_queue.get_nowait()
                        except:
                            break
                    sender_task=asyncio.create_task(self.sender_task())
                    ping_task=asyncio.create_task(self.ping_loop())
                    receive_task=asyncio.create_task(self.receive_messages())
                    shutdown_task=asyncio.create_task(self.shutdown_event.wait())
                    done,pending=await asyncio.wait({receive_task,shutdown_task},return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
                    await self.send_queue.put(None)
                    try:
                        await asyncio.wait_for(sender_task,timeout=2)
                    except:
                        sender_task.cancel()
                    ping_task.cancel()
                    if shutdown_task in done:
                        break
                except Exception as e:
                    logger.error(f"Runtime error: {e}")
                finally:
                    if self.websocket:
                        await self.websocket.close()
                    self.tunnel_manager.close_all()
            if self.running and not self.shutdown_event.is_set():
                logger.info(f"Reconnecting in {self.reconnect_delay} seconds...")
                try:
                    await asyncio.wait_for(self.shutdown_event.wait(),timeout=self.reconnect_delay)
                    break
                except asyncio.TimeoutError:
                    pass
                self.reconnect_delay=min(self.reconnect_delay*self.config.multiplier,self.config.max_delay)
        logger.info("Client shutting down")

    def stop(self):
        self.running=False
        self.shutdown_event.set()

def signal_handler(client,loop):
    logger.info("Received shutdown signal")
    loop.call_soon_threadsafe(client.stop)

def main():
    parser=argparse.ArgumentParser(description="GhostWire Client")
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
        config=ClientConfig(args.config)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)
    client=GhostWireClient(config)
    loop=asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGTERM,signal.SIGINT):
        loop.add_signal_handler(sig,lambda:signal_handler(client,loop))
    try:
        loop.run_until_complete(client.run())
    except KeyboardInterrupt:
        logger.info("Client stopped")
    finally:
        loop.close()

if __name__=="__main__":
    main()
