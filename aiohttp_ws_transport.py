#!/usr/bin/env python3.13
import asyncio
import logging
from aiohttp import web,WSMsgType,ClientWebSocketResponse

logger=logging.getLogger(__name__)

class AiohttpClientWebSocket:
    def __init__(self,ws,session):
        self._ws=ws
        self._session=session
        self._closed=False
        self.close_code=None
    async def send(self,data):
        if isinstance(data,bytes):
            await self._ws.send_bytes(data)
        else:
            await self._ws.send_str(data)
    async def recv(self):
        msg=await self._ws.receive()
        if msg.type==WSMsgType.BINARY:
            return msg.data
        elif msg.type==WSMsgType.TEXT:
            return msg.data
        elif msg.type in (WSMsgType.CLOSE,WSMsgType.CLOSED,WSMsgType.CLOSING):
            self._closed=True
            self.close_code=1000
            raise ConnectionError("WebSocket closed")
        elif msg.type==WSMsgType.ERROR:
            raise ConnectionError(f"WebSocket error: {self._ws.exception()}")
        return b""
    async def close(self):
        if not self._closed:
            await self._ws.close()
            await self._session.close()
            self._closed=True
            self.close_code=1000
    def __aiter__(self):
        return self
    async def __anext__(self):
        try:
            return await self.recv()
        except ConnectionError:
            raise StopAsyncIteration

class AiohttpWebSocketAdapter:
    def __init__(self,ws,request):
        self._ws=ws
        self._request=request
        self._closed=False
        self.close_code=None
    @property
    def remote_address(self):
        peername=self._request.transport.get_extra_info('peername')
        if peername:
            return (peername[0],peername[1])
        return ('unknown',0)
    async def send(self,data):
        if isinstance(data,bytes):
            await self._ws.send_bytes(data)
        else:
            await self._ws.send_str(data)
    async def recv(self):
        msg=await self._ws.receive()
        if msg.type==WSMsgType.BINARY:
            return msg.data
        elif msg.type==WSMsgType.TEXT:
            return msg.data
        elif msg.type in (WSMsgType.CLOSE,WSMsgType.CLOSED,WSMsgType.CLOSING):
            self._closed=True
            self.close_code=1000
            raise ConnectionError("WebSocket closed")
        elif msg.type==WSMsgType.ERROR:
            raise ConnectionError(f"WebSocket error: {self._ws.exception()}")
        return b""
    async def close(self):
        if not self._closed:
            await self._ws.close()
            self._closed=True
            self.close_code=1000
    def __aiter__(self):
        return self
    async def __anext__(self):
        try:
            return await self.recv()
        except ConnectionError:
            raise StopAsyncIteration

async def start_aiohttp_ws_server(ghost_server):
    app=web.Application()
    async def websocket_handler(request):
        # CloudFlare optimization: Enable native WebSocket ping/pong with 30s interval
        # This is more efficient than application-level pings for CloudFlare's keepalive
        ws=web.WebSocketResponse(
            max_msg_size=0,
            compress=False,
            heartbeat=30  # 30 second native ping interval - CloudFlare friendly
        )
        await ws.prepare(request)
        adapter=AiohttpWebSocketAdapter(ws,request)
        try:
            await ghost_server.handle_client(adapter)
        except Exception as e:
            logger.error(f"Error handling client: {e}")
        finally:
            if not ws.closed:
                await ws.close()
        return ws
    app.router.add_get(ghost_server.config.websocket_path,websocket_handler)
    runner=web.AppRunner(app)
    await runner.setup()
    site=web.TCPSite(runner,ghost_server.config.listen_host,ghost_server.config.listen_port)
    await site.start()
    logger.info(f"aiohttp WebSocket server listening on {ghost_server.config.listen_host}:{ghost_server.config.listen_port}")
    await ghost_server.shutdown_event.wait()
    await runner.cleanup()
