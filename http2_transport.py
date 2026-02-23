#!/usr/bin/env python3.13
import asyncio
import logging
import time
import struct
import ssl
from urllib.parse import urlparse
from h2.connection import H2Connection
from h2.events import RequestReceived,DataReceived,StreamEnded,WindowUpdated,StreamReset,ConnectionTerminated,RemoteSettingsChanged
from h2.config import H2Configuration
from nanoid import generate
from protocol import *

logger=logging.getLogger(__name__)

MSG_NEW_CONNECTION=MSG_CONNECT
MSG_CONNECTION_CLOSED=MSG_CLOSE

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
        logger.info(f"Client connected: {peer}")
        preface=await reader.read(24)
        if preface.startswith(b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"):
            logger.info(f"HTTP/2 protocol detected from {peer}")
            await self._handle_http2(reader,writer,preface,peer)
        elif preface.startswith(b"GET") or preface.startswith(b"POST"):
            logger.info(f"HTTP/1.1 protocol detected from {peer}")
            await self._handle_http11(reader,writer,preface,peer)
        else:
            logger.error(f"Unknown protocol from {peer}: {preface[:20]}")
            writer.close()
            await writer.wait_closed()
    async def _handle_http2(self,reader,writer,preface,peer):
        config=H2Configuration(client_side=False)
        conn=H2Connection(config=config)
        conn_lock=asyncio.Lock()
        window_event=asyncio.Event()
        window_event.set()
        conn.initiate_connection()
        async with conn_lock:
            conn.receive_data(preface)
        writer.write(conn.data_to_send())
        await writer.drain()
        key=None
        last_ping_time=[time.time()]
        send_queue=asyncio.Queue(maxsize=512)
        stop_event=asyncio.Event()
        stream_id=None
        sender_task=None
        ping_task=None
        auth_buffer=b""
        msg_buffer=b""
        authenticated=False
        try:
            while not stop_event.is_set():
                data=await reader.read(65536)
                if not data:
                    break
                async with conn_lock:
                    events=conn.receive_data(data)
                for event in events:
                    if isinstance(event,RequestReceived):
                        stream_id=event.stream_id
                        async with conn_lock:
                            conn.send_headers(stream_id,[(':status','200'),('content-type','application/octet-stream')],end_stream=False)
                        await self._flush_outbound(conn,writer,conn_lock)
                        pubkey_msg=pack_pubkey(self.public_key)
                        frame_data=struct.pack("!I",len(pubkey_msg))+pubkey_msg
                        await self._send_framed_bytes(stream_id,frame_data,conn,writer,conn_lock,window_event,stop_event)
                    elif isinstance(event,DataReceived):
                        async with conn_lock:
                            conn.acknowledge_received_data(event.flow_controlled_length,event.stream_id)
                        if not authenticated:
                            auth_buffer+=event.data
                            while len(auth_buffer)>=4:
                                msg_len=struct.unpack("!I",auth_buffer[:4])[0]
                                if len(auth_buffer)<4+msg_len:
                                    break
                                msg_data=auth_buffer[4:4+msg_len]
                                auth_buffer=auth_buffer[4+msg_len:]
                                msg_type,_,payload,_=unpack_message(msg_data,None)
                                if msg_type==MSG_AUTH:
                                    client_token=rsa_decrypt(self.private_key,payload)
                                    token_str,_,_=unpack_auth_payload(client_token)
                                    if token_str!=self.token:
                                        raise ValueError("Invalid token")
                                elif msg_type==MSG_PUBKEY:
                                    client_public_key=deserialize_public_key(payload)
                                    key=generate(size=32).encode()
                                    session_msg=pack_session_key(key,client_public_key)
                                    frame_data=struct.pack("!I",len(session_msg))+session_msg
                                    await self._send_framed_bytes(stream_id,frame_data,conn,writer,conn_lock,window_event,stop_event)
                                    logger.info(f"HTTP/2 client authenticated: {peer}")
                                    authenticated=True
                                    self.server.websocket=True
                                    self.server.key=key
                                    self.server.send_queue=send_queue
                                    self.server.control_queue=send_queue
                                    if not self.server.listeners:
                                        await self.server.start_listeners()
                                    sender_task=asyncio.create_task(self._sender_loop(stream_id,conn,writer,send_queue,stop_event,conn_lock,window_event))
                                    ping_task=asyncio.create_task(self._ping_monitor(last_ping_time,stop_event,send_queue,key))
                                    msg_buffer=auth_buffer
                                    auth_buffer=b""
                                    break
                        else:
                            last_ping_time[0]=time.time()
                            msg_buffer+=event.data
                            while len(msg_buffer)>=4:
                                msg_len=struct.unpack("!I",msg_buffer[:4])[0]
                                if len(msg_buffer)<4+msg_len:
                                    break
                                msg_data=msg_buffer[4:4+msg_len]
                                msg_buffer=msg_buffer[4+msg_len:]
                                msg_type,conn_id,payload,_=unpack_message(msg_data,key)
                                if msg_type==MSG_INFO:
                                    self.server.client_version=payload.decode()
                                    logger.info(f"Client version: {self.server.client_version}")
                                elif msg_type==MSG_PING:
                                    pong_msg=pack_pong(struct.unpack("!Q",payload)[0],key)
                                    try:
                                        send_queue.put_nowait(pong_msg)
                                    except asyncio.QueueFull:
                                        logger.warning("HTTP/2 send queue full, dropping PONG")
                                elif msg_type==MSG_PONG:
                                    last_ping_time[0]=time.time()
                                elif msg_type==MSG_CONNECT:
                                    remote_ip,remote_port=unpack_connect(payload)
                                    logger.debug(f"CONNECT from client: {conn_id} -> {remote_ip}:{remote_port}")
                                elif msg_type==MSG_DATA:
                                    await self.server.handle_data(conn_id,payload)
                                elif msg_type==MSG_CLOSE:
                                    await self.server.handle_close(conn_id)
                    elif isinstance(event,WindowUpdated):
                        window_event.set()
                    elif isinstance(event,RemoteSettingsChanged):
                        window_event.set()
                    elif isinstance(event,StreamEnded):
                        logger.info("Stream ended by client")
                        stop_event.set()
                    elif isinstance(event,StreamReset):
                        logger.info("Stream reset by client")
                        stop_event.set()
                    elif isinstance(event,ConnectionTerminated):
                        logger.info("Connection terminated")
                        stop_event.set()
                await self._flush_outbound(conn,writer,conn_lock)
        except asyncio.CancelledError:
            logger.info(f"HTTP/2 client cancelled: {peer}")
        except Exception as e:
            logger.error(f"HTTP/2 client error: {e}")
        finally:
            stop_event.set()
            if sender_task and not sender_task.done():
                sender_task.cancel()
            if ping_task and not ping_task.done():
                ping_task.cancel()
            if authenticated:
                self.server.websocket=None
                self.server.key=None
                self.server.send_queue=None
                self.server.control_queue=None
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass
            logger.info(f"HTTP/2 client disconnected: {peer}")
    async def _handle_http11(self,reader,writer,preface,peer):
        key=None
        last_ping_time=[time.time()]
        send_queue=asyncio.Queue(maxsize=512)
        conn_write_queues={}
        stop_event=asyncio.Event()
        sender_task=None
        ping_task=None
        try:
            while b"\r\n\r\n" not in preface:
                chunk=await reader.read(1024)
                if not chunk:
                    return
                preface+=chunk
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nTransfer-Encoding: chunked\r\n\r\n")
            await writer.drain()
            pubkey_msg=pack_pubkey(self.public_key)
            writer.write(struct.pack("!I",len(pubkey_msg))+pubkey_msg)
            await writer.drain()
            auth_len_data=await asyncio.wait_for(reader.readexactly(4),timeout=30)
            auth_len=struct.unpack("!I",auth_len_data)[0]
            auth_data=await asyncio.wait_for(reader.readexactly(auth_len),timeout=30)
            auth_type,_,encrypted_token,_=unpack_message(auth_data,None)
            if auth_type!=MSG_AUTH:
                raise ValueError("Expected auth message")
            client_token=rsa_decrypt(self.private_key,encrypted_token)
            token_str,_,_=unpack_auth_payload(client_token)
            if token_str!=self.token:
                raise ValueError("Invalid token")
            pubkey_len_data=await asyncio.wait_for(reader.readexactly(4),timeout=30)
            pubkey_len=struct.unpack("!I",pubkey_len_data)[0]
            pubkey_data=await asyncio.wait_for(reader.readexactly(pubkey_len),timeout=30)
            pubkey_type,_,client_pubkey,_=unpack_message(pubkey_data,None)
            if pubkey_type!=MSG_PUBKEY:
                raise ValueError("Expected public key")
            client_public_key=deserialize_public_key(client_pubkey)
            key=generate(size=32).encode()
            session_msg=pack_session_key(key,client_public_key)
            writer.write(struct.pack("!I",len(session_msg))+session_msg)
            await writer.drain()
            logger.info(f"HTTP/1.1 client authenticated: {peer}")
            self.server.websocket=True
            self.server.key=key
            self.server.send_queue=send_queue
            self.server.control_queue=send_queue
            if not self.server.listeners:
                await self.server.start_listeners()
            sender_task=asyncio.create_task(self._http11_sender_loop(writer,send_queue,stop_event))
            ping_task=asyncio.create_task(self._ping_monitor(last_ping_time,stop_event,send_queue,key))
            while not stop_event.is_set():
                msg_len_data=await reader.readexactly(4)
                msg_len=struct.unpack("!I",msg_len_data)[0]
                msg_data=await reader.readexactly(msg_len)
                msg_type,conn_id,payload,_=unpack_message(msg_data,key)
                if msg_type==MSG_INFO:
                    self.server.client_version=payload.decode()
                    logger.info(f"Client version: {self.server.client_version}")
                elif msg_type==MSG_PING:
                    pong_msg=pack_pong(struct.unpack("!Q",payload)[0],key)
                    await send_queue.put(pong_msg)
                elif msg_type==MSG_PONG:
                    last_ping_time[0]=time.time()
                elif msg_type==MSG_CONNECT:
                    remote_ip,remote_port=unpack_connect(payload)
                    logger.debug(f"CONNECT from client: {conn_id} -> {remote_ip}:{remote_port}")
                elif msg_type==MSG_DATA:
                    await self.server.handle_data(conn_id,payload)
                elif msg_type==MSG_CLOSE:
                    await self.server.handle_close(conn_id)
        except asyncio.CancelledError:
            logger.info(f"HTTP/1.1 client cancelled: {peer}")
        except Exception as e:
            logger.error(f"HTTP/1.1 client error: {e}")
        finally:
            stop_event.set()
            if sender_task and not sender_task.done():
                sender_task.cancel()
            if ping_task and not ping_task.done():
                ping_task.cancel()
            self.server.websocket=None
            self.server.key=None
            self.server.send_queue=None
            self.server.control_queue=None
            try:
                writer.close()
                await writer.wait_closed()
            except:
                pass
            logger.info(f"HTTP/1.1 client disconnected: {peer}")
    async def _http11_sender_loop(self,writer,send_queue,stop_event):
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
            logger.error(f"HTTP/1.1 sender error: {e}")
            stop_event.set()
    async def _flush_outbound(self,conn,writer,conn_lock):
        async with conn_lock:
            outbound=conn.data_to_send()
        if outbound:
            writer.write(outbound)
            await writer.drain()
    async def _send_framed_bytes(self,stream_id,payload,conn,writer,conn_lock,window_event,stop_event):
        offset=0
        while offset<len(payload) and not stop_event.is_set():
            async with conn_lock:
                stream_window=conn.local_flow_control_window(stream_id)
                conn_window=conn.outbound_flow_control_window
                max_frame=conn.max_outbound_frame_size
                chunk_size=min(len(payload)-offset,stream_window,conn_window,max_frame)
                if chunk_size>0:
                    conn.send_data(stream_id,payload[offset:offset+chunk_size],end_stream=False)
                    outbound=conn.data_to_send()
                else:
                    outbound=b""
            if chunk_size>0:
                writer.write(outbound)
                await writer.drain()
                offset+=chunk_size
                continue
            window_event.clear()
            try:
                await asyncio.wait_for(window_event.wait(),timeout=5)
            except asyncio.TimeoutError:
                if stop_event.is_set():
                    break
    async def _sender_loop(self,stream_id,conn,writer,send_queue,stop_event,conn_lock,window_event):
        try:
            while not stop_event.is_set():
                msg=await send_queue.get()
                if msg is None:
                    break
                frame_data=struct.pack("!I",len(msg))+msg
                await self._send_framed_bytes(stream_id,frame_data,conn,writer,conn_lock,window_event,stop_event)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Sender loop error: {e}")
            stop_event.set()
    async def _ping_monitor(self,last_ping_time,stop_event,send_queue,key):
        interval=max(2,self.ping_timeout//2)
        try:
            while not stop_event.is_set():
                await asyncio.sleep(interval)
                ping_msg=pack_ping(int(time.time()*1000),key)
                try:
                    send_queue.put_nowait(ping_msg)
                except asyncio.QueueFull:
                    logger.warning("HTTP/2 send queue full, dropping PING")
                if time.time()-last_ping_time[0]>self.ping_timeout:
                    logger.warning("Client ping timeout")
                    stop_event.set()
                    break
        except asyncio.CancelledError:
            pass

async def start_http2_server(server_instance):
    handler=HTTP2ServerHandler(server_instance)
    ssl_context=None
    if hasattr(server_instance.config,'ssl_cert') and hasattr(server_instance.config,'ssl_key'):
        if server_instance.config.ssl_cert and server_instance.config.ssl_key:
            ssl_context=ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(server_instance.config.ssl_cert,server_instance.config.ssl_key)
            logger.info(f"SSL enabled with certificate: {server_instance.config.ssl_cert}")
    server=await asyncio.start_server(handler.handle_tunnel,server_instance.config.listen_host,server_instance.config.listen_port,ssl=ssl_context,backlog=server_instance.config.listen_backlog)
    addr=server.sockets[0].getsockname()
    protocol="HTTPS" if ssl_context else "HTTP"
    logger.info(f"HTTP/2 server listening on {protocol}://{addr[0]}:{addr[1]}")
    async with server:
        await server_instance.shutdown_event.wait()
    logger.info("HTTP/2 server stopped")

class HTTP2ClientTransport:
    def __init__(self,server_url,token):
        self.server_url=server_url.replace("wss://","https://").replace("ws://","http://")
        self.token=token
        self.reader=None
        self.writer=None
        self.conn=None
        self.stream_id=None
        self.send_queue=asyncio.Queue(maxsize=512)
        self.recv_queue=asyncio.Queue(maxsize=512)
        self.key=None
        self.connected=False
        self.sender_task=None
        self.receiver_task=None
        self.stop_event=asyncio.Event()
        self._recv_buffer=b""
        self.conn_lock=asyncio.Lock()
        self.window_event=asyncio.Event()
        self.window_event.set()
    async def connect(self):
        try:
            parsed=urlparse(self.server_url)
            host=parsed.hostname
            port=parsed.port or (443 if parsed.scheme=="https" else 80)
            use_ssl=parsed.scheme=="https"
            logger.info(f"Connecting to {host}:{port} (ssl={use_ssl})...")
            if use_ssl:
                ssl_context=ssl.create_default_context()
                self.reader,self.writer=await asyncio.wait_for(asyncio.open_connection(host,port,ssl=ssl_context,server_hostname=host),timeout=30)
            else:
                self.reader,self.writer=await asyncio.wait_for(asyncio.open_connection(host,port),timeout=30)
            config=H2Configuration(client_side=True)
            self.conn=H2Connection(config=config)
            async with self.conn_lock:
                self.conn.initiate_connection()
                outbound=self.conn.data_to_send()
                self.stream_id=self.conn.get_next_available_stream_id()
            self.writer.write(outbound)
            await self.writer.drain()
            headers=[(':method','POST'),(':scheme',parsed.scheme),(':authority',f"{host}:{port}"),(':path',parsed.path or '/'),('content-type','application/octet-stream')]
            async with self.conn_lock:
                self.conn.send_headers(self.stream_id,headers,end_stream=False)
                outbound=self.conn.data_to_send()
            self.writer.write(outbound)
            await self.writer.drain()
            self.receiver_task=asyncio.create_task(self._receiver_loop())
            logger.debug("Waiting for server public key...")
            server_msg_len_data=await asyncio.wait_for(self._read_exact(4),timeout=30)
            server_msg_len=struct.unpack("!I",server_msg_len_data)[0]
            server_msg_data=await asyncio.wait_for(self._read_exact(server_msg_len),timeout=30)
            msg_type,_,server_pubkey,_=unpack_message(server_msg_data,None)
            if msg_type!=MSG_PUBKEY:
                raise ValueError("Expected public key from server")
            server_public_key=deserialize_public_key(server_pubkey)
            logger.debug("Performing authentication...")
            client_private_key,client_public_key=generate_rsa_keypair()
            auth_msg=pack_auth_message(self.token,server_public_key,role="main")
            frame_data=struct.pack("!I",len(auth_msg))+auth_msg
            await self._send_framed_bytes(frame_data)
            pubkey_msg=pack_pubkey(client_public_key)
            frame_data=struct.pack("!I",len(pubkey_msg))+pubkey_msg
            await self._send_framed_bytes(frame_data)
            logger.debug("Waiting for session key...")
            session_msg_len_data=await asyncio.wait_for(self._read_exact(4),timeout=30)
            session_msg_len=struct.unpack("!I",session_msg_len_data)[0]
            session_msg_data=await asyncio.wait_for(self._read_exact(session_msg_len),timeout=30)
            session_type,_,session_payload,_=unpack_message(session_msg_data,None)
            if session_type!=MSG_SESSION_KEY:
                raise ValueError("Expected session key from server")
            self.key=unpack_session_key(session_payload,client_private_key)
            self.connected=True
            self.sender_task=asyncio.create_task(self._sender_loop())
            logger.info("HTTP/2 connected and authenticated")
            return True
        except Exception as e:
            logger.error(f"HTTP/2 connection failed: {e}")
            await self.close()
            return False
    async def _read_exact(self,n):
        while len(self._recv_buffer)<n:
            msg=await self.recv_queue.get()
            if msg is None:
                raise EOFError("Connection closed")
            self._recv_buffer+=msg
        result=self._recv_buffer[:n]
        self._recv_buffer=self._recv_buffer[n:]
        return result
    async def _flush_outbound(self):
        async with self.conn_lock:
            outbound=self.conn.data_to_send() if self.conn else b""
        if outbound:
            self.writer.write(outbound)
            await self.writer.drain()
    async def _send_framed_bytes(self,payload):
        offset=0
        while offset<len(payload) and not self.stop_event.is_set():
            async with self.conn_lock:
                stream_window=self.conn.local_flow_control_window(self.stream_id)
                conn_window=self.conn.outbound_flow_control_window
                max_frame=self.conn.max_outbound_frame_size
                chunk_size=min(len(payload)-offset,stream_window,conn_window,max_frame)
                if chunk_size>0:
                    self.conn.send_data(self.stream_id,payload[offset:offset+chunk_size],end_stream=False)
                    outbound=self.conn.data_to_send()
                else:
                    outbound=b""
            if chunk_size>0:
                self.writer.write(outbound)
                await self.writer.drain()
                offset+=chunk_size
                continue
            self.window_event.clear()
            try:
                await asyncio.wait_for(self.window_event.wait(),timeout=5)
            except asyncio.TimeoutError:
                if self.stop_event.is_set():
                    break
    async def _receiver_loop(self):
        try:
            while not self.stop_event.is_set():
                data=await self.reader.read(65536)
                if not data:
                    break
                async with self.conn_lock:
                    events=self.conn.receive_data(data)
                for event in events:
                    if isinstance(event,DataReceived):
                        await self.recv_queue.put(event.data)
                        async with self.conn_lock:
                            self.conn.acknowledge_received_data(event.flow_controlled_length,event.stream_id)
                    elif isinstance(event,WindowUpdated):
                        self.window_event.set()
                    elif isinstance(event,RemoteSettingsChanged):
                        self.window_event.set()
                    elif isinstance(event,StreamEnded):
                        await self.recv_queue.put(None)
                        self.stop_event.set()
                    elif isinstance(event,StreamReset):
                        await self.recv_queue.put(None)
                        self.stop_event.set()
                    elif isinstance(event,ConnectionTerminated):
                        await self.recv_queue.put(None)
                        self.stop_event.set()
                await self._flush_outbound()
        except Exception as e:
            logger.error(f"Receiver error: {e}")
            await self.recv_queue.put(None)
            self.stop_event.set()
    async def _sender_loop(self):
        try:
            while not self.stop_event.is_set():
                msg=await self.send_queue.get()
                if msg is None:
                    break
                frame_data=struct.pack("!I",len(msg))+msg
                await self._send_framed_bytes(frame_data)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Sender error: {e}")
            self.stop_event.set()
    async def send(self,msg):
        await self.send_queue.put(msg)
    async def recv(self):
        while len(self._recv_buffer)<4:
            data=await self.recv_queue.get()
            if data is None:
                raise EOFError("Connection closed")
            self._recv_buffer+=data
        msg_len=struct.unpack("!I",self._recv_buffer[:4])[0]
        while len(self._recv_buffer)<4+msg_len:
            data=await self.recv_queue.get()
            if data is None:
                raise EOFError("Connection closed")
            self._recv_buffer+=data
        msg_data=self._recv_buffer[4:4+msg_len]
        self._recv_buffer=self._recv_buffer[4+msg_len:]
        return msg_data
    async def close(self):
        self.stop_event.set()
        await self.send_queue.put(None)
        if self.sender_task and not self.sender_task.done():
            self.sender_task.cancel()
        if self.receiver_task and not self.receiver_task.done():
            self.receiver_task.cancel()
        if self.conn and self.stream_id:
            try:
                async with self.conn_lock:
                    self.conn.end_stream(self.stream_id)
                    outbound=self.conn.data_to_send()
                if outbound:
                    self.writer.write(outbound)
                    await self.writer.drain()
            except:
                pass
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except:
                pass
        self.connected=False
