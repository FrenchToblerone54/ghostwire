#!/usr/bin/env python3.13
import asyncio
import logging
import time
import struct
from http import HTTPStatus
import httpx
from protocol import *
from crypto import generate_rsa_keypair,serialize_public_key,deserialize_public_key,encrypt_token,decrypt_token,derive_key

logger=logging.getLogger(__name__)

class HTTP2ServerHandler:
    def __init__(self,server_instance):
        self.server=server_instance
        self.private_key=server_instance.private_key
        self.public_key=server_instance.public_key
        self.token=server_instance.config.token
        self.tunnel_manager=server_instance.tunnel_manager
        self.ping_timeout=server_instance.ping_timeout
    async def handle_tunnel(self,reader,writer):
        peer=writer.get_extra_info('peername')
        logger.info(f"HTTP/2 client connected: {peer}")
        key=None
        last_ping_time=[time.time()]
        send_queue=asyncio.Queue(maxsize=512)
        conn_write_queues={}
        stop_event=asyncio.Event()
        receiver_task=None
        sender_task=None
        ping_task=None
        try:
            pubkey_msg=pack_pubkey(self.public_key)
            writer.write(struct.pack("!I",len(pubkey_msg))+pubkey_msg)
            await writer.drain()
            auth_len_data=await asyncio.wait_for(reader.readexactly(4),timeout=30)
            auth_len=struct.unpack("!I",auth_len_data)[0]
            if auth_len>1048576:
                raise ValueError("Auth message too large")
            auth_data=await asyncio.wait_for(reader.readexactly(auth_len),timeout=30)
            auth_type,_,encrypted_token,_=unpack_message(auth_data,None)
            if auth_type!=MSG_AUTH:
                raise ValueError("Expected auth message")
            client_token=decrypt_token(encrypted_token,self.private_key)
            if client_token!=self.token:
                raise ValueError("Invalid token")
            pubkey_len_data=await asyncio.wait_for(reader.readexactly(4),timeout=10)
            pubkey_len=struct.unpack("!I",pubkey_len_data)[0]
            if pubkey_len>1048576:
                raise ValueError("Pubkey message too large")
            pubkey_data=await asyncio.wait_for(reader.readexactly(pubkey_len),timeout=10)
            pubkey_type,_,client_pubkey,_=unpack_message(pubkey_data,None)
            if pubkey_type!=MSG_PUBKEY:
                raise ValueError("Expected public key")
            client_public_key=deserialize_public_key(client_pubkey)
            key=derive_key(self.token)
            encrypted_key=encrypt_token(key,client_public_key)
            session_msg=pack_session_key(encrypted_key)
            writer.write(struct.pack("!I",len(session_msg))+session_msg)
            await writer.drain()
            logger.info(f"HTTP/2 client authenticated: {peer}")
            receiver_task=asyncio.create_task(self._receiver_loop(reader,send_queue,conn_write_queues,last_ping_time,stop_event,key))
            sender_task=asyncio.create_task(self._sender_loop(writer,send_queue,stop_event,key))
            ping_task=asyncio.create_task(self._ping_monitor(last_ping_time,stop_event))
            await stop_event.wait()
        except asyncio.CancelledError:
            logger.info(f"HTTP/2 client cancelled: {peer}")
        except Exception as e:
            logger.error(f"HTTP/2 client error: {e}")
        finally:
            stop_event.set()
            if receiver_task and not receiver_task.done():
                receiver_task.cancel()
            if sender_task and not sender_task.done():
                sender_task.cancel()
            if ping_task and not ping_task.done():
                ping_task.cancel()
            for queue in conn_write_queues.values():
                try:
                    queue.put_nowait(None)
                except:
                    pass
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass
            logger.info(f"HTTP/2 client disconnected: {peer}")
    async def _receiver_loop(self,reader,send_queue,conn_write_queues,last_ping_time,stop_event,key):
        try:
            while not stop_event.is_set():
                msg_len_data=await reader.readexactly(4)
                msg_len=struct.unpack("!I",msg_len_data)[0]
                if msg_len>16777216:
                    raise ValueError("Message too large")
                msg_data=await reader.readexactly(msg_len)
                msg_type,conn_id,payload,_=unpack_message(msg_data,key)
                if msg_type==MSG_INFO:
                    self.server.client_version=payload.decode()
                    logger.info(f"Client version: {self.server.client_version}")
                elif msg_type==MSG_PING:
                    pong_msg=pack_pong(payload.decode(),key)
                    await send_queue.put(pong_msg)
                elif msg_type==MSG_PONG:
                    last_ping_time[0]=time.time()
                elif msg_type==MSG_NEW_CONNECTION:
                    parts=payload.decode().split(":")
                    remote_ip=parts[0]
                    remote_port=int(parts[1])
                    queue=asyncio.Queue(maxsize=512)
                    conn_write_queues[conn_id]=queue
                    asyncio.create_task(self._connection_writer(conn_id,queue,send_queue,key))
                    asyncio.create_task(self.tunnel_manager.handle_new_connection(conn_id,remote_ip,remote_port,queue,None))
                elif msg_type==MSG_DATA:
                    await self.tunnel_manager.send_to_connection(conn_id,payload)
                elif msg_type==MSG_CONNECTION_CLOSED:
                    await self.tunnel_manager.close_connection(conn_id)
                    conn_write_queues.pop(conn_id,None)
        except asyncio.IncompleteReadError:
            logger.info("Client disconnected")
            stop_event.set()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Receiver loop error: {e}")
            stop_event.set()
    async def _sender_loop(self,writer,send_queue,stop_event,key):
        try:
            while not stop_event.is_set():
                msg=await send_queue.get()
                if msg is None:
                    break
                writer.write(struct.pack("!I",len(msg))+msg)
                await writer.drain()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Sender loop error: {e}")
            stop_event.set()
    async def _ping_monitor(self,last_ping_time,stop_event):
        interval=max(2,self.ping_timeout//2)
        try:
            while not stop_event.is_set():
                await asyncio.sleep(interval)
                if time.time()-last_ping_time[0]>self.ping_timeout:
                    logger.warning("Client ping timeout")
                    stop_event.set()
                    break
        except asyncio.CancelledError:
            pass
    async def _connection_writer(self,conn_id,queue,send_queue,key):
        try:
            while True:
                payload=await queue.get()
                if payload is None:
                    queue.task_done()
                    close_msg=pack_connection_closed(conn_id,key)
                    await send_queue.put(close_msg)
                    break
                data_msg=pack_data(conn_id,payload,key)
                await send_queue.put(data_msg)
                queue.task_done()
        except asyncio.CancelledError:
            pass

async def start_http2_server(server_instance):
    handler=HTTP2ServerHandler(server_instance)
    server=await asyncio.start_server(handler.handle_tunnel,server_instance.config.listen_host,server_instance.config.listen_port,backlog=server_instance.config.listen_backlog)
    addr=server.sockets[0].getsockname()
    logger.info(f"HTTP/2 server listening on {addr[0]}:{addr[1]}")
    async with server:
        await server_instance.shutdown_event.wait()
    logger.info("HTTP/2 server stopped")

class HTTP2ClientTransport:
    def __init__(self,server_url,token):
        self.server_url=server_url.replace("wss://","https://").replace("ws://","http://")
        self.token=token
        self.client=None
        self.response=None
        self.send_queue=asyncio.Queue(maxsize=512)
        self.recv_queue=asyncio.Queue(maxsize=512)
        self.key=None
        self.connected=False
        self.sender_task=None
        self.receiver_task=None
        self.stop_event=asyncio.Event()
    async def connect(self):
        try:
            self.client=httpx.AsyncClient(http2=True,timeout=httpx.Timeout(None))
            async def request_content():
                async def send_stream():
                    pubkey_msg=pack_pubkey(None)
                    yield struct.pack("!I",len(pubkey_msg))+pubkey_msg
                    while not self.stop_event.is_set():
                        msg=await self.send_queue.get()
                        if msg is None:
                            break
                        yield struct.pack("!I",len(msg))+msg
                async for chunk in send_stream():
                    yield chunk
            self.response=await self.client.post(self.server_url,content=request_content(),headers={"Content-Type":"application/octet-stream"})
            self.receiver_task=asyncio.create_task(self._receiver_loop())
            server_msg_len_data=await self._read_exact(4)
            server_msg_len=struct.unpack("!I",server_msg_len_data)[0]
            server_msg_data=await self._read_exact(server_msg_len)
            msg_type,_,server_pubkey,_=unpack_message(server_msg_data,None)
            if msg_type!=MSG_PUBKEY:
                raise ValueError("Expected public key from server")
            server_public_key=deserialize_public_key(server_pubkey)
            client_private_key,client_public_key=generate_rsa_keypair()
            auth_msg=pack_auth_message(self.token,server_public_key,role="main")
            await self.send_queue.put(auth_msg)
            pubkey_msg=pack_pubkey(client_public_key)
            await self.send_queue.put(pubkey_msg)
            session_msg_len_data=await self._read_exact(4)
            session_msg_len=struct.unpack("!I",session_msg_len_data)[0]
            session_msg_data=await self._read_exact(session_msg_len)
            session_type,_,session_payload,_=unpack_message(session_msg_data,None)
            if session_type!=MSG_SESSION_KEY:
                raise ValueError("Expected session key from server")
            self.key=unpack_session_key(session_payload,client_private_key)
            self.connected=True
            logger.info("HTTP/2 connected and authenticated")
            return True
        except Exception as e:
            logger.error(f"HTTP/2 connection failed: {e}")
            await self.close()
            return False
    async def _read_exact(self,n):
        data=b""
        async for chunk in self.response.aiter_bytes():
            data+=chunk
            if len(data)>=n:
                result=data[:n]
                remaining=data[n:]
                if remaining:
                    await self.recv_queue.put(remaining)
                return result
        raise EOFError("Connection closed")
    async def _receiver_loop(self):
        try:
            buffer=b""
            async for chunk in self.response.aiter_bytes():
                buffer+=chunk
                while len(buffer)>=4:
                    msg_len=struct.unpack("!I",buffer[:4])[0]
                    if len(buffer)<4+msg_len:
                        break
                    msg_data=buffer[4:4+msg_len]
                    buffer=buffer[4+msg_len:]
                    await self.recv_queue.put(msg_data)
        except Exception as e:
            logger.error(f"Receiver error: {e}")
            self.stop_event.set()
    async def send(self,msg):
        await self.send_queue.put(msg)
    async def recv(self):
        return await self.recv_queue.get()
    async def close(self):
        self.stop_event.set()
        await self.send_queue.put(None)
        if self.sender_task and not self.sender_task.done():
            self.sender_task.cancel()
        if self.receiver_task and not self.receiver_task.done():
            self.receiver_task.cancel()
        if self.response:
            await self.response.aclose()
        if self.client:
            await self.client.aclose()
        self.connected=False
