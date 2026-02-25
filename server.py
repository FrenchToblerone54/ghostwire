#!/usr/bin/env python3.13
import asyncio
import logging
import signal
import sys
import time
import struct
import argparse
import os
from protocol import *
from config import ServerConfig
from auth import validate_token
from tunnel import TunnelManager
from updater import Updater
from panel import start_panel
from udp_transport import UDPWriterAdapter

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
        self.main_websocket=None
        self.key=None
        self.tunnel_manager=TunnelManager()
        self.listeners=[]
        self.send_queue=None
        self.control_queue=None
        self.main_send_queue=None
        self.main_control_queue=None
        self.shutdown_event=asyncio.Event()
        self.auth_lock=asyncio.Lock()
        self.last_ping_time=0
        self.ping_timeout=config.ping_timeout
        self.conn_write_queues={}
        self.conn_write_tasks={}
        self.client_version=None
        self.child_channels={}
        self.conn_channel_map={}
        self.child_rr_index=0
        self.data_rr_index=0
        self.child_queue_sizes={}
        self.current_child_count=0
        self.conn_data_tx_seq={}
        self.conn_data_seq_enabled=set()
        self.conn_data_rx_expected={}
        self.conn_data_rx_pending={}
        self.conn_data_rx_wait_start={}
        self.conn_data_close_seq={}
        self.seq_timeout=30
        self.udp_sessions={}
        self.io_chunk_size=262144
        self.writer_batch_bytes=262144
        self.ws_send_batch_bytes=config.ws_send_batch_bytes
        self.ws_write_limit=4194304
        self.ws_max_queue=2048
        logger.info("Generating RSA key pair for secure authentication...")
        self.private_key,self.public_key=generate_rsa_keypair()
        self.updater=Updater("server",check_interval=config.update_check_interval,check_on_startup=config.update_check_on_startup,http_proxy=config.update_http_proxy,https_proxy=config.update_https_proxy)

    def clear_conn_writers(self):
        for conn_id,task in list(self.conn_write_tasks.items()):
            if not task.done():
                task.cancel()
        self.conn_write_tasks.clear()
        self.conn_write_queues.clear()
        self.conn_data_tx_seq.clear()
        self.conn_data_seq_enabled.clear()
        self.conn_data_rx_expected.clear()
        self.conn_data_rx_pending.clear()
        self.conn_data_close_seq.clear()

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
                while written<self.writer_batch_bytes:
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
            logger.warning(f"Write timeout for local connection {conn_id}")
        except Exception as e:
            logger.debug(f"Writer loop error for {conn_id}: {e}")
        finally:
            self.conn_write_queues.pop(conn_id,None)
            self.conn_write_tasks.pop(conn_id,None)
            self.clear_conn_data_state(conn_id)
            self.tunnel_manager.remove_connection(conn_id)

    async def sender_task(self,websocket,send_queue,control_queue,stop_event):
        try:
            while not stop_event.is_set() or not send_queue.empty() or not control_queue.empty():
                batch=bytearray()
                queue_depth=send_queue.qsize()+control_queue.qsize()
                if queue_depth<10:
                    adaptive_batch_size=16384
                elif queue_depth<50:
                    adaptive_batch_size=self.ws_send_batch_bytes
                else:
                    adaptive_batch_size=min(self.ws_send_batch_bytes*2,131072)
                for _ in range(64):
                    try:
                        batch.extend(control_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                while len(batch)<adaptive_batch_size:
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
                    while len(batch)<adaptive_batch_size:
                        try:
                            batch.extend(control_queue.get_nowait())
                        except asyncio.QueueEmpty:
                            break
                    while len(batch)<adaptive_batch_size:
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

    def get_available_child_ids(self):
        return [child_id for child_id,channel in self.child_channels.items() if channel.get("ws") and getattr(channel.get("ws"),"close_code",None) is None]

    def pick_child_for_connection(self):
        child_ids=self.get_available_child_ids()
        if not child_ids:
            return None
        best_child=None
        min_load=float("inf")
        for child_id in child_ids:
            channel=self.child_channels.get(child_id)
            if not channel:
                continue
            send_queue=channel.get("send_queue")
            conn_count=sum(1 for mapped_child in self.conn_channel_map.values() if mapped_child==child_id)
            queue_depth=send_queue.qsize() if send_queue else 0
            load_score=queue_depth+conn_count*10
            if load_score<min_load:
                min_load=load_score
                best_child=child_id
        if best_child:
            return best_child
        child_id=child_ids[self.child_rr_index%len(child_ids)]
        self.child_rr_index+=1
        return child_id

    def clear_conn_data_state(self,conn_id):
        self.conn_data_tx_seq.pop(conn_id,None)
        self.conn_data_seq_enabled.discard(conn_id)
        self.conn_data_rx_expected.pop(conn_id,None)
        self.conn_data_rx_pending.pop(conn_id,None)
        self.conn_data_rx_wait_start.pop(conn_id,None)
        self.conn_data_close_seq.pop(conn_id,None)

    def should_stripe_data(self):
        return self.config.ws_pool_enabled and len(self.get_available_child_ids())>1

    def next_data_seq(self,conn_id):
        seq=self.conn_data_tx_seq.get(conn_id,0)
        self.conn_data_tx_seq[conn_id]=seq+1
        return seq

    def pick_data_channel(self,conn_id):
        if self.should_stripe_data():
            child_ids=self.get_available_child_ids()
            if child_ids:
                child_id=child_ids[self.data_rr_index%len(child_ids)]
                self.data_rr_index+=1
                return child_id
        mapped_child=self.conn_channel_map.get(conn_id)
        if mapped_child:
            return mapped_child
        return "main"

    def get_send_queue_for_channel(self,channel_id):
        if channel_id=="main":
            return self.send_queue
        channel=self.child_channels.get(channel_id)
        if channel:
            return channel.get("send_queue")
        return None

    async def maybe_finalize_close_seq(self,conn_id):
        close_state=self.conn_data_close_seq.get(conn_id)
        if not close_state:
            return
        close_seq,_=close_state
        expected=self.conn_data_rx_expected.get(conn_id,0)
        pending=self.conn_data_rx_pending.get(conn_id,{})
        if expected>=close_seq and not pending:
            self.conn_data_close_seq.pop(conn_id,None)
            await self.handle_close(conn_id)
            self.conn_channel_map.pop(conn_id,None)
            self.clear_conn_data_state(conn_id)

    async def handle_data_seq(self,conn_id,seq,payload):
        expected=self.conn_data_rx_expected.get(conn_id,0)
        if seq<expected:
            return
        if seq==expected:
            self.conn_data_rx_wait_start.pop(conn_id,None)
            await self.handle_data(conn_id,payload)
            expected+=1
            pending=self.conn_data_rx_pending.get(conn_id)
            while pending and expected in pending:
                next_payload=pending.pop(expected)
                await self.handle_data(conn_id,next_payload)
                expected+=1
            if pending is not None and not pending:
                self.conn_data_rx_pending.pop(conn_id,None)
                self.conn_data_rx_wait_start.pop(conn_id,None)
            else:
                if conn_id not in self.conn_data_rx_wait_start:
                    self.conn_data_rx_wait_start[conn_id]=time.time()
            self.conn_data_rx_expected[conn_id]=expected
            await self.maybe_finalize_close_seq(conn_id)
            return
        pending=self.conn_data_rx_pending.setdefault(conn_id,{})
        if seq not in pending:
            pending[seq]=payload
            if conn_id not in self.conn_data_rx_wait_start:
                self.conn_data_rx_wait_start[conn_id]=time.time()

    async def sequence_timeout_monitor(self):
        while self.running and not self.shutdown_event.is_set():
            await asyncio.sleep(2)
            now=time.time()
            timed_out=[]
            for conn_id,start_time in list(self.conn_data_rx_wait_start.items()):
                if now-start_time>self.seq_timeout:
                    timed_out.append(conn_id)
            for conn_id in timed_out:
                expected=self.conn_data_rx_expected.get(conn_id,0)
                logger.warning(f"Connection {conn_id} sequence {expected} missing, skipping (VPN/TCP will retransmit)")
                self.conn_data_rx_expected[conn_id]=expected+1
                pending=self.conn_data_rx_pending.get(conn_id,{})
                while pending and self.conn_data_rx_expected[conn_id] in pending:
                    next_seq=self.conn_data_rx_expected[conn_id]
                    next_payload=pending.pop(next_seq)
                    await self.handle_data(conn_id,next_payload)
                    self.conn_data_rx_expected[conn_id]+=1
                if pending and self.conn_data_rx_expected[conn_id] not in pending:
                    self.conn_data_rx_wait_start[conn_id]=time.time()
                else:
                    self.conn_data_rx_wait_start.pop(conn_id,None)

    async def close_child_channels(self):
        for child_id,channel in list(self.child_channels.items()):
            stop_event=channel.get("stop_event")
            sender=channel.get("sender")
            ws=channel.get("ws")
            if stop_event:
                stop_event.set()
            if sender:
                try:
                    await asyncio.wait_for(sender,timeout=2)
                except:
                    sender.cancel()
            if ws and getattr(ws,"close_code",None) is None:
                try:
                    await asyncio.wait_for(ws.close(),timeout=2)
                except:
                    pass
            self.child_channels.pop(child_id,None)
        self.conn_channel_map.clear()

    async def close_connections_for_child(self,child_id):
        affected=[conn_id for conn_id,mapped_child in self.conn_channel_map.items() if mapped_child==child_id]
        if self.conn_data_seq_enabled:
            striped_count=len(self.conn_data_seq_enabled)
            logger.info(f"Child {child_id} lost during striped mode, {striped_count} striped connections will timeout if sequences are missing")
            for conn_id in affected:
                self.conn_channel_map.pop(conn_id,None)
            return
        alternative_children=self.get_available_child_ids()
        if not alternative_children:
            logger.warning(f"Child {child_id} lost, closing {len(affected)} connections (no alternatives)")
            for conn_id in affected:
                self.conn_channel_map.pop(conn_id,None)
                self.clear_conn_data_state(conn_id)
                await self.close_conn_writer(conn_id,flush=False)
                self.tunnel_manager.remove_connection(conn_id)
        else:
            logger.info(f"Child {child_id} lost, reassigning {len(affected)} connections to other children")
            reassign_index=0
            for conn_id in affected:
                new_child=alternative_children[reassign_index%len(alternative_children)]
                reassign_index+=1
                self.conn_channel_map[conn_id]=new_child
                logger.debug(f"Reassigned connection {conn_id} from {child_id} to {new_child}")

    async def route_message(self,msg_type,conn_id,payload):
        if msg_type==MSG_DATA:
            await self.handle_data(conn_id,payload)
        elif msg_type==MSG_DATA_SEQ:
            seq,data_payload=unpack_data_seq(payload)
            await self.handle_data_seq(conn_id,seq,data_payload)
        elif msg_type==MSG_CLOSE:
            await self.handle_close(conn_id)
            self.conn_channel_map.pop(conn_id,None)
            self.clear_conn_data_state(conn_id)
        elif msg_type==MSG_CLOSE_SEQ:
            close_seq,reason=unpack_close_seq(payload)
            self.conn_data_close_seq[conn_id]=(close_seq,reason)
            await self.maybe_finalize_close_seq(conn_id)
        elif msg_type==MSG_ERROR:
            logger.error(f"Client error for {conn_id}: {payload.decode()}")
            self.tunnel_manager.remove_connection(conn_id)
            self.conn_channel_map.pop(conn_id,None)
            self.clear_conn_data_state(conn_id)
        elif msg_type==MSG_INFO:
            self.client_version=payload.decode()
            logger.info(f"Client version: {self.client_version}")
    async def handle_client(self,websocket):
        client_id=f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"New connection from {client_id}")
        authenticated=False
        role="main"
        child_id=""
        sender=None
        ping_monitor=None
        seq_monitor=None
        pool_monitor=None
        udp_cleanup=None
        send_queue=asyncio.Queue(maxsize=512)
        control_queue=asyncio.Queue(maxsize=256)
        stop_event=asyncio.Event()
        self.last_ping_time=time.time()
        try:
            pubkey_msg=pack_pubkey(self.public_key)
            await websocket.send(pubkey_msg)
            buffer=bytearray()
            auth_msg=await asyncio.wait_for(websocket.recv(),timeout=30)
            buffer.extend(auth_msg)
            async with self.auth_lock:
                if len(buffer)<9:
                    logger.warning(f"Incomplete auth from {client_id}")
                    return
                msg_type,conn_id,encrypted_token,consumed=unpack_message(buffer,None)
                del buffer[:consumed]
                if msg_type!=MSG_AUTH:
                    logger.warning(f"Expected AUTH message from {client_id}")
                    return
                try:
                    token,role,child_id=unpack_auth_payload(rsa_decrypt(self.private_key,encrypted_token))
                except Exception as e:
                    logger.warning(f"Failed to decrypt token from {client_id}: {e}")
                    return
                if not validate_token(token,self.config.token):
                    logger.warning(f"Invalid token from {client_id}")
                    return
                if role=="main":
                    if self.main_websocket is not None:
                        logger.warning(f"Rejecting {client_id}: main already connected")
                        return
                elif role=="child":
                    if not self.config.ws_pool_enabled:
                        logger.warning(f"Rejecting {client_id}: child channels disabled")
                        return
                    if self.main_websocket is None:
                        logger.warning(f"Rejecting {client_id}: main not connected")
                        return
                    if not child_id:
                        logger.warning(f"Rejecting {client_id}: missing child id")
                        return
                    if self.key is None:
                        logger.warning(f"Rejecting {client_id}: missing main session key")
                        return
                else:
                    logger.warning(f"Rejecting {client_id}: unknown role {role}")
                    return
                authenticated=True
                if role=="main":
                    client_pubkey_msg=await asyncio.wait_for(websocket.recv(),timeout=10)
                    if len(client_pubkey_msg)<9:
                        logger.warning(f"Rejecting {client_id}: invalid client public key message")
                        return
                    try:
                        key_msg_type,_,client_pubkey_bytes,_=unpack_message(client_pubkey_msg,None)
                        if key_msg_type!=MSG_PUBKEY:
                            logger.warning(f"Rejecting {client_id}: expected client public key message")
                            return
                        client_public_key=deserialize_public_key(client_pubkey_bytes)
                    except Exception as e:
                        logger.warning(f"Rejecting {client_id}: invalid client public key: {e}")
                        return
                    self.key=os.urandom(32)
                    await websocket.send(pack_session_key(self.key,client_public_key))
                logger.info(f"Client {client_id} authenticated role={role}")
                sender=asyncio.create_task(self.sender_task(websocket,send_queue,control_queue,stop_event))
                if role=="main":
                    self.websocket=websocket
                    self.main_websocket=websocket
                    self.send_queue=send_queue
                    self.control_queue=control_queue
                    self.main_send_queue=send_queue
                    self.main_control_queue=control_queue
                    ping_monitor=asyncio.create_task(self.ping_monitor_loop())
                    seq_monitor=asyncio.create_task(self.sequence_timeout_monitor())
                    if self.config.ws_pool_enabled:
                        self.current_child_count=self.config.ws_pool_min
                        try:
                            control_queue.put_nowait(pack_child_cfg(self.current_child_count,self.key))
                        except asyncio.QueueFull:
                            logger.warning("Main control queue full, child config dropped")
                        pool_monitor=asyncio.create_task(self.pool_manager_loop())
                    udp_cleanup=asyncio.create_task(self.udp_session_cleanup_loop())
                else:
                    self.child_channels[child_id]={"ws":websocket,"send_queue":send_queue,"control_queue":control_queue,"stop_event":stop_event,"sender":sender}
                if not self.listeners:
                    await self.start_listeners()
            async for message in websocket:
                if role=="main":
                    self.last_ping_time=time.time()
                buffer.extend(message)
                while len(buffer)>=9:
                    try:
                        msg_type,conn_id,payload,consumed=unpack_message(buffer,self.key)
                        del buffer[:consumed]
                    except ValueError:
                        break
                    if msg_type in (MSG_DATA,MSG_DATA_SEQ,MSG_CLOSE,MSG_CLOSE_SEQ,MSG_ERROR,MSG_INFO):
                        await self.route_message(msg_type,conn_id,payload)
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
        except ConnectionError:
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
            if seq_monitor:
                seq_monitor.cancel()
            if pool_monitor:
                pool_monitor.cancel()
            if udp_cleanup:
                udp_cleanup.cancel()
            if authenticated:
                if role=="main":
                    self.udp_sessions.clear()
                    await self.close_child_channels()
                    self.clear_conn_writers()
                    self.websocket=None
                    self.main_websocket=None
                    self.send_queue=None
                    self.control_queue=None
                    self.main_send_queue=None
                    self.main_control_queue=None
                    self.client_version=None
                    self.tunnel_manager.close_all()
                else:
                    self.child_channels.pop(child_id,None)
                    await self.close_connections_for_child(child_id)

    async def pool_manager_loop(self):
        scale_down_count=0
        while self.running and not self.shutdown_event.is_set():
            await asyncio.sleep(self.config.ws_pool_scale_interval)
            if not self.main_websocket or not self.send_queue:
                continue
            qsize=self.send_queue.qsize()
            active=len(self.tunnel_manager.connections)
            target=self.current_child_count
            if qsize>=self.config.ws_pool_scale_up or active>self.current_child_count*10:
                target=min(self.config.ws_pool_children,self.current_child_count+1)
                scale_down_count=0
            elif qsize<=self.config.ws_pool_scale_down and active<self.current_child_count*5:
                scale_down_count+=1
                if scale_down_count>=3:
                    target=max(self.config.ws_pool_min,self.current_child_count-1)
                    scale_down_count=0
            else:
                scale_down_count=0
            if target!=self.current_child_count:
                self.current_child_count=target
                try:
                    self.control_queue.put_nowait(pack_child_cfg(self.current_child_count,self.key))
                    logger.info(f"Pool scaled to {self.current_child_count} connections (queue={qsize}, active={active})")
                except asyncio.QueueFull:
                    pass

    async def ping_monitor_loop(self):
        interval=max(2,self.ping_timeout//2)
        while self.running and not self.shutdown_event.is_set():
            await asyncio.sleep(interval)
            if time.time()-self.last_ping_time>self.ping_timeout:
                logger.warning("Client ping timeout, closing connection")
                if self.main_websocket:
                    await self.main_websocket.close()
                break

    async def handle_udp_datagram(self,data,src_addr,remote_ip,remote_port,local_transport):
        if not self.config.udp_enabled:
            return
        key=(src_addr,remote_ip,remote_port)
        if key in self.udp_sessions:
            conn_id,_,channel_id=self.udp_sessions[key]
            self.udp_sessions[key]=(conn_id,time.time(),channel_id)
        else:
            if not self.websocket or not self.send_queue:
                return
            conn_id=self.tunnel_manager.generate_conn_id()
            writer=UDPWriterAdapter(local_transport,src_addr)
            self.tunnel_manager.add_connection(conn_id,(None,writer))
            send_queue=self.send_queue
            control_queue=self.control_queue
            channel_id="main"
            if self.config.ws_pool_enabled:
                selected_child=self.pick_child_for_connection()
                if selected_child:
                    channel=self.child_channels.get(selected_child)
                    if channel:
                        send_queue=channel.get("send_queue")
                        control_queue=channel.get("control_queue")
                        self.conn_channel_map[conn_id]=selected_child
                        channel_id=selected_child
            self.udp_sessions[key]=(conn_id,time.time(),channel_id)
            connect_msg=pack_connect_udp(conn_id,remote_ip,remote_port,self.key)
            try:
                control_queue.put_nowait(connect_msg)
            except (asyncio.QueueFull,AttributeError):
                self.tunnel_manager.remove_connection(conn_id)
                del self.udp_sessions[key]
                return
        conn_id,_,channel_id=self.udp_sessions[key]
        send_queue=self.get_send_queue_for_channel(channel_id)
        if not send_queue:
            return
        message=pack_data(conn_id,data,self.key)
        try:
            send_queue.put_nowait(message)
        except asyncio.QueueFull:
            pass

    async def udp_session_cleanup_loop(self):
        while self.running and not self.shutdown_event.is_set():
            await asyncio.sleep(10)
            now=time.time()
            expired=[k for k,(cid,t,_) in list(self.udp_sessions.items()) if now-t>30]
            for key in expired:
                conn_id,_,channel_id=self.udp_sessions.pop(key)
                send_queue=self.get_send_queue_for_channel(channel_id)
                if send_queue and self.key:
                    try:
                        send_queue.put_nowait(pack_close(conn_id,0,self.key))
                    except asyncio.QueueFull:
                        pass
                self.conn_channel_map.pop(conn_id,None)
                self.tunnel_manager.remove_connection(conn_id)

    async def handle_udp_client(self,session):
        if self.main_websocket is not None:
            logger.warning(f"Rejecting UDP client from {session.remote_address}: main already connected")
            return
        sender=None
        ping_monitor=None
        seq_monitor=None
        udp_cleanup=None
        send_queue=asyncio.Queue(maxsize=512)
        control_queue=asyncio.Queue(maxsize=256)
        stop_event=asyncio.Event()
        self.last_ping_time=time.time()
        try:
            sender=asyncio.create_task(self.sender_task(session,send_queue,control_queue,stop_event))
            self.websocket=session
            self.main_websocket=session
            self.send_queue=send_queue
            self.control_queue=control_queue
            self.main_send_queue=send_queue
            self.main_control_queue=control_queue
            ping_monitor=asyncio.create_task(self.ping_monitor_loop())
            seq_monitor=asyncio.create_task(self.sequence_timeout_monitor())
            udp_cleanup=asyncio.create_task(self.udp_session_cleanup_loop())
            if not self.listeners:
                await self.start_listeners()
            logger.info(f"UDP raw client connected from {session.remote_address}")
            async for message in session:
                self.last_ping_time=time.time()
                msg_type,conn_id,payload,_=unpack_message(message,self.key)
                if msg_type in (MSG_DATA,MSG_DATA_SEQ,MSG_CLOSE,MSG_CLOSE_SEQ,MSG_ERROR,MSG_INFO):
                    await self.route_message(msg_type,conn_id,payload)
                elif msg_type==MSG_PING:
                    timestamp=struct.unpack("!Q",payload)[0]
                    try:
                        control_queue.put_nowait(pack_pong(timestamp,self.key))
                    except asyncio.QueueFull:
                        pass
        except ConnectionError:
            logger.info(f"UDP raw client disconnected from {session.remote_address}")
        except Exception as e:
            logger.error(f"UDP raw client error: {e}",exc_info=True)
        finally:
            if sender:
                stop_event.set()
                try:
                    await asyncio.wait_for(sender,timeout=2)
                except:
                    sender.cancel()
            if ping_monitor:
                ping_monitor.cancel()
            if seq_monitor:
                seq_monitor.cancel()
            if udp_cleanup:
                udp_cleanup.cancel()
            self.udp_sessions.clear()
            await self.close_child_channels()
            self.clear_conn_writers()
            self.websocket=None
            self.main_websocket=None
            self.send_queue=None
            self.control_queue=None
            self.main_send_queue=None
            self.main_control_queue=None
            self.client_version=None
            self.tunnel_manager.close_all()

    async def start_listeners(self):
        for local_ip,local_port,remote_ip,remote_port in self.config.port_mappings:
            server=await asyncio.start_server(lambda r,w,rip=remote_ip,rport=remote_port:self.handle_local_connection(r,w,rip,rport),local_ip,local_port,backlog=self.config.listen_backlog)
            self.listeners.append(server)
            logger.info(f"Listening on {local_ip}:{local_port} -> {remote_ip}:{remote_port}")
        if self.config.udp_enabled:
            from udp_transport import start_udp_local_listeners
            udp_transports=await start_udp_local_listeners(self)
            self.listeners.extend(udp_transports)

    async def handle_local_connection(self,reader,writer,remote_ip,remote_port):
        conn_id=self.tunnel_manager.generate_conn_id()
        self.tunnel_manager.add_connection(conn_id,(reader,writer))
        logger.debug(f"New local connection {conn_id} -> {remote_ip}:{remote_port}")
        try:
            send_queue=self.send_queue
            control_queue=self.control_queue
            selected_child=""
            if self.config.ws_pool_enabled:
                selected_child=self.pick_child_for_connection()
                if selected_child:
                    channel=self.child_channels.get(selected_child)
                    if channel:
                        send_queue=channel.get("send_queue")
                        control_queue=channel.get("control_queue")
                        self.conn_channel_map[conn_id]=selected_child
                else:
                    logger.debug(f"No child channel available for {conn_id}, using main channel")
            if not self.websocket or not send_queue or not control_queue:
                logger.error(f"No client connected, dropping connection {conn_id}")
                self.conn_channel_map.pop(conn_id,None)
                self.clear_conn_data_state(conn_id)
                self.tunnel_manager.remove_connection(conn_id)
                writer.close()
                await writer.wait_closed()
                return
            connect_msg=pack_connect(conn_id,remote_ip,remote_port,self.key)
            try:
                control_queue.put_nowait(connect_msg)
            except (asyncio.QueueFull,AttributeError):
                logger.error(f"Control queue unavailable, dropping connection {conn_id}")
                self.conn_channel_map.pop(conn_id,None)
                self.clear_conn_data_state(conn_id)
                self.tunnel_manager.remove_connection(conn_id)
                writer.close()
                await writer.wait_closed()
                return
            asyncio.create_task(self.forward_local_to_websocket(conn_id,reader))
        except Exception as e:
            logger.error(f"Error sending CONNECT: {e}")
            self.clear_conn_data_state(conn_id)
            self.tunnel_manager.remove_connection(conn_id)
            writer.close()
            await writer.wait_closed()

    async def forward_local_to_websocket(self,conn_id,reader):
        try:
            while True:
                data=await reader.read(self.io_chunk_size)
                if not data:
                    break
                channel_id=self.pick_data_channel(conn_id)
                send_queue=self.get_send_queue_for_channel(channel_id)
                if not self.websocket or not send_queue:
                    logger.debug(f"Client disconnected, stopping forward for {conn_id}")
                    break
                use_seq=conn_id in self.conn_data_seq_enabled or self.should_stripe_data()
                if use_seq:
                    self.conn_data_seq_enabled.add(conn_id)
                    message=pack_data_seq(conn_id,self.next_data_seq(conn_id),data,self.key)
                else:
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
                control_queue=self.control_queue
                send_queue=self.send_queue
                if self.config.ws_pool_enabled:
                    mapped_child=self.conn_channel_map.get(conn_id)
                    if mapped_child:
                        self.child_queue_sizes[mapped_child]=max(0,self.child_queue_sizes.get(mapped_child,0)-1)
                        channel=self.child_channels.get(mapped_child)
                        if channel:
                            control_queue=channel.get("control_queue")
                            send_queue=channel.get("send_queue")
                if self.websocket and send_queue:
                    if conn_id in self.conn_data_seq_enabled:
                        send_queue.put_nowait(pack_close_seq(conn_id,self.conn_data_tx_seq.get(conn_id,0),0,self.key))
                    else:
                        send_queue.put_nowait(pack_close(conn_id,0,self.key))
                elif self.websocket and control_queue:
                    control_queue.put_nowait(pack_close(conn_id,0,self.key))
            except:
                pass
            self.conn_channel_map.pop(conn_id,None)
            self.clear_conn_data_state(conn_id)
            self.tunnel_manager.remove_connection(conn_id)

    async def handle_data(self,conn_id,payload):
        connection=self.tunnel_manager.get_connection(conn_id)
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
                logger.warning(f"Write queue full for local connection {conn_id}")
                self.clear_conn_data_state(conn_id)
                await self.close_conn_writer(conn_id,flush=False)
            except Exception as e:
                logger.error(f"Error writing to local connection {conn_id}: {e}")
                self.clear_conn_data_state(conn_id)
                self.tunnel_manager.remove_connection(conn_id)

    async def handle_close(self,conn_id):
        logger.debug(f"CLOSE from client: {conn_id}")
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
                self.clear_conn_data_state(conn_id)
                self.tunnel_manager.remove_connection(conn_id)
        else:
            self.clear_conn_data_state(conn_id)
            self.tunnel_manager.remove_connection(conn_id)

    async def start(self):
        self.running=True
        logger.info(f"Starting GhostWire server ({self.config.protocol}) on {self.config.listen_host}:{self.config.listen_port}")
        start_panel(self.config,self)
        update_task=None
        if self.config.auto_update:
            update_task=asyncio.create_task(self.updater.update_loop(self.shutdown_event))
        if self.config.protocol=="http2":
            from http2_transport import start_http2_server
            await start_http2_server(self)
        elif self.config.protocol=="grpc":
            from grpc_transport import start_grpc_server
            await start_grpc_server(self)
        elif self.config.protocol=="udp":
            from udp_transport import start_udp_server
            await start_udp_server(self)
        else:
            from aiohttp_ws_transport import start_aiohttp_ws_server
            await start_aiohttp_ws_server(self)
        if update_task:
            update_task.cancel()
        logger.info("Server shutting down")

    def stop(self):
        self.running=False
        self.shutdown_event.set()

def signal_handler(server,loop):
    logger.info("Received shutdown signal")
    loop.call_soon_threadsafe(server.stop)

def cmd_panel_configure():
    import tomllib
    import toml
    import subprocess
    from auth import generate_token
    config_path="/etc/ghostwire/server.toml"
    for i,arg in enumerate(sys.argv):
        if arg in ("-c","--config") and i+1<len(sys.argv):
            config_path=sys.argv[i+1]
            break
    if not os.path.exists(config_path):
        print(f"Config not found: {config_path}")
        sys.exit(1)
    with open(config_path,"rb") as f:
        config=tomllib.load(f)
    panel_cfg=config.get("panel",{})
    panel_enabled=panel_cfg.get("enabled",False)
    if panel_enabled:
        panel_host=panel_cfg.get("host","127.0.0.1")
        panel_port=panel_cfg.get("port",9090)
        panel_path=panel_cfg.get("path","")
        print(f"Panel already configured: http://{panel_host}:{panel_port}/{panel_path}/")
    else:
        print("=== GhostWire Panel Configure ===\n")
        panel_host=input("Panel listen host [127.0.0.1]: ").strip() or "127.0.0.1"
        panel_port=int(input("Panel listen port [9090]: ").strip() or "9090")
        panel_path=generate_token()
        config["panel"]={"enabled":True,"host":panel_host,"port":panel_port,"path":panel_path,"threads":4}
        with open(config_path,"w") as f:
            toml.dump(config,f)
        print(f"\nPanel configured!\nURL: http://{panel_host}:{panel_port}/{panel_path}/")
        reply=input("Restart ghostwire-server to apply? [Y/n]: ").strip().lower()
        if reply!="n":
            subprocess.run(["systemctl","restart","ghostwire-server"])
    reply=input("\nSetup nginx for panel? [y/N]: ").strip().lower()
    if reply!="y":
        return
    if subprocess.run(["which","nginx"],capture_output=True).returncode!=0:
        print("Installing nginx...")
        subprocess.run(["apt-get","update"])
        subprocess.run(["apt-get","install","-y","nginx","certbot","python3-certbot-nginx"])
    domain=input("Enter domain name for panel: ").strip()
    if not domain:
        print("No domain entered, skipping nginx setup.")
        return
    nginx_http=f"server {{\n    listen 80;\n    server_name {domain};\n    location /.well-known/acme-challenge/ {{\n        root /var/www/html;\n    }}\n}}\n"
    with open("/etc/nginx/sites-available/ghostwire-panel","w") as f:
        f.write(nginx_http)
    subprocess.run(["ln","-sf","/etc/nginx/sites-available/ghostwire-panel","/etc/nginx/sites-enabled/ghostwire-panel"])
    subprocess.run(["nginx","-t"])
    subprocess.run(["systemctl","reload","nginx"])
    reply=input(f"Generate TLS certificate for {domain}? [y/N]: ").strip().lower()
    if reply=="y":
        subprocess.run(["certbot","--nginx","-d",domain])
    nginx_full=(
        f"server {{\n    listen 80;\n    server_name {domain};\n"
        f"    location /.well-known/acme-challenge/ {{\n        root /var/www/html;\n    }}\n"
        f"    location / {{\n        return 301 https://$server_name$request_uri;\n    }}\n}}\n"
        f"server {{\n    listen 443 ssl http2;\n    server_name {domain};\n"
        f"    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;\n"
        f"    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;\n"
        f"    ssl_protocols TLSv1.2 TLSv1.3;\n    ssl_ciphers HIGH:!aNULL:!MD5;\n"
        f"    location / {{\n        proxy_pass http://{panel_host}:{panel_port};\n"
        f"        proxy_http_version 1.1;\n        proxy_set_header Host $host;\n"
        f"        proxy_set_header X-Real-IP $remote_addr;\n"
        f"        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        f"        proxy_set_header X-Forwarded-Proto $scheme;\n    }}\n}}\n"
    )
    with open("/etc/nginx/sites-available/ghostwire-panel","w") as f:
        f.write(nginx_full)
    subprocess.run(["systemctl","reload","nginx"])
    print(f"nginx configured for panel: https://{domain}/{panel_path}/")

def main():
    if len(sys.argv)>=2 and sys.argv[1]=="update":
        asyncio.run(Updater("server").manual_update())
        sys.exit(0)
    if len(sys.argv)>=3 and sys.argv[1]=="panel" and sys.argv[2]=="configure":
        cmd_panel_configure()
        sys.exit(0)
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
