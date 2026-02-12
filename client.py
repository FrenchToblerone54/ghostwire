#!/usr/bin/env python3.13
import asyncio
import logging
import signal
import sys
import time
import struct
import argparse
import websockets
from nanoid import generate
from protocol import *
from config import ClientConfig
from tunnel import TunnelManager
from updater import Updater

logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(message)s")
logger=logging.getLogger(__name__)

def setup_logging(config):
    level=getattr(logging,config.log_level.upper(),logging.INFO)
    logging.getLogger().setLevel(level)
    if config.log_file:
        handler=logging.FileHandler(config.log_file)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(handler)

class GhostWireClient:
    def __init__(self,config):
        self.config=config
        self.tunnel_manager=TunnelManager()
        self.websocket=None
        self.main_websocket=None
        self.key=None
        self.running=False
        self.reconnect_delay=config.initial_delay
        self.send_queue=None
        self.control_queue=None
        self.main_send_queue=None
        self.main_control_queue=None
        self.shutdown_event=asyncio.Event()
        self.last_ping_time=0
        self.last_pong_time=0
        self.last_rx_time=0
        self.ping_interval=config.ping_interval
        self.ping_timeout=config.ping_timeout
        self.conn_write_queues={}
        self.conn_write_tasks={}
        self.connect_tasks=set()
        self.connect_semaphore=asyncio.Semaphore(1024)
        self.preconnect_buffers={}
        self.connected_server_url=""
        self.child_channels={}
        self.conn_channel_map={}
        self.channel_recv_tasks={}
        self.channel_sender_tasks={}
        self.channel_stop_events={}
        self.child_worker_tasks={}
        self.desired_child_count=0
        self.updater=Updater("client",check_interval=config.update_check_interval,check_on_startup=config.update_check_on_startup,http_proxy=config.update_http_proxy,https_proxy=config.update_https_proxy)

    def clear_conn_writers(self):
        for conn_id,task in list(self.conn_write_tasks.items()):
            if not task.done():
                task.cancel()
        self.conn_write_tasks.clear()
        self.conn_write_queues.clear()
        for task in list(self.connect_tasks):
            if not task.done():
                task.cancel()
        self.connect_tasks.clear()
        self.preconnect_buffers.clear()
        for task in list(self.channel_recv_tasks.values()):
            if not task.done():
                task.cancel()
        self.channel_recv_tasks.clear()
        for task in list(self.channel_sender_tasks.values()):
            if not task.done():
                task.cancel()
        self.channel_sender_tasks.clear()
        self.channel_stop_events.clear()
        for task in list(self.child_worker_tasks.values()):
            if not task.done():
                task.cancel()
        self.child_worker_tasks.clear()
        self.desired_child_count=0
        self.child_channels.clear()
        self.conn_channel_map.clear()

    def spawn_connect_task(self,conn_id,remote_ip,remote_port):
        task=asyncio.create_task(self.handle_connect(conn_id,remote_ip,remote_port))
        self.connect_tasks.add(task)
        task.add_done_callback(self.connect_tasks.discard)

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
                written=len(payload)
                queue.task_done()
                while written<262144:
                    try:
                        p=queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if p is None:
                        queue.task_done()
                        await asyncio.wait_for(writer.drain(),timeout=60)
                        return
                    writer.write(p)
                    written+=len(p)
                    queue.task_done()
                await asyncio.wait_for(writer.drain(),timeout=15)
        except asyncio.CancelledError:
            logger.debug(f"Writer task canceled for {conn_id}")
        except asyncio.TimeoutError:
            logger.warning(f"Write timeout for remote connection {conn_id}")
        except Exception as e:
            logger.debug(f"Writer loop error for {conn_id}: {e}")
        finally:
            self.conn_write_queues.pop(conn_id,None)
            self.conn_write_tasks.pop(conn_id,None)
            self.tunnel_manager.remove_connection(conn_id)

    async def sender_task(self,websocket,send_queue,control_queue,stop_event):
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
                    await websocket.send(bytes(batch))
        except Exception as e:
            logger.debug(f"Sender task error: {e}")
        finally:
            logger.debug("Sender task stopped")

    def get_channel(self,channel_id):
        if channel_id=="main":
            return {"ws":self.main_websocket,"send_queue":self.main_send_queue,"control_queue":self.main_control_queue}
        return self.child_channels.get(channel_id)

    async def close_channel(self,channel_id):
        stop_event=self.channel_stop_events.get(channel_id)
        if stop_event:
            stop_event.set()
        sender=self.channel_sender_tasks.get(channel_id)
        if sender:
            try:
                await asyncio.wait_for(sender,timeout=2)
            except:
                sender.cancel()
        ws=self.main_websocket if channel_id=="main" else self.child_channels.get(channel_id,{}).get("ws")
        if ws and getattr(ws,"close_code",None) is None:
            try:
                await asyncio.wait_for(ws.close(),timeout=2)
            except:
                pass
        recv_task=self.channel_recv_tasks.get(channel_id)
        if recv_task and recv_task is not asyncio.current_task() and not recv_task.done():
            recv_task.cancel()
        self.channel_sender_tasks.pop(channel_id,None)
        self.channel_recv_tasks.pop(channel_id,None)
        self.channel_stop_events.pop(channel_id,None)
        if channel_id!="main":
            self.child_channels.pop(channel_id,None)

    async def close_all_child_channels(self):
        for child_id in list(self.child_channels.keys()):
            await self.close_channel(child_id)

    async def child_worker(self,slot_id):
        delay=self.config.initial_delay
        while self.running and not self.shutdown_event.is_set():
            if not self.main_websocket:
                break
            server_url=self.connected_server_url if self.connected_server_url else self.config.server_url
            child_id=await self.connect_child_channel(server_url,slot_id)
            if child_id:
                delay=self.config.initial_delay
                recv_task=self.channel_recv_tasks.get(child_id)
                if recv_task:
                    try:
                        await recv_task
                    except:
                        pass
            if not self.running or self.shutdown_event.is_set() or not self.main_websocket:
                break
            logger.info(f"Child slot {slot_id} reconnecting in {delay} seconds...")
            try:
                await asyncio.wait_for(self.shutdown_event.wait(),timeout=delay)
                break
            except asyncio.TimeoutError:
                pass
            delay=min(delay*self.config.multiplier,self.config.max_delay)

    async def sync_child_workers(self,child_count):
        self.desired_child_count=max(0,child_count)
        for slot_id in list(self.child_worker_tasks.keys()):
            if slot_id>=self.desired_child_count:
                task=self.child_worker_tasks.pop(slot_id,None)
                if task and not task.done():
                    task.cancel()
                for child_id,channel in list(self.child_channels.items()):
                    if channel.get("slot_id")==slot_id:
                        await self.close_channel(child_id)
        for slot_id in range(self.desired_child_count):
            task=self.child_worker_tasks.get(slot_id)
            if not task or task.done():
                self.child_worker_tasks[slot_id]=asyncio.create_task(self.child_worker(slot_id))

    async def close_child_workers(self):
        for slot_id,task in list(self.child_worker_tasks.items()):
            if task and not task.done():
                task.cancel()
        self.child_worker_tasks.clear()
        self.desired_child_count=0
    async def connect(self):
        try:
            server_url=self.config.server_url
            if self.config.cloudflare_enabled and self.config.cloudflare_ips:
                best_ip=await self.find_best_cloudflare_ip()
                if best_ip:
                    server_url=self.config.server_url.replace(self.config.cloudflare_host,best_ip)
                    logger.info(f"Using CloudFlare IP: {best_ip}")
            self.connected_server_url=server_url
            self.main_websocket=await websockets.connect(server_url,max_size=None,max_queue=512,ping_interval=None,compression=None,write_limit=65536,close_timeout=10)
            self.websocket=self.main_websocket
            pubkey_msg=await asyncio.wait_for(self.main_websocket.recv(),timeout=10)
            if len(pubkey_msg)<9:
                raise ValueError("Invalid public key message")
            msg_type,_,pubkey_bytes,_=unpack_message(pubkey_msg,None)
            if msg_type!=MSG_PUBKEY:
                raise ValueError("Expected public key from server")
            server_public_key=deserialize_public_key(pubkey_bytes)
            client_private_key,client_public_key=generate_rsa_keypair()
            auth_msg=pack_auth_message(self.config.token,server_public_key,role="main")
            await self.main_websocket.send(auth_msg)
            await self.main_websocket.send(pack_pubkey(client_public_key))
            session_msg=await asyncio.wait_for(self.main_websocket.recv(),timeout=10)
            session_type,_,session_payload,_=unpack_message(session_msg,None)
            if session_type!=MSG_SESSION_KEY:
                raise ValueError("Expected session key from server")
            self.key=unpack_session_key(session_payload,client_private_key)
            self.last_ping_time=time.time()
            self.last_pong_time=time.time()
            self.last_rx_time=time.time()
            logger.info("Connected and authenticated to server")
            info_msg=pack_info(self.updater.current_version,self.key)
            await self.main_websocket.send(info_msg)
            self.reconnect_delay=self.config.initial_delay
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self.connected_server_url=""
            self.main_websocket=None
            self.websocket=None
            return False

    async def find_best_cloudflare_ip(self):
        best_ip=None
        best_latency=float("inf")
        for ip in self.config.cloudflare_ips:
            try:
                test_url=self.config.server_url.replace(self.config.cloudflare_host,ip)
                start=time.time()
                ws=await asyncio.wait_for(websockets.connect(test_url,max_size=None,ping_interval=None,compression=None,write_limit=65536),timeout=5)
                latency=time.time()-start
                await ws.close()
                if latency<best_latency:
                    best_latency=latency
                    best_ip=ip
            except:
                continue
        return best_ip

    async def connect_child_channel(self,server_url,slot_id):
        child_id=generate(size=20)
        try:
            ws=await websockets.connect(server_url,max_size=None,max_queue=512,ping_interval=None,compression=None,write_limit=65536,close_timeout=10)
            pubkey_msg=await asyncio.wait_for(ws.recv(),timeout=10)
            if len(pubkey_msg)<9:
                raise ValueError("Invalid child public key message")
            msg_type,_,pubkey_bytes,_=unpack_message(pubkey_msg,None)
            if msg_type!=MSG_PUBKEY:
                raise ValueError("Expected public key from server")
            server_public_key=deserialize_public_key(pubkey_bytes)
            auth_msg=pack_auth_message(self.config.token,server_public_key,role="child",child_id=child_id)
            await ws.send(auth_msg)
            send_queue=asyncio.Queue(maxsize=512)
            control_queue=asyncio.Queue(maxsize=256)
            stop_event=asyncio.Event()
            self.child_channels[child_id]={"ws":ws,"send_queue":send_queue,"control_queue":control_queue,"slot_id":slot_id}
            self.channel_stop_events[child_id]=stop_event
            self.channel_sender_tasks[child_id]=asyncio.create_task(self.sender_task(ws,send_queue,control_queue,stop_event))
            self.channel_recv_tasks[child_id]=asyncio.create_task(self.receive_messages(ws,child_id))
            logger.info(f"Child channel established: slot={slot_id} id={child_id}")
            return child_id
        except Exception as e:
            logger.warning(f"Child channel failed slot={slot_id} id={child_id}: {e}")
            return None

    async def handle_connect(self,conn_id,remote_ip,remote_port):
        try:
            async with self.connect_semaphore:
                channel_id=self.conn_channel_map.get(conn_id,"main")
                logger.debug(f"CONNECT request: {conn_id} -> {remote_ip}:{remote_port} via {channel_id}")
                reader,writer=await asyncio.wait_for(asyncio.open_connection(remote_ip,remote_port),timeout=10)
            self.tunnel_manager.add_connection(conn_id,(reader,writer))
            buffered=self.preconnect_buffers.pop(conn_id,[])
            for payload in buffered:
                await self.handle_data(conn_id,payload)
            asyncio.create_task(self.forward_remote_to_websocket(conn_id,reader))
        except Exception as e:
            logger.error(f"Failed to connect to {remote_ip}:{remote_port}: {e}")
            self.preconnect_buffers.pop(conn_id,None)
            error_msg=pack_error(conn_id,str(e),self.key)
            try:
                if self.control_queue:
                    self.control_queue.put_nowait(error_msg)
            except (asyncio.QueueFull,AttributeError):
                logger.warning(f"Control queue unavailable, dropping error message")

    async def forward_remote_to_websocket(self,conn_id,reader):
        try:
            while True:
                data=await reader.read(65536)
                if not data:
                    break
                channel_id=self.conn_channel_map.get(conn_id,"main")
                channel=self.get_channel(channel_id)
                send_queue=channel.get("send_queue") if channel else None
                if not send_queue:
                    logger.debug(f"Send queue unavailable, stopping forward for {conn_id}")
                    break
                message=pack_data(conn_id,data,self.key)
                try:
                    send_queue.put_nowait(message)
                except asyncio.QueueFull:
                    try:
                        await asyncio.wait_for(send_queue.put(message),timeout=30)
                    except asyncio.TimeoutError:
                        logger.warning(f"Send queue stalled for {conn_id}, closing connection")
                        break
        except Exception as e:
            logger.debug(f"Forward error for {conn_id}: {e}")
        finally:
            try:
                channel_id=self.conn_channel_map.get(conn_id,"main")
                channel=self.get_channel(channel_id)
                control_queue=channel.get("control_queue") if channel else None
                send_queue=channel.get("send_queue") if channel else None
                if send_queue:
                    send_queue.put_nowait(pack_close(conn_id,0,self.key))
                elif control_queue:
                    control_queue.put_nowait(pack_close(conn_id,0,self.key))
            except:
                pass
            self.conn_channel_map.pop(conn_id,None)
            self.tunnel_manager.remove_connection(conn_id)

    async def receive_messages(self,websocket,channel_id):
        buffer=bytearray()
        try:
            async for message in websocket:
                if channel_id=="main":
                    self.last_ping_time=time.time()
                    self.last_rx_time=time.time()
                buffer.extend(message)
                while len(buffer)>=9:
                    try:
                        msg_type,conn_id,payload,consumed=unpack_message(buffer,self.key)
                        del buffer[:consumed]
                    except ValueError:
                        break
                    if msg_type==MSG_CONNECT:
                        remote_ip,remote_port=unpack_connect(payload)
                        self.conn_channel_map[conn_id]=channel_id
                        logger.debug(f"Routing connection {conn_id} via {channel_id}")
                        self.spawn_connect_task(conn_id,remote_ip,remote_port)
                    elif msg_type==MSG_DATA:
                        await self.handle_data(conn_id,payload)
                    elif msg_type==MSG_CLOSE:
                        self.conn_channel_map.pop(conn_id,None)
                        self.preconnect_buffers.pop(conn_id,None)
                        queue=self.conn_write_queues.get(conn_id)
                        if queue:
                            try:
                                queue.put_nowait(None)
                            except asyncio.QueueFull:
                                task=self.conn_write_tasks.get(conn_id)
                                if task:
                                    task.cancel()
                                self.conn_write_queues.pop(conn_id,None)
                                self.conn_write_tasks.pop(conn_id,None)
                                self.tunnel_manager.remove_connection(conn_id)
                        else:
                            self.tunnel_manager.remove_connection(conn_id)
                    elif msg_type==MSG_ERROR:
                        logger.error(f"Server error for {conn_id}: {payload.decode()}")
                        self.conn_channel_map.pop(conn_id,None)
                        self.tunnel_manager.remove_connection(conn_id)
                    elif msg_type==MSG_PING:
                        timestamp=struct.unpack("!Q",payload)[0]
                        if channel_id=="main":
                            self.last_ping_time=time.time()
                        try:
                            channel=self.get_channel(channel_id)
                            control_queue=channel.get("control_queue") if channel else None
                            if control_queue:
                                control_queue.put_nowait(pack_pong(timestamp,self.key))
                        except (asyncio.QueueFull,AttributeError):
                            pass
                    elif msg_type==MSG_PONG:
                        if channel_id=="main":
                            self.last_pong_time=time.time()
                    elif msg_type==MSG_CHILD_CFG and channel_id=="main":
                        child_count=unpack_child_cfg(payload)
                        await self.sync_child_workers(child_count)
        except websockets.exceptions.ConnectionClosed:
            logger.warning(f"Connection closed by server channel={channel_id}")
        except Exception as e:
            logger.error(f"Receive error channel={channel_id}: {e}",exc_info=True)
        finally:
            if channel_id!="main":
                affected=[conn_id for conn_id,mapped_channel in self.conn_channel_map.items() if mapped_channel==channel_id]
                available_children=[cid for cid,ch in self.child_channels.items() if cid!=channel_id and ch.get("ws") and getattr(ch.get("ws"),"close_code",None) is None]
                for conn_id in affected:
                    if available_children:
                        new_channel=available_children[0]
                        self.conn_channel_map[conn_id]=new_channel
                        logger.debug(f"Reassigned {conn_id} from {channel_id} to {new_channel}")
                        continue
                    self.conn_channel_map.pop(conn_id,None)
                    self.preconnect_buffers.pop(conn_id,None)
                    await self.close_conn_writer(conn_id,flush=False)
                    self.tunnel_manager.remove_connection(conn_id)
                await self.close_channel(channel_id)

    async def handle_data(self,conn_id,payload):
        connection=self.tunnel_manager.get_connection(conn_id)
        if not connection:
            buffer=self.preconnect_buffers.setdefault(conn_id,[])
            if len(buffer)<16:
                buffer.append(payload)
            else:
                logger.warning(f"Preconnect buffer full for remote connection {conn_id}")
            return
        if connection:
            _,writer=connection
            try:
                queue=self.conn_write_queues.get(conn_id)
                if not queue:
                    queue=asyncio.Queue(maxsize=512)
                    self.conn_write_queues[conn_id]=queue
                    self.conn_write_tasks[conn_id]=asyncio.create_task(self.conn_writer_loop(conn_id,writer,queue))
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning(f"Write queue full for remote connection {conn_id}")
                await self.close_conn_writer(conn_id,flush=False)
            except Exception as e:
                logger.error(f"Error writing to remote connection {conn_id}: {e}")
                self.tunnel_manager.remove_connection(conn_id)

    async def ping_loop(self):
        while self.running:
            try:
                await asyncio.sleep(self.ping_interval)
                if self.main_websocket:
                    timestamp=int(time.time()*1000)
                    if self.main_control_queue:
                        try:
                            self.main_control_queue.put_nowait(pack_ping(timestamp,self.key))
                        except (asyncio.QueueFull,AttributeError):
                            logger.warning(f"Control queue unavailable, skipping ping")
                    for _,channel in list(self.child_channels.items()):
                        control_queue=channel.get("control_queue") if channel else None
                        if not control_queue:
                            continue
                        try:
                            control_queue.put_nowait(pack_ping(timestamp,self.key))
                        except (asyncio.QueueFull,AttributeError):
                            pass
            except Exception as e:
                logger.debug(f"Ping error: {e}")
                break

    async def ping_timeout_monitor(self):
        while self.running and self.main_websocket:
            await asyncio.sleep(15)
            now=time.time()
            last_activity=max(self.last_rx_time,self.last_pong_time)
            if now-last_activity>self.ping_timeout:
                logger.warning("Server ping timeout, closing connection")
                if self.main_websocket:
                    await self.main_websocket.close()
                break

    async def run(self):
        self.running=True
        update_task=None
        if self.config.auto_update:
            update_task=asyncio.create_task(self.updater.update_loop(self.shutdown_event))
        while self.running and not self.shutdown_event.is_set():
            if await self.connect():
                send_queue=asyncio.Queue(maxsize=512)
                control_queue=asyncio.Queue(maxsize=256)
                stop_event=asyncio.Event()
                self.send_queue=send_queue
                self.control_queue=control_queue
                self.main_send_queue=send_queue
                self.main_control_queue=control_queue
                try:
                    sender_task=asyncio.create_task(self.sender_task(self.main_websocket,send_queue,control_queue,stop_event))
                    self.channel_sender_tasks["main"]=sender_task
                    self.channel_stop_events["main"]=stop_event
                    ping_task=asyncio.create_task(self.ping_loop())
                    timeout_monitor=asyncio.create_task(self.ping_timeout_monitor())
                    receive_task=asyncio.create_task(self.receive_messages(self.main_websocket,"main"))
                    self.channel_recv_tasks["main"]=receive_task
                    shutdown_task=asyncio.create_task(self.shutdown_event.wait())
                    wait_tasks={receive_task,shutdown_task}
                    cf_timer=None
                    if self.config.cloudflare_enabled and self.config.cloudflare_max_connection_time>0:
                        cf_timer=asyncio.create_task(asyncio.sleep(self.config.cloudflare_max_connection_time))
                        wait_tasks.add(cf_timer)
                    done,pending=await asyncio.wait(wait_tasks,return_when=asyncio.FIRST_COMPLETED)
                    if cf_timer and cf_timer in done:
                        logger.info(f"CloudFlare connection limit, reconnecting proactively")
                    for task in pending:
                        task.cancel()
                    stop_event.set()
                    try:
                        await asyncio.wait_for(sender_task,timeout=2)
                    except:
                        sender_task.cancel()
                    ping_task.cancel()
                    timeout_monitor.cancel()
                    if shutdown_task in done:
                        break
                except Exception as e:
                    logger.error(f"Runtime error: {e}")
                finally:
                    await self.close_child_workers()
                    await self.close_all_child_channels()
                    self.clear_conn_writers()
                    if self.main_websocket:
                        try:
                            await asyncio.wait_for(self.main_websocket.close(),timeout=2)
                        except:
                            pass
                    self.main_websocket=None
                    self.websocket=None
                    self.connected_server_url=""
                    self.send_queue=None
                    self.control_queue=None
                    self.main_send_queue=None
                    self.main_control_queue=None
                    self.tunnel_manager.close_all()
            if self.running and not self.shutdown_event.is_set():
                logger.info(f"Reconnecting in {self.reconnect_delay} seconds...")
                try:
                    await asyncio.wait_for(self.shutdown_event.wait(),timeout=self.reconnect_delay)
                    break
                except asyncio.TimeoutError:
                    pass
                self.reconnect_delay=min(self.reconnect_delay*self.config.multiplier,self.config.max_delay)
        if update_task:
            update_task.cancel()
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
    parser.add_argument("--version",action="store_true",help="Print version and exit")
    args=parser.parse_args()
    if args.version:
        print(Updater("client").current_version)
        sys.exit(0)
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
    setup_logging(config)
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
