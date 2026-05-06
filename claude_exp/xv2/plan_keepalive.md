# Plan: 0800 Keep-Alive & Socket Reconnection

## Overview

Two features:
1. **0800 keep-alive** — the upstream_host always initiates `0800` (F24=100) on a configurable interval, regardless of whether it is in server or client mode. The router passes the `0800` through to the downstream_host (via IMS Connect, bypassing workers/STAN/crypto). The downstream_host replies with `0810` echoing F24. The router passes the `0810` back to upstream_host.
2. **Reconnection** — when either side drops, the router tears down both connections, waits `reestablish_seconds`, reconnects downstream, then resumes upstream (server: accept new connection; client: reconnect). Only one upstream client is active at any time.

Message flow for keep-alive:
```
upstream_host  →  0800  →  router  →  0800 (IMS-framed)  →  downstream_host
upstream_host  ←  0810  ←  router  ←  0810 (IMS-framed)  ←  downstream_host
```

---

## Phase 1 — Config additions

**Router configs** (`router/router_1/config.json`, `router/router_2/config.json`):

Add at top level:
```json
"reestablish_seconds": 10
```

**Upstream_host config** (`simulators/upstream_host/upstream_host_1/config.json`):

Add at top level:
```json
"ping_0800_seconds": 30
```

Field 24 already exists in `test_spec.json` (ASCII, 3 chars, fixed length). No spec change needed.

---

## Phase 2 — 0800/0810 message helpers (`shared/iso_utils.py`)

Add two functions:

```python
def build_0800(spec) -> bytes:
    msg = {"t": "0800", "24": "100"}
    encoded, _ = iso8583.encode(msg, spec=spec)
    return encoded

def build_0810(f24: str, spec) -> bytes:
    msg = {"t": "0810", "24": f24}
    encoded, _ = iso8583.encode(msg, spec=spec)
    return encoded
```

---

## Phase 3 — Per-connection upstream write lock

`_downstream_receiver` writes `0110` and `0810` responses to `up_conn`. `_handle_upstream` reads only — it no longer writes replies directly. However, in the future this could change, and the lock costs nothing, so keep it.

**Change**: create `up_write_lock = threading.Lock()` when a new upstream connection is established.

- Store in each `pending` entry so `_downstream_receiver` can acquire it before writing `0110`.
- Pass in a shared mutable ref (`upstream_ref = {"conn": None, "lock": None}`) updated when upstream connects, so `_downstream_receiver` can write `0810` back without a pending lookup.

Pending entry (for 0110) unchanged in shape but `_downstream_receiver` acquires `entry["up_write_lock"]` before writing.

---

## Phase 4 — 0800/0810 pass-through in router (`router/main.py`)

### 4a — `_handle_upstream()`: forward 0800 to downstream

Current code rejects any non-0100 MTI (line 114). Change to:

```
if mti == "0100":  → enqueue to work_queue (existing)
if mti == "0800":  → forward directly to downstream via IMS Connect
                      (acquire ds_write_lock, build_frame, to_sock.sendall)
                      no STAN mapping, no crypto, no worker thread
if mti == "0810":  → log warning (unexpected — router never sends 0800), continue
else:              → log warning, continue
```

Signature gains `to_sock`, `ims_cfg`, `ds_write_lock`, and `spec` parameters.

### 4b — `_downstream_receiver()`: route 0810 back to upstream

Current code only handles `0110` (line 146). Add:

```
if mti == "0110":  → existing STAN-lookup path
if mti == "0810":  → write directly to current upstream_host connection
                      (acquire upstream_ref["lock"], write_message 0810 to upstream_ref["conn"])
else:              → log warning
```

`_downstream_receiver` receives `upstream_ref` (shared mutable dict). When no upstream is connected (`upstream_ref["conn"] is None`), log and discard the 0810.

### 4c — `upstream_ref` lifecycle

`upstream_ref = {"conn": None, "lock": None}` is created per session in `run()`.

- Set when `_handle_upstream` starts (upstream connects).
- Cleared when `_handle_upstream` ends (upstream disconnects).

---

## Phase 5 — Reconnection logic (`router/main.py`)

### Design

Introduce a **session loop** inside `run()`. A session = one downstream connection + one upstream connection.

Add `reconnect_event = threading.Event()` per session. Both `_handle_upstream` and `_downstream_receiver` receive it and call `reconnect_event.set()` on disconnect.

### Session lifecycle (replaces current flat `run()` logic)

