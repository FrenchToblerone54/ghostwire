import struct
import os
import hashlib
from functools import lru_cache
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa,padding

MSG_PUBKEY=0x00
MSG_AUTH=0x01
MSG_CONNECT=0x02
MSG_DATA=0x03
MSG_CLOSE=0x04
MSG_PING=0x05
MSG_PONG=0x06
MSG_ERROR=0x07
MSG_INFO=0x08
MSG_CHILD_CFG=0x09
MSG_SESSION_KEY=0x0A
MSG_DATA_SEQ=0x0B
MSG_CLOSE_SEQ=0x0C
MSG_CONNECT_UDP=0x0D

@lru_cache(maxsize=64)
def get_aesgcm(key):
    return AESGCM(key)

def generate_rsa_keypair():
    private_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    return private_key,private_key.public_key()

def serialize_public_key(public_key):
    return public_key.public_bytes(encoding=serialization.Encoding.DER,format=serialization.PublicFormat.SubjectPublicKeyInfo)

def deserialize_public_key(public_key_bytes):
    return serialization.load_der_public_key(public_key_bytes)

def rsa_encrypt(public_key,plaintext):
    return public_key.encrypt(plaintext,padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=None))

def rsa_decrypt(private_key,ciphertext):
    return private_key.decrypt(ciphertext,padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),algorithm=hashes.SHA256(),label=None))

def encrypt_payload(key,plaintext,header):
    nonce=os.urandom(12)
    aesgcm=get_aesgcm(key)
    ciphertext=aesgcm.encrypt(nonce,plaintext,header)
    return nonce+ciphertext

def decrypt_payload(key,encrypted_payload,header):
    nonce=encrypted_payload[:12]
    ciphertext=encrypted_payload[12:]
    aesgcm=get_aesgcm(key)
    return aesgcm.decrypt(nonce,ciphertext,header)

def pack_header(msg_type,conn_id,payload_length):
    return struct.pack("!BII",msg_type,conn_id,payload_length)

def unpack_header(header):
    return struct.unpack("!BII",header)

def pack_pubkey(public_key):
    pubkey_bytes=serialize_public_key(public_key)
    header=pack_header(MSG_PUBKEY,0,len(pubkey_bytes))
    return header+pubkey_bytes

def pack_auth_payload(token,role="main",child_id=""):
    return role.encode()+b"\x00"+child_id.encode()+b"\x00"+token.encode()

def unpack_auth_payload(payload):
    parts=payload.split(b"\x00",2)
    if len(parts)==3:
        return parts[2].decode(),parts[0].decode(),parts[1].decode()
    return payload.decode(),"main",""

def pack_auth_message(token,public_key=None,role="main",child_id=""):
    payload=pack_auth_payload(token,role,child_id)
    if public_key:
        encrypted_token=rsa_encrypt(public_key,payload)
        header=pack_header(MSG_AUTH,0,len(encrypted_token))
        return header+encrypted_token
    else:
        header=pack_header(MSG_AUTH,0,len(payload))
        return header+payload

def pack_message(msg_type,conn_id,payload,key):
    aad=pack_header(msg_type,conn_id,0)
    encrypted=encrypt_payload(key,payload,aad)
    header=pack_header(msg_type,conn_id,len(encrypted))
    return header+encrypted

def unpack_message(data,key):
    if len(data)<9:
        raise ValueError("Message too short")
    header=data[:9]
    msg_type,conn_id,payload_length=unpack_header(header)
    if len(data)<9+payload_length:
        raise ValueError("Incomplete message")
    payload=bytes(data[9:9+payload_length])
    if msg_type==MSG_PUBKEY:
        return msg_type,conn_id,payload,9+payload_length
    if msg_type==MSG_AUTH:
        return msg_type,conn_id,payload,9+payload_length
    if msg_type==MSG_SESSION_KEY:
        return msg_type,conn_id,payload,9+payload_length
    aad=pack_header(msg_type,conn_id,0)
    decrypted=decrypt_payload(key,payload,aad)
    return msg_type,conn_id,decrypted,9+payload_length

def pack_connect(conn_id,remote_ip,remote_port,key):
    payload=remote_ip.encode()+struct.pack("!H",remote_port)
    return pack_message(MSG_CONNECT,conn_id,payload,key)

def pack_connect_udp(conn_id,remote_ip,remote_port,key):
    payload=remote_ip.encode()+struct.pack("!H",remote_port)
    return pack_message(MSG_CONNECT_UDP,conn_id,payload,key)

def unpack_connect(payload):
    remote_ip=payload[:-2].decode()
    remote_port=struct.unpack("!H",payload[-2:])[0]
    return remote_ip,remote_port

def pack_data(conn_id,data,key):
    return pack_message(MSG_DATA,conn_id,data,key)

def pack_data_seq(conn_id,seq,data,key):
    return pack_message(MSG_DATA_SEQ,conn_id,struct.pack("!I",seq)+data,key)

def unpack_data_seq(payload):
    return struct.unpack("!I",payload[:4])[0],payload[4:]

def pack_close(conn_id,reason,key):
    return pack_message(MSG_CLOSE,conn_id,bytes([reason]),key)

def pack_close_seq(conn_id,seq,reason,key):
    return pack_message(MSG_CLOSE_SEQ,conn_id,struct.pack("!IB",seq,reason),key)

def unpack_close_seq(payload):
    return struct.unpack("!IB",payload)

def pack_ping(timestamp,key):
    return pack_message(MSG_PING,0,struct.pack("!Q",timestamp),key)

def pack_pong(timestamp,key):
    return pack_message(MSG_PONG,0,struct.pack("!Q",timestamp),key)

def pack_error(conn_id,error_msg,key):
    return pack_message(MSG_ERROR,conn_id,error_msg.encode(),key)

def pack_info(version,key):
    return pack_message(MSG_INFO,0,version.encode(),key)

def pack_child_cfg(child_count,key):
    return pack_message(MSG_CHILD_CFG,0,struct.pack("!H",child_count),key)

def unpack_child_cfg(payload):
    return struct.unpack("!H",payload)[0]

def pack_session_key(session_key,client_public_key):
    encrypted_key=rsa_encrypt(client_public_key,session_key)
    header=pack_header(MSG_SESSION_KEY,0,len(encrypted_key))
    return header+encrypted_key

def unpack_session_key(payload,client_private_key):
    return rsa_decrypt(client_private_key,payload)
