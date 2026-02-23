import secrets
from nanoid import generate

def generate_token():
    """Generate a random authentication token using nanoid"""
    return generate(size=20)

def validate_token(token,expected_token):
    if len(token)!=len(expected_token):
        return False
    return secrets.compare_digest(token,expected_token)
