import secrets
import hashlib
from nanoid import generate

def generate_token():
    return generate(size=20)

def validate_token(token_bytes,expected_token,auth_salt):
    expected=hashlib.pbkdf2_hmac("sha256",expected_token.encode(),auth_salt,100000,32)
    return secrets.compare_digest(token_bytes,expected)
