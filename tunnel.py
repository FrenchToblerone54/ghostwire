import asyncio
import logging

logger=logging.getLogger(__name__)

class TunnelConnection:
    def __init__(self,conn_id,local_socket,remote_ip,remote_port):
        self.conn_id=conn_id
        self.local_socket=local_socket
        self.remote_ip=remote_ip
        self.remote_port=remote_port
        self.remote_socket=None
        self.closed=False

    async def connect_remote(self):
        try:
            self.remote_socket=await asyncio.wait_for(asyncio.open_connection(self.remote_ip,self.remote_port),timeout=10)
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {self.remote_ip}:{self.remote_port}: {e}")
            return False

    async def forward_local_to_remote(self,websocket,pack_data_func,key):
        try:
            reader,writer=self.local_socket
            while not self.closed:
                data=await reader.read(65536)
                if not data:
                    break
                message=pack_data_func(self.conn_id,data,key)
                await websocket.send(message)
        except Exception as e:
            logger.debug(f"Local to remote forward error: {e}")
        finally:
            self.closed=True

    async def forward_remote_to_local(self):
        try:
            reader,writer=self.remote_socket
            local_reader,local_writer=self.local_socket
            while not self.closed:
                data=await reader.read(65536)
                if not data:
                    break
                local_writer.write(data)
                await local_writer.drain()
        except Exception as e:
            logger.debug(f"Remote to local forward error: {e}")
        finally:
            self.closed=True

    def close(self):
        self.closed=True
        try:
            if self.local_socket:
                _,writer=self.local_socket
                writer.close()
        except:
            pass
        try:
            if self.remote_socket:
                _,writer=self.remote_socket
                writer.close()
        except:
            pass

class TunnelManager:
    def __init__(self):
        self.connections={}
        self.next_conn_id=1

    def generate_conn_id(self):
        conn_id=self.next_conn_id
        self.next_conn_id=(self.next_conn_id+1)%0xFFFFFFFF
        return conn_id

    def add_connection(self,conn_id,connection):
        self.connections[conn_id]=connection

    def get_connection(self,conn_id):
        return self.connections.get(conn_id)

    def remove_connection(self,conn_id):
        conn=self.connections.pop(conn_id,None)
        if conn:
            conn.close()

    def close_all(self):
        for conn in list(self.connections.values()):
            conn.close()
        self.connections.clear()
