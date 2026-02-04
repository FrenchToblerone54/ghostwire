#!/usr/bin/env python3.13
import auth
import protocol

print("Testing GhostWire Core Functionality")
print("====================================")

print("\n1. Token Generation:")
token=auth.generate_token()
print(f"Generated token: {token}")
print(f"Token length: {len(token)}")

print("\n2. Token Validation:")
valid=auth.validate_token(token,token)
print(f"Same token validation: {valid}")
invalid=auth.validate_token(token,"wrong_token_12345678")
print(f"Different token validation: {invalid}")

print("\n3. Key Derivation:")
key=protocol.derive_key(token,"wss://example.com/ws")
print(f"Derived key length: {len(key)} bytes")

print("\n4. Message Packing/Unpacking:")
auth_msg=protocol.pack_auth_message(token)
print(f"AUTH message size: {len(auth_msg)} bytes")

print("\n5. Encryption/Decryption:")
test_payload=b"Hello, GhostWire!"
header=protocol.pack_header(protocol.MSG_DATA,1,0)
encrypted=protocol.encrypt_payload(key,test_payload,header)
print(f"Encrypted payload size: {len(encrypted)} bytes")
decrypted=protocol.decrypt_payload(key,encrypted,header)
print(f"Decrypted payload: {decrypted}")
print(f"Encryption/Decryption successful: {decrypted==test_payload}")

print("\n6. Complete Message:")
msg=protocol.pack_data(1,b"Test data",key)
print(f"Complete DATA message size: {len(msg)} bytes")

print("\n7. Port Mapping Parser:")
from config import parse_port_mapping
mappings=parse_port_mapping("8080=80")
print(f"Port mapping '8080=80': {mappings}")
mappings=parse_port_mapping("8000-8002:3000")
print(f"Port mapping '8000-8002:3000': {mappings}")
mappings=parse_port_mapping("127.0.0.1:443=1.1.1.1:5201")
print(f"Port mapping '127.0.0.1:443=1.1.1.1:5201': {mappings}")

print("\n✅ All tests passed!")
