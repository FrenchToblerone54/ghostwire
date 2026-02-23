#!/usr/bin/env python3.13
import asyncio
import logging
import os
import struct
from protocol import *

logger=logging.getLogger(__name__)

HELLO=b'\xff'

def _split_send(data,send_fn):
    buf=data if isinstance(data,(bytes,bytearray)) else bytes(data)
    offset=0
    while offset+9<=len(buf):
        payload_len=struct.unpack_from("!I",buf,offset+5)[0]
        end=offset+9+payload_len
        if end>len(buf):
            break
        send_fn(buf[offset:end])
        offset=end

class UDPWriterAdapter:
    def __init__(self,transport,addr=None):
        self._transport=transport
        self._addr=addr
    def write(self,data):
        self._transport.sendto(data,self._addr) if self._addr else self._transport.sendto(data)
    async def drain(self):
        pass
    def close(self):
        pass
    async def wait_closed(self):
        pass

class _UDPDataProtocol(asyncio.DatagramProtocol):
    def __init__(self,recv_queue):
        self._recv_queue=recv_queue
    def datagram_received(self,data,addr):
        try:
            self._recv_queue.put_nowait(data)
        except asyncio.QueueFull:
            pass
    def error_received(self,exc):
        logger.warning(f"UDP data error: {exc}")
    def connection_lost(self,exc):
        try:
            self._recv_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

class _UDPClientProtocol(asyncio.DatagramProtocol):
    def __init__(self,recv_queue):
        self._recv_queue=recv_queue
        self._transport=None
    def connection_made(self,transport):
        self._transport=transport
    def datagram_received(self,data,addr):
        try:
            self._recv_queue.put_nowait(data)
        except asyncio.QueueFull:
            pass
    def error_received(self,exc):
        logger.warning(f"UDP error: {exc}")
    def connection_lost(self,exc):
        pass

class UDPClientTransport:
    def __init__(self,host,port,token):
        self.host=host
        self.port=port
        self.token=token
        self.key=None
        self.connected=False
        self._transport=None
        self._recv_queue=asyncio.Queue(maxsize=4096)

    @property
    def close_code(self):
        return None if self.connected else 1000

    async def connect(self):
        loop=asyncio.get_event_loop()
        self._transport,_=await loop.create_datagram_endpoint(
            lambda: _UDPClientProtocol(self._recv_queue),
            remote_addr=(self.host,self.port)
        )
        for attempt in range(5):
            try:
                self._transport.sendto(HELLO)
                data=await asyncio.wait_for(self._recv_queue.get(),timeout=3)
                if len(data)<9:
                    continue
                msg_type,_,pubkey_bytes,_=unpack_message(data,None)
                if msg_type!=MSG_PUBKEY:
                    continue
                server_public_key=deserialize_public_key(pubkey_bytes)
                client_private_key,client_public_key=generate_rsa_keypair()
                self._transport.sendto(pack_auth_message(self.token,server_public_key,role="main"))
                self._transport.sendto(pack_pubkey(client_public_key))
                session_data=await asyncio.wait_for(self._recv_queue.get(),timeout=5)
                if len(session_data)<9:
                    continue
                session_type,_,session_payload,_=unpack_message(session_data,None)
                if session_type!=MSG_SESSION_KEY:
                    continue
                self.key=unpack_session_key(session_payload,client_private_key)
                self.connected=True
                return True
            except asyncio.TimeoutError:
                logger.debug(f"UDP handshake timeout attempt {attempt+1}")
        return False

    async def send(self,data):
        if not self.connected:
            raise ConnectionError("Not connected")
        _split_send(data,self._transport.sendto)

    async def recv(self):
        data=await self._recv_queue.get()
        if data is None:
            raise ConnectionError("UDP closed")
        return data

    async def close(self):
        self.connected=False
        try:
            self._recv_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        if self._transport:
            self._transport.close()
            self._transport=None

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.recv()
        except ConnectionError:
            raise StopAsyncIteration

class UDPSession:
    def __init__(self,addr,send_fn):
        self._addr=addr
        self._send_fn=send_fn
        self._recv_queue=asyncio.Queue(maxsize=4096)
        self.close_code=None
        self._closed=False

    @property
    def remote_address(self):
        return self._addr

    async def send(self,data):
        if not self._closed:
            _split_send(data,lambda d: self._send_fn(d,self._addr))

    async def recv(self):
        data=await self._recv_queue.get()
        if data is None:
            raise ConnectionError("Session closed")
        return data

    async def close(self):
        self._closed=True
        self.close_code=1000
        try:
            self._recv_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.recv()
        except ConnectionError:
            raise StopAsyncIteration

