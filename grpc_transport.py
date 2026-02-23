#!/usr/bin/env python3.13
import asyncio
import logging
import time
import struct
import ssl
import os
from urllib.parse import urlparse
from grpclib.server import Server,Stream
from grpclib.client import Channel
from nanoid import generate
from protocol import *
from tunnel_grpc import TunnelBase,TunnelStub
from tunnel_pb2 import TunnelMessage

logger=logging.getLogger(__name__)

class GrpcTunnelServicer(TunnelBase):
    def __init__(self,server_instance):
        self.server=server_instance
        self.private_key=server_instance.private_key
        self.public_key=server_instance.public_key
        self.token=server_instance.config.token
        self.ping_timeout=server_instance.ping_timeout
    async def Stream(self,stream:Stream):
        peer="grpc-client"
        logger.info(f"gRPC client connected: {peer}")
        key=None
        last_ping_time=[time.time()]
        send_queue=asyncio.Queue(maxsize=512)
        control_queue=asyncio.Queue(maxsize=256)
        stop_event=asyncio.Event()
        sender_task=None
        ping_monitor=None
        authenticated=False
        try:
            init_msg=await asyncio.wait_for(stream.recv_message(),timeout=30)
            if not init_msg or init_msg.data!=b"INIT":
                logger.warning(f"Expected INIT message from {peer}")
                return
            pubkey_msg=pack_pubkey(self.public_key)
            await stream.send_message(TunnelMessage(data=pubkey_msg))
            auth_msg=await asyncio.wait_for(stream.recv_message(),timeout=30)
            if not auth_msg or not auth_msg.data:
                logger.warning(f"Empty auth from {peer}")
                return
            auth_data=auth_msg.data
            if len(auth_data)<9:
                logger.warning(f"Incomplete auth from {peer}")
                return
            msg_type,conn_id,encrypted_token,_=unpack_message(auth_data,None)
            if msg_type!=MSG_AUTH:
                logger.warning(f"Expected AUTH message from {peer}")
                return
            try:
                token_str,role,child_id=unpack_auth_payload(rsa_decrypt(self.private_key,encrypted_token))
            except Exception as e:
                logger.warning(f"Failed to decrypt token from {peer}: {e}")
                return
            if token_str!=self.token:
                logger.warning(f"Invalid token from {peer}")
                return
            client_pubkey_msg=await asyncio.wait_for(stream.recv_message(),timeout=10)
            if not client_pubkey_msg or not client_pubkey_msg.data:
                logger.warning(f"Empty client pubkey from {peer}")
                return
            client_pubkey_data=client_pubkey_msg.data
            if len(client_pubkey_data)<9:
                logger.warning(f"Invalid client public key message from {peer}")
                return
            try:
                key_msg_type,_,client_pubkey_bytes,_=unpack_message(client_pubkey_data,None)
                if key_msg_type!=MSG_PUBKEY:
                    logger.warning(f"Expected client public key message from {peer}")
                    return
                client_public_key=deserialize_public_key(client_pubkey_bytes)
            except Exception as e:
                logger.warning(f"Invalid client public key from {peer}: {e}")
                return
            key=generate(size=32).encode()
            session_msg=pack_session_key(key,client_public_key)
            await stream.send_message(TunnelMessage(data=session_msg))
            logger.info(f"gRPC client authenticated: {peer}")
            authenticated=True
            self.server.websocket=True
            self.server.key=key
            self.server.send_queue=send_queue
            self.server.control_queue=control_queue
            self.server.main_send_queue=send_queue
            self.server.main_control_queue=control_queue
            if not self.server.listeners:
                await self.server.start_listeners()
            sender_task=asyncio.create_task(self._sender_loop(stream,send_queue,control_queue,stop_event))
            ping_monitor=asyncio.create_task(self._ping_monitor(last_ping_time,stop_event,control_queue,key))
            buffer=bytearray()
            while not stop_event.is_set():
                msg=await stream.recv_message()
                if not msg or not msg.data:
                    break
                last_ping_time[0]=time.time()
                buffer.extend(msg.data)
                while len(buffer)>=9:
                    try:
                        msg_type,conn_id,payload,consumed=unpack_message(buffer,key)
                        del buffer[:consumed]
                    except ValueError:
                        break
                    if msg_type in (MSG_DATA,MSG_CLOSE,MSG_ERROR,MSG_INFO):
                        await self.server.route_message(msg_type,conn_id,payload)
                    elif msg_type==MSG_PING:
                        timestamp=struct.unpack("!Q",payload)[0]
                        try:
                            control_queue.put_nowait(pack_pong(timestamp,key))
                        except asyncio.QueueFull:
                            logger.warning("gRPC control queue full, dropping PONG")
                    elif msg_type==MSG_PONG:
                        pass
        except asyncio.TimeoutError:
            logger.warning(f"gRPC client {peer} authentication timeout")
        except Exception as e:
            logger.error(f"Error handling gRPC client {peer}: {e}",exc_info=True)
        finally:
            stop_event.set()
            if sender_task and not sender_task.done():
                sender_task.cancel()
            if ping_monitor and not ping_monitor.done():
                ping_monitor.cancel()
            if authenticated:
                self.server.websocket=None
                self.server.key=None
                self.server.send_queue=None
                self.server.control_queue=None
                self.server.main_send_queue=None
                self.server.main_control_queue=None
                self.server.client_version=None
                self.server.tunnel_manager.close_all()
            logger.info(f"gRPC client disconnected: {peer}")
    async def _sender_loop(self,stream,send_queue,control_queue,stop_event):
        try:
            while not stop_event.is_set() or not send_queue.empty() or not control_queue.empty():
                batch=bytearray()
                for _ in range(64):
                    try:
                        batch.extend(control_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                while len(batch)<1048576:
                    try:
                        batch.extend(send_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                if not batch:
                    control_get=asyncio.create_task(control_queue.get())
                    data_get=asyncio.create_task(send_queue.get())
                    stop_get=asyncio.create_task(stop_event.wait())
                    done,pending=await asyncio.wait({control_get,data_get,stop_get},return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
                    if pending:
                        await asyncio.gather(*pending,return_exceptions=True)
                    if stop_get in done and control_get not in done and data_get not in done:
                        break
                    if control_get in done:
                        batch.extend(control_get.result())
                    if data_get in done:
                        batch.extend(data_get.result())
                    while len(batch)<1048576:
                        try:
                            batch.extend(control_queue.get_nowait())
                        except asyncio.QueueEmpty:
                            break
                    while len(batch)<1048576:
                        try:
                            batch.extend(send_queue.get_nowait())
                        except asyncio.QueueEmpty:
                            break
                if batch:
                    await stream.send_message(TunnelMessage(data=bytes(batch)))
        except Exception as e:
            logger.debug(f"gRPC sender task error: {e}")
        finally:
            logger.debug("gRPC sender task stopped")
    async def _ping_monitor(self,last_ping_time,stop_event,control_queue,key):
        interval=max(2,self.ping_timeout//2)
        try:
            while not stop_event.is_set():
                await asyncio.sleep(interval)
                if time.time()-last_ping_time[0]>self.ping_timeout:
                    logger.warning("gRPC client ping timeout")
                    stop_event.set()
                    break
        except asyncio.CancelledError:
            pass

async def start_grpc_server(server_instance):
    servicer=GrpcTunnelServicer(server_instance)
    ssl_context=None
    if hasattr(server_instance.config,'ssl_cert') and hasattr(server_instance.config,'ssl_key'):
        if server_instance.config.ssl_cert and server_instance.config.ssl_key:
            ssl_context=ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(server_instance.config.ssl_cert,server_instance.config.ssl_key)
            logger.info(f"gRPC SSL enabled with certificate: {server_instance.config.ssl_cert}")
    grpc_server=Server([servicer])
    await grpc_server.start(server_instance.config.listen_host,server_instance.config.listen_port,ssl=ssl_context)
    protocol="gRPCs" if ssl_context else "gRPC"
    logger.info(f"gRPC server listening on {protocol}://{server_instance.config.listen_host}:{server_instance.config.listen_port}")
    await server_instance.shutdown_event.wait()
    grpc_server.close()
    await grpc_server.wait_closed()
    logger.info("gRPC server stopped")

class GrpcClientTransport:
    def __init__(self,server_url,token):
        self.server_url=server_url.replace("wss://","https://").replace("ws://","http://")
        self.token=token
        self.channel=None
        self.stub=None
        self.stream=None
        self.key=None
        self.connected=False
        self.stop_event=asyncio.Event()
        self.send_queue=asyncio.Queue(maxsize=512)
        self.recv_queue=asyncio.Queue(maxsize=512)
        self.sender_task=None
        self.receiver_task=None
    async def connect(self):
        try:
            parsed=urlparse(self.server_url)
            host=parsed.hostname
            port=parsed.port or (443 if parsed.scheme=="https" else 80)
            use_ssl=parsed.scheme=="https"
            logger.info(f"Connecting to gRPC server {host}:{port} (ssl={use_ssl})...")
            if use_ssl:
                ssl_context=ssl.create_default_context()
                self.channel=Channel(host,port,ssl=ssl_context)
            else:
                self.channel=Channel(host,port)
            self.stub=TunnelStub(self.channel)
            self.stream=self.stub.Stream.open()
            await self.stream.__aenter__()
            await self.stream.send_request()
            logger.debug("Sending init message...")
            await self.stream.send_message(TunnelMessage(data=b"INIT"))
            logger.debug("Waiting for server public key...")
            pubkey_msg=await asyncio.wait_for(self.stream.recv_message(),timeout=30)
            if not pubkey_msg or not pubkey_msg.data:
                raise ValueError("Empty public key from server")
            pubkey_data=pubkey_msg.data
            if len(pubkey_data)<9:
                raise ValueError("Invalid public key message")
            msg_type,_,pubkey_bytes,_=unpack_message(pubkey_data,None)
            if msg_type!=MSG_PUBKEY:
                raise ValueError("Expected public key from server")
            server_public_key=deserialize_public_key(pubkey_bytes)
            logger.debug("Performing authentication...")
            client_private_key,client_public_key=generate_rsa_keypair()
            auth_msg=pack_auth_message(self.token,server_public_key,role="main")
            await self.stream.send_message(TunnelMessage(data=auth_msg))
            pubkey_msg_data=pack_pubkey(client_public_key)
            await self.stream.send_message(TunnelMessage(data=pubkey_msg_data))
            logger.debug("Waiting for session key...")
            session_msg=await asyncio.wait_for(self.stream.recv_message(),timeout=30)
            if not session_msg or not session_msg.data:
                raise ValueError("Empty session key from server")
            session_data=session_msg.data
            if len(session_data)<9:
                raise ValueError("Invalid session key message")
            session_type,_,session_payload,_=unpack_message(session_data,None)
            if session_type!=MSG_SESSION_KEY:
                raise ValueError("Expected session key from server")
            self.key=unpack_session_key(session_payload,client_private_key)
            self.connected=True
            self.sender_task=asyncio.create_task(self._sender_loop())
            self.receiver_task=asyncio.create_task(self._receiver_loop())
            logger.info("gRPC connected and authenticated")
            return True
        except Exception as e:
            logger.error(f"gRPC connection failed: {e}")
            await self.close()
            return False
    async def _sender_loop(self):
        try:
            while not self.stop_event.is_set():
                msg=await self.send_queue.get()
                if msg is None:
                    break
                await self.stream.send_message(TunnelMessage(data=msg))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"gRPC sender error: {e}")
            self.stop_event.set()
    async def _receiver_loop(self):
        try:
            while not self.stop_event.is_set():
                msg=await self.stream.recv_message()
                if not msg or not msg.data:
                    break
                await self.recv_queue.put(msg.data)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"gRPC receiver error: {e}")
            await self.recv_queue.put(None)
            self.stop_event.set()
    async def send(self,msg):
        await self.send_queue.put(msg)
    async def recv(self):
        data=await self.recv_queue.get()
        if data is None:
            raise EOFError("Connection closed")
        return data
    async def close(self):
        self.stop_event.set()
        if self.send_queue:
            await self.send_queue.put(None)
        if self.sender_task and not self.sender_task.done():
            self.sender_task.cancel()
        if self.receiver_task and not self.receiver_task.done():
            self.receiver_task.cancel()
        if self.stream:
            try:
                await self.stream.send_message(TunnelMessage(data=b""))
            except:
                pass
        if self.channel:
            try:
                self.channel.close()
            except:
                pass
        self.connected=False
