# GhostWire Security

## Overview

GhostWire uses multiple layers of cryptography to protect both authentication and tunnel traffic.

## Authentication

### Threat Model

A passive eavesdropper or TLS-terminating proxy (e.g. CloudFlare) sees WebSocket frame contents in plaintext. Without protection, a MITM who controls the RSA key exchange could substitute their own public key, intercept the auth token, and authenticate independently as a legitimate client.

### PBKDF2 Challenge-Response

GhostWire prevents token extraction through a challenge-response mechanism:

1. Server generates a random 32-byte `auth_salt` per connection
2. Server sends its RSA public key **with the salt appended**
3. Client computes `derived_key = PBKDF2-SHA256(token, auth_salt, iterations=100_000, dklen=32)`
4. Client RSA-encrypts `derived_key + role + child_id` with the server's public key and sends it
5. Server decrypts, runs the same PBKDF2 derivation on the expected token, and compares with `secrets.compare_digest`

**What this prevents:** Even if a MITM intercepts and decrypts the auth message (by substituting its RSA key), it only obtains `PBKDF2(token, salt)` — a one-way derived value that cannot be reversed to recover the raw token. The token has ~120 bits of entropy (nanoid, 20 chars × 64-symbol alphabet), making offline brute force completely infeasible regardless of salt knowledge.

**Replay protection:** Each connection uses a fresh random `auth_salt`, so a captured derived key is useless for subsequent connections.

## Session Encryption

After authentication:

1. Client sends its RSA-2048 public key
2. Server generates a random 256-bit session key
3. Server RSA-encrypts the session key with the client's public key and sends it
4. Client decrypts the session key
5. All tunnel traffic is encrypted with **AES-256-GCM** using this session key, with random 96-bit nonces per frame

The AES-256-GCM authenticated encryption provides both confidentiality and integrity — any tampering with tunnel frames is detected and the frame is rejected.

## Transport Layer

- **WebSocket (default):** Uses `wss://` (TLS) via nginx or directly; the TLS layer protects the key exchange from passive observers
- **gRPC / HTTP/2:** Same TLS requirement
- **CloudFlare:** TLS is terminated at CloudFlare's edge; the RSA key exchange and PBKDF2 auth ensure tokens remain secret even from CloudFlare

## Token Security

- Tokens are generated with `nanoid(size=20)` using a 64-symbol alphabet (~120 bits of entropy)
- Tokens are stored only in the server's config file (`/etc/ghostwire/server.toml`) and the client's config file
- Tokens are never transmitted in plaintext — always PBKDF2-derived and RSA-encrypted
- Token comparison uses `secrets.compare_digest` to prevent timing attacks

## Summary

| Layer | Mechanism |
|-------|-----------|
| Auth token protection | PBKDF2-SHA256 (100 000 iterations) + RSA-2048-OAEP |
| Session key exchange | RSA-2048-OAEP |
| Tunnel traffic | AES-256-GCM with per-frame random nonces |
| Transport | TLS (WSS / HTTPS) |
