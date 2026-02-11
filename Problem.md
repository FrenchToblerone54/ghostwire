# GhostWire Latency and Stability Issues

## Overview

GhostWire suffers from high latency and poor stability due to several architectural issues in the data path. These problems cause speedtest timeouts, frequent disconnections, and general instability.

## Critical Issues

### 1. **Artificial Batching Latency (HIGH PRIORITY)**

**Location:** `server.py:122-156`, `client.py:151-185`

**Problem:** The `sender_task` introduces artificial 50ms latency by waiting for data to batch:
```python
batch.extend(await asyncio.wait_for(send_queue.get(),timeout=0.05))
```

This means:
- Every send operation waits up to 50ms before transmitting
- Small packets are deliberately delayed for batching efficiency
- Latency-sensitive applications (speedtest, gaming, SSH) suffer severely
- Interactive sessions feel laggy and unresponsive

**Impact:** ~50ms added latency per direction = 100ms round-trip overhead

---

### 2. **Head-of-Line Blocking in Writer Loop (CRITICAL)**

**Location:** `server.py:88-120`, `client.py:117-149`

**Problem:** The `conn_writer_loop` batches up to 1MB before draining:
```python
while written<1048576:
    # Batch more data
    await asyncio.wait_for(writer.drain(),timeout=120)
```

This causes:
- Slow receivers block fast senders (head-of-line blocking)
- 120-second timeout is way too long
- If one connection is slow, it backs up the entire queue
- Memory pressure from large buffered batches

**Impact:** Cascading delays, timeouts, and connection drops under load

---

### 3. **Aggressive Queue Timeouts (HIGH PRIORITY)**

**Location:** `server.py:457`, `client.py:390`

**Problem:** Forwarding functions use 30-second queue put timeouts:
```python
await asyncio.wait_for(send_queue.put(message),timeout=30)
```

Issues:
- 30 seconds is too long for interactive traffic
- When queues back up, connections stall for 30s before failing
- No backpressure mechanism - just drop and fail

**Impact:** Speedtest connections hang for 30s then fail

---

### 4. **No TCP_NODELAY on Local Sockets (HIGH PRIORITY)**

**Location:** `server.py:389`, `client.py:357`

**Problem:** Local TCP connections don't disable Nagle's algorithm:
```python
server=await asyncio.start_server(...)
reader,writer=await asyncio.open_connection(...)
```

Without `TCP_NODELAY`:
- Nagle's algorithm waits for ACKs or full packets
- 40-200ms delays per small packet
- Disastrous for interactive traffic (SSH, gaming, speedtest handshake)
- Compounds with the 50ms batching latency

**Impact:** Additional 40-200ms latency on small packets

---

### 5. **~~Overly Aggressive Ping Timeouts~~ (NOT AN ISSUE)**

**Location:** `server.toml:6`, `client.py:539-543`

**Note:** Ping timeout of 10 seconds is **MANDATORY** behind CloudFlare:
```toml
ping_timeout=10
```

CloudFlare aggressively disconnects idle connections, so the 10s timeout is necessary to detect dead connections quickly. This is **not a problem** to fix.

---

### 6. **Preconnect Buffer Memory Pressure (MEDIUM PRIORITY)**

**Location:** `client.py:488-493`

**Problem:** Buffers up to 128 messages per connection before establishment:
```python
if len(buffer)<128:
    buffer.append(payload)
```

Issues:
- Each buffer can hold 128 * 262KB = 33MB per connection
- Memory pressure under many concurrent connections
- Delays while buffer fills before connection is ready

**Impact:** Memory exhaustion, slower connection establishment

---

### 7. **Semaphore Connection Limiting (MEDIUM PRIORITY)**

**Location:** `client.py:49`

**Problem:** Hard limit of 256 concurrent outbound connections:
```python
self.connect_semaphore=asyncio.Semaphore(256)
```

Issues:
- Speedtests create many short-lived connections
- Semaphore causes queuing delays
- No visibility into queue depth
- Can cause connection establishment timeouts

**Impact:** Connection queuing delays under load

---

### 8. **Large Read Buffers (LOW PRIORITY)**

**Location:** `server.py:438`, `client.py:376`

**Problem:** Reading 262KB (256KB) per read call:
```python
data=await reader.read(262144)
```

Issues:
- On slow connections, takes time to fill buffer
- Delays packet transmission until buffer fills
- Better for throughput, worse for latency

**Impact:** Added latency on slow/unreliable connections

---

### 9. **Writer Drain Timeout Too Long (LOW PRIORITY)**

**Location:** `server.py:110`, `client.py:139`

**Problem:** 120-second drain timeout:
```python
await asyncio.wait_for(writer.drain(),timeout=120)
```

Issues:
- Blocks for 2 minutes if receiver is slow
- Should use much shorter timeout (5-10s)
- Resources held unnecessarily long

**Impact:** Slow connections block resources for 2 minutes

---

### 10. **Batch Size Too Large (LOW PRIORITY)**

**Location:** `server.py:98`, `client.py:127`

**Problem:** 1MB batch threshold:
```python
while written<1048576:
```

Issues:
- Takes time to accumulate 1MB
- Memory pressure
- Latency while batching

**Impact:** Slight latency increase for large transfers

---

## Root Cause Summary

The primary issues are:

1. **Artificial batching delays** (50ms wait in sender_task)
2. **No TCP_NODELAY** on local connections (40-200ms Nagle delays)
3. **Head-of-line blocking** from large batch drains
4. **Overly aggressive timeouts** causing false disconnections

These combine to create:
- **Minimum latency:** 50ms (batch) + 50ms (Nagle) = 100ms+ per hop
- **Unstable connections** under load from timeout cascades
- **Speedtest failures** from connection establishment delays

---

## Recommended Fixes (Priority Order)

### HIGH PRIORITY (Critical for stability)

1. **Remove batching wait** - Send immediately, don't wait 50ms
2. **Enable TCP_NODELAY** - Set on all local sockets
3. **Reduce drain timeout** - From 120s to 5s
4. **Reduce queue timeout** - From 30s to 5s

### MEDIUM PRIORITY (Improves reliability)

5. **Reduce preconnect buffer** - From 128 to 16 messages
6. **Remove semaphore or increase limit** - From 256 to 1024+

### LOW PRIORITY (Optimization)

7. **Reduce read buffer size** - From 256KB to 64KB
8. **Reduce batch threshold** - From 1MB to 256KB

**Note:** Keep ping_timeout=10s - mandatory for CloudFlare stability

---

## Expected Improvements

After fixes:
- **Latency:** From 100ms+ to <10ms per hop
- **Stability:** No false disconnections under load
- **Speedtest:** Should complete without timeouts
- **Interactive traffic:** SSH/gaming will feel responsive