class _UDPServerProtocol(asyncio.DatagramProtocol):
    def __init__(self,ghost_server):
        self._ghost=ghost_server
        self._transport=None
        self._session=None
        self._pending_addr=None
        self._pending_queue=asyncio.Queue()

    def connection_made(self,transport):
        self._transport=transport

    def datagram_received(self,data,addr):
        if data==HELLO:
            if self._session is None and self._pending_addr is None:
                self._pending_addr=addr
                asyncio.create_task(self._handshake(addr))
            return
        if self._pending_addr==addr:
            try:
                self._pending_queue.put_nowait(data)
            except asyncio.QueueFull:
                pass
        elif self._session and not self._session._closed and self._session._addr==addr:
            try:
                self._session._recv_queue.put_nowait(data)
            except asyncio.QueueFull:
                pass

    def send_to(self,data,addr):
        if self._transport:
            self._transport.sendto(data,addr)

    async def _handshake(self,addr):
        ghost=self._ghost
        try:
            self.send_to(pack_pubkey(ghost.public_key),addr)
            auth_data=await asyncio.wait_for(self._pending_queue.get(),timeout=30)
            if len(auth_data)<9:
                return
            msg_type,_,encrypted_token,_=unpack_message(auth_data,None)
            if msg_type!=MSG_AUTH:
                return
            try:
                token,role,_=unpack_auth_payload(rsa_decrypt(ghost.private_key,encrypted_token))
            except Exception as e:
                logger.warning(f"UDP: Failed to decrypt token from {addr}: {e}")
                return
            from auth import validate_token
            if not validate_token(token,ghost.config.token):
                logger.warning(f"UDP: Invalid token from {addr}")
                return
            if role!="main":
                logger.warning(f"UDP: Only main role supported, got {role}")
                return
            pubkey_data=await asyncio.wait_for(self._pending_queue.get(),timeout=10)
            if len(pubkey_data)<9:
                return
            key_type,_,client_pubkey_bytes,_=unpack_message(pubkey_data,None)
            if key_type!=MSG_PUBKEY:
                return
            client_public_key=deserialize_public_key(client_pubkey_bytes)
            session_key=os.urandom(32)
            self.send_to(pack_session_key(session_key,client_public_key),addr)
            session=UDPSession(addr,self.send_to)
            ghost.key=session_key
            self._session=session
            self._pending_addr=None
            logger.info(f"UDP client authenticated from {addr}")
            await ghost.handle_udp_client(session)
        except Exception as e:
            logger.error(f"UDP handshake error from {addr}: {e}",exc_info=True)
        finally:
            if self._session and self._session._addr==addr:
                self._session=None
            self._pending_addr=None

class _UDPLocalListener(asyncio.DatagramProtocol):
    def __init__(self,ghost_server,remote_ip,remote_port):
        self._ghost=ghost_server
        self._remote_ip=remote_ip
        self._remote_port=remote_port
        self._transport=None
    def connection_made(self,transport):
        self._transport=transport
    def datagram_received(self,data,addr):
        asyncio.create_task(self._ghost.handle_udp_datagram(data,addr,self._remote_ip,self._remote_port,self._transport))
    def error_received(self,exc):
        logger.warning(f"UDP local listener error: {exc}")
    def connection_lost(self,exc):
        pass

async def start_udp_local_listeners(ghost_server):
    loop=asyncio.get_event_loop()
    transports=[]
    for local_ip,local_port,remote_ip,remote_port in ghost_server.config.port_mappings:
        transport,_=await loop.create_datagram_endpoint(
            lambda rip=remote_ip,rport=remote_port: _UDPLocalListener(ghost_server,rip,rport),
            local_addr=(local_ip,local_port)
        )
        transports.append(transport)
        logger.info(f"UDP listening on {local_ip}:{local_port} -> {remote_ip}:{remote_port}")
    return transports

async def start_udp_server(ghost_server):
    loop=asyncio.get_event_loop()
    transport,_=await loop.create_datagram_endpoint(
        lambda: _UDPServerProtocol(ghost_server),
        local_addr=(ghost_server.config.listen_host,ghost_server.config.listen_port)
    )
    logger.info(f"UDP server listening on {ghost_server.config.listen_host}:{ghost_server.config.listen_port}")
    await ghost_server.shutdown_event.wait()
    transport.close()