```
while not stop_event.is_set():
    reconnect_event = threading.Event()
    upstream_ref = {"conn": None, "lock": None}

    # 1. Connect downstream
    to_sock, from_sock = _connect_downstream_ims(...)

    # 2. Start workers + downstream receiver
    start n_workers × _worker(to_sock, ..., reconnect_event)
    start ds-receiver(from_sock, upstream_ref, ..., reconnect_event)

    # 3. Start upstream (server or client mode)
    server mode: _upstream_accept_loop thread
    client mode: _client_upstream_loop thread

    # 4. Wait for session to end
    while not reconnect_event.is_set() and not stop_event.is_set():
        stop_event.wait(timeout=1)

    if stop_event.is_set():
        break

    # 5. Teardown current session
    if upstream_ref["conn"]:
        upstream_ref["conn"].close()    # handler thread exits via ConnectionError
    poison pill workers (n_workers × None)
    to_sock.close(), from_sock.close()
    log "session ended, reconnecting in Ns"

    # 6. Wait before retry
    stop_event.wait(timeout=reestablish_seconds)
```

### Changes to `_handle_upstream()`

- Receives `reconnect_event`, `upstream_ref`, `to_sock`, `ims_cfg`, `ds_write_lock`, `spec`.
- On entry: set `upstream_ref["conn"]` and `upstream_ref["lock"]`.
- On `ConnectionError`: set `reconnect_event`, clear `upstream_ref`, return.

### Changes to `_downstream_receiver()`

- Receives `reconnect_event`, `upstream_ref`.
- On `ConnectionError`: set `reconnect_event`, return.
- Handles both `0110` (STAN lookup) and `0810` (upstream_ref direct write).

### `_worker()` — trigger reconnect on downstream write failure

When a worker catches an exception writing to `to_sock`, it sets `reconnect_event`. Pass `reconnect_event` to workers.

### Server-mode accept loop — one connection at a time

`_upstream_accept_loop(srv_sock, reconnect_event, stop_event, handler_fn)`:

```
while not reconnect_event.is_set() and not stop_event.is_set():
    accept one up_conn
    spawn _handle_upstream thread
    join that thread          # blocks — enforces one connection at a time
```

`srv_sock` is created once before the session loop and reused across sessions (never closed between reconnects). OS queues incoming connections during the reconnect delay.

### Client-mode

`_client_upstream_loop` runs per session as a thread. On upstream disconnect it sets `reconnect_event` (no silent retry within a session). Session teardown closes the socket.

---

## Phase 6 — Downstream simulator: handle 0800, reply 0810 (`simulators/downstream_host/main.py`)

The downstream_host must recognise inbound 0800 and respond with 0810.

In the downstream_host request handler, add before the existing `_process_0100` path:

```
if mti == "0800":
    f24 = req.get("24", "100")
    reply = build_0810(f24, spec)
    # send back via the "from connection" (response stream) to router
```

The 0810 is sent on the `from_sock` response stream (same path as 0110 responses), wrapped in an IMS response frame.

---

## Phase 7 — Upstream simulator: keepalive sender and 0810 handling (`simulators/upstream_host/main.py`)

### 7a — receive loop: handle 0810

In the upstream_host receive loop, add:
```
if mti == "0810":  → log receipt (response to our 0800), continue
```

### 7b — new `_keepalive_sender()`

```python
def _keepalive_sender(sock, framing, spec, interval_sec, stop_evt):
    while not stop_evt.is_set():
        stop_evt.wait(timeout=interval_sec)
        if stop_evt.is_set():
            break
        try:
            write_message(sock, build_0800(spec), framing)
            log.debug("upstream_host: sent 0800 keepalive")
        except Exception:
            break
```

### 7c — start keepalive thread per connection

After a connection is established (both server and client mode), start `_keepalive_sender` as a daemon thread. Config key `ping_0800_seconds` from upstream_host config (default 30 if absent).

---

## File change summary

| File | Change |
|------|--------|
| `router/router_1/config.json` | Add `reestablish_seconds` |
| `router/router_2/config.json` | Same |
| `simulators/upstream_host/upstream_host_1/config.json` | Add `ping_0800_seconds` |
| `shared/iso_utils.py` | Add `build_0800()`, `build_0810()` |
| `router/main.py` | Phase 3–5: upstream_ref, 0800 pass-through, 0810 routing, session loop |
| `simulators/downstream_host/main.py` | Phase 6: handle 0800, reply 0810 |
| `simulators/upstream_host/main.py` | Phase 7: keepalive sender, 0810 handling |
