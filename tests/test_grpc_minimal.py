#!/usr/bin/env python3.13
import asyncio
import logging
from grpclib.server import Server,Stream
from grpclib.client import Channel
from tunnel_grpc import TunnelBase,TunnelStub
from tunnel_pb2 import TunnelMessage

logging.basicConfig(level=logging.INFO)
logger=logging.getLogger(__name__)

class MinimalServicer(TunnelBase):
    async def Stream(self,stream:Stream):
        logger.info("Server: Stream called")
        try:
            logger.info("Server: Sending hello")
            await stream.send_message(TunnelMessage(data=b"hello from server"))
            logger.info("Server: Waiting for client message")
            msg=await stream.recv_message()
            logger.info(f"Server: Received from client: {msg.data if msg else 'None'}")
            logger.info("Server: Sending goodbye")
            await stream.send_message(TunnelMessage(data=b"goodbye from server"))
        except Exception as e:
            logger.error(f"Server error: {e}",exc_info=True)
        finally:
            logger.info("Server: Stream ending")

async def test_client():
    logger.info("Client: Connecting")
    channel=Channel('127.0.0.1',9999)
    stub=TunnelStub(channel)
    try:
        async with stub.Stream.open() as stream:
            logger.info("Client: Stream opened")
            logger.info("Client: Sending init message")
            await stream.send_message(TunnelMessage(data=b"init"))
            logger.info("Client: Receiving first message")
            msg1=await stream.recv_message()
            logger.info(f"Client: Received: {msg1.data if msg1 else 'None'}")
            logger.info("Client: Sending response")
            await stream.send_message(TunnelMessage(data=b"hi from client"))
            logger.info("Client: Receiving second message")
            msg2=await stream.recv_message()
            logger.info(f"Client: Received: {msg2.data if msg2 else 'None'}")
    except Exception as e:
        logger.error(f"Client error: {e}",exc_info=True)
    finally:
        channel.close()
        logger.info("Client: Done")

async def main():
    server=Server([MinimalServicer()])
    await server.start('127.0.0.1',9999)
    logger.info("Server started on 9999")
    await asyncio.sleep(0.5)
    await test_client()
    await asyncio.sleep(0.5)
    server.close()
    await server.wait_closed()
    logger.info("Server stopped")

if __name__=="__main__":
    asyncio.run(main())
