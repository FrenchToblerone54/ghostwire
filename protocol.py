import struct
import os
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

MSG_AUTH=0x01
MSG_CONNECT=0x02
MSG_DATA=0x03
MSG_CLOSE=0x04
MSG_PING=0x05
MSG_PONG=0x06
MSG_ERROR=0x07

def derive_key(token,server_url):
    salt=hashlib.sha256(server_url.encode()).digest()[:16]
    kdf=PBKDF2HMAC(algorithm=hashes.SHA256(),length=32,salt=salt,iterations=100000)
    return kdf.derive(token.encode())

def encrypt_payload(key,plaintext,header):
    nonce=os.urandom(12)
    aesgcm=AESGCM(key)
    ciphertext=aesgcm.encrypt(nonce,plaintext,header)
    return nonce+ciphertext

def decrypt_payload(key,encrypted_payload,header):
    nonce=encrypted_payload[:12]
    ciphertext=encrypted_payload[12:]
    aesgcm=AESGCM(key)
    return aesgcm.decrypt(nonce,ciphertext,header)

def pack_header(msg_type,conn_id,payload_length):
    return struct.pack("!BII",msg_type,conn_id,payload_length)

def unpack_header(header):
    return struct.unpack("!BII",header)

def pack_auth_message(token):
    header=pack_header(MSG_AUTH,0,len(token))
    return header+token.encode()

def pack_message(msg_type,conn_id,payload,key):
    header=pack_header(msg_type,conn_id,0)
    encrypted=encrypt_payload(key,payload,header)
    header=pack_header(msg_type,conn_id,len(encrypted))
    return header+encrypted

def unpack_message(data,key):
    if len(data)<9:
        raise ValueError("Message too short")
    header=data[:9]
    msg_type,conn_id,payload_length=unpack_header(header)
    if len(data)<9+payload_length:
        raise ValueError("Incomplete message")
    payload=data[9:9+payload_length]
    if msg_type==MSG_AUTH:
        return msg_type,conn_id,payload.decode(),9+payload_length
    decrypted=decrypt_payload(key,payload,header)
    return msg_type,conn_id,decrypted,9+payload_length

def pack_connect(conn_id,remote_ip,remote_port,key):
    payload=remote_ip.encode()+struct.pack("!H",remote_port)
    return pack_message(MSG_CONNECT,conn_id,payload,key)

def unpack_connect(payload):
    remote_ip=payload[:-2].decode()
    remote_port=struct.unpack("!H",payload[-2:])[0]
    return remote_ip,remote_port

def pack_data(conn_id,data,key):
    return pack_message(MSG_DATA,conn_id,data,key)

def pack_close(conn_id,reason,key):
    return pack_message(MSG_CLOSE,conn_id,bytes([reason]),key)

def pack_ping(timestamp,key):
    return pack_message(MSG_PING,0,struct.pack("!Q",timestamp),key)

def pack_pong(timestamp,key):
    return pack_message(MSG_PONG,0,struct.pack("!Q",timestamp),key)

def pack_error(conn_id,error_msg,key):
    return pack_message(MSG_ERROR,conn_id,error_msg.encode(),key)
