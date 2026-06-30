# Build Session Result — xv3 Post-Build Learnings

## What happened in this session

`build_router.md` was used to rebuild the router from scratch (xv2 → xv3). The code was
produced but did not work. A series of bugs were found and fixed through the monitor UI,
log inspection, and code reading. This document captures the root causes, fixes, and
recommended spec updates so the next rebuild starts clean.

---

## Bugs found and fixed (ordered by impact)

### 1. Socket timeout persisting after `create_connection` ⚠️ MOST SUBTLE

**Location:** `simulators/upstream_host/main.py` — `_client_connect_loop`

**Root cause:** `socket.create_connection(addr, timeout=5)` sets a 5-second timeout on the
**returned socket**, not only on the connection attempt. After a successful connect the socket
remained in 5-second timeout mode. Every `recv()` that blocked longer than 5 seconds raised
`socket.timeout` (an `OSError`), which `_recv_exact` converted to `ConnectionError`, which the
receive loop treated as a disconnect. The symptom was the upstream disconnecting **exactly 5
seconds** after the last received message (one 0810) — silently, with no error logged.

**Fix:**
```python
sock = socket.create_connection((host, port), timeout=5)
sock.settimeout(None)   # switch to blocking; timeout=5 above is connect-only
```

**Why it's easy to miss:** The timeout intent was "fail fast if the router isn't reachable",
which is correct, but `create_connection` applies it to the full socket lifetime. The
reconnect pattern (connect, disconnect ~5s later, connect, …) looked exactly like a
connection-management bug rather than a socket API footgun.

**Spec change needed:** Document this in the upstream simulator spec and add a note under
"Common pitfalls" in `build_router.md`.

---

### 2. `_keepalive_loop` waited full interval before first send

**Location:** `simulators/upstream_host/main.py` — `_keepalive_loop`

**Root cause:** The loop slept `ping_0800_seconds` (30 s) **before** sending the first 0800.
On a fresh connection the system appeared dead for 30 seconds with zero counters.

**Fix:** Send immediately, then wait:
```python
def _keepalive_loop(self, conn, disc_evt):
    while not disc_evt.is_set() and not self.stop_event.is_set():
        try:
            write_message(conn, build_0800(self.spec), self.framing)
            self.stats.record_sent()
        except OSError:
            return
        # interruptible wait for the rest of the interval
        elapsed = 0.0
        while elapsed < self.ping_0800_seconds:
            if disc_evt.is_set() or self.stop_event.is_set():
                return
            time.sleep(min(1.0, self.ping_0800_seconds - elapsed))
            elapsed += 1.0
```

**Spec change needed:** Update the `_keepalive_loop` pseudocode in `build_router.md` to
show send-first.

---

### 3. `RouterConfig.from_file()` did not exclude `is_active`

**Location:** `router/config.py` — `RouterConfig.from_file()`

**Root cause:** The `extra_kwargs` dict comprehension filtered out known structured keys
(`upstream`, `downstream`, `crypto`, `iso_spec`, `type`) but not `is_active`, which was
added to all config.json files in this session. Passing `is_active` as a kwarg to the
`RouterConfig` dataclass produced `TypeError: __init__() got an unexpected keyword argument
'is_active'`.

**Fix:** Add `"is_active"` to the exclusion set:
```python
extra_kwargs = {
    k: v
    for k, v in data.items()
    if k not in ("upstream", "downstream", "crypto", "iso_spec", "type", "is_active")
}
```

**Broader lesson:** Every JSON field that exists in the config but is NOT a `RouterConfig`
dataclass attribute must be listed here. The exclusion set is the canonical list of "JSON
keys that are consumed by the parsing logic above and must not be passed as kwargs." Any
future addition to config.json that is handled explicitly (e.g., a `logging` block, an
`auth` section) must be added to this set at the same time.

**Spec change needed:** Document the exclusion set explicitly in `RouterConfig.from_file()`
spec. Add `is_active` to the config.json field list.

---

### 4. Invalid JSON boolean syntax in config.json

**Location:** `router/router_2/config.json`

**Root cause:** `"is_active": True` used Python syntax. JSON requires lowercase: `true` /
`false`. The router process exited immediately at startup with `json.JSONDecodeError`.

**Fix:** `"is_active": false`

**Spec change needed:** Add a note in the config.json examples section: JSON booleans are
lowercase (`true`, `false`). Python `True`/`False` will silently produce bad configs when
edited by hand.

---

### 5. Unguarded dispatch calls in `_downstream_receiver`

**Location:** `router/session.py` — `_downstream_receiver`
exception guard. Any non-OSError (e.g., from `iso8583.encode`, internal logic error) would
propagate up, kill the ds-receiver daemon thread with no log, and leave the session silently
broken — the router would still accept upstream messages and forward them to the downstream,
but no responses would ever come back.

**Fix:**
```python
try:
    if resp.get("t") == "0810":
        self._forward_0810(resp)
    else:
        self.dispatcher.handle_response(resp)
except Exception:
    logger.exception("unexpected error dispatching downstream message mti=%s", resp.get("t"))
```

**Spec change needed:** Add this guard to the `_downstream_receiver` pseudocode in
`build_router.md`. The general principle — daemon threads that are the sole reader of a
connection must never die silently — is worth calling out explicitly in the design
principles.

---

### 6. `is_active` field missing from spec and config.json examples

**Root cause:** The spec had no mechanism for the monitor to decide which actors to launch.
When the project has multiple router instances (router_1, router_1.01, router_2) and
multiple upstreams, "Start All" launching everything at once causes port conflicts or
requires all simulators to be running.

**Fix (monitor):** `discover_actors()` reads `is_active` from each config.json (defaulting
to `True`). `_start_all_worker` skips actors where `not actor["is_active"]`.

**Fix (config.json):** Every config.json file gets `"is_active": true|false`.

**Spec change needed:** Document `is_active` in the config.json field tables for router,
upstream, downstream, and crypto. Add to `RouterConfig.from_file()` exclusion set note
(see bug 3).

---

## `build_router.md` spec update recommendations

| Section | Change |
|---|---|
| `RouterConfig` config.json fields | Add `"is_active": bool (default true)` |
| `RouterConfig.from_file()` | Document the exclusion set; name every field explicitly |
| `_keepalive_loop` pseudocode | Send first, then wait |
| Upstream simulator `_client_connect_loop` | Add `sock.settimeout(None)` immediately after `create_connection` |
| `_downstream_receiver` pseudocode | Wrap dispatch calls in `try/except Exception` |
| Monitor `_start_all_worker` | Show `is_active` filter |
| New section: "Common pitfalls" | Socket timeout, JSON booleans, exclusion set |

---

## Refactoring hints — path toward C++

The spec already states the blocking-threads model was chosen for C++ portability. These
observations sharpen where the boundary will matter most.

### Router core is the right C++ target; leave simulators in Python

The downstream host, upstream simulator, and crypto host will be replaced by real external
systems. They are pure development scaffolding. Only `router/` needs to perform at volume.

### `_OrEvent` is a Python workaround — use atomics in C++

```python
class _OrEvent:
    def is_set(self): return any(e.is_set() for e in self._events)
```

This lets `UpstreamServer.accept()` / `UpstreamClient.connect()` wake on either
`stop_event` or `reconnect_event` without those APIs knowing about both. In C++,
use a single `std::atomic<bool> stop_flag` that is set by either condition, or a
`std::condition_variable` with a compound predicate. The Python workaround adds a poll
loop (checking `is_set()` every 1 s via socket timeout); C++ can do it edge-triggered.

### Dispatcher maps directly to a thread pool + concurrent queue

`Dispatcher` is:
- A bounded `queue.Queue(maxsize=cfg.queue_maxsize)` → C++: `std::deque` + `std::mutex` +
  `std::condition_variable` with max-size check, or a lock-free bounded MPMC queue
- N worker threads draining it → `std::thread` pool, launched once
- `pending` map (STAN → `PendingEntry`) with a `threading.Lock` → `std::unordered_map` +
  `std::mutex`; for high volume consider sharded locks (e.g., 16 buckets)
- `_pending_reaper` thread: scans `pending` for expired entries every second. In C++, a
  sorted structure (e.g., a min-heap keyed on deadline) avoids a full linear scan

### `write_lock` per upstream connection is correct and cheap

Each upstream connection gets one `threading.Lock` (= `std::mutex`). The ds-receiver and
any worker writing an 0110 back to the same upstream both acquire it before `sendall`.
This is the right model — no per-message allocation overhead.

### Framing is the hot path in the router

`_recv_exact` loops on `recv()`. In C++ this becomes a tight `while (remaining > 0)` loop
around `recv()` in a dedicated read thread per connection. No heap allocation inside the
loop (stack buffer or pre-allocated `std::array<uint8_t, MAX_MSG_SIZE>`). The ISO 8583
decode (currently done with pyiso8583) will need a C++ equivalent; the field map is small
enough to fit in a lookup table.

### Session teardown race is inherent to the dual-socket model

`_teardown` must close the upstream socket (waking the up-server thread) AND close the
downstream from-socket (waking ds-receiver) before joining both threads. In C++, the
equivalent is `shutdown(fd, SHUT_RDWR)` + `join()`. Using `close()` directly is technically
a race on Linux when another thread holds the fd (the fd could be reused). Prefer
`shutdown()` to unblock blocked `recv()` calls, then `close()` after all threads exit.

### Pending reaper and clock source

The reaper uses `time.time()` (wall clock). For a C++ port, `std::chrono::steady_clock` is
better — monotonic, unaffected by NTP adjustments. All TTL calculations should be relative
to `steady_clock::now()`.

---

## What worked well and should be preserved

- **`_recv_exact` normalizing OSError → ConnectionError**: Every caller of `read_message` /
  `read_response` catches exactly one exception type regardless of whether the disconnect
  was remote (EOF) or local (teardown closed the fd). This must be preserved in C++ by
  catching both `recv()` returning 0 and `recv()` returning `EBADF`/`EINTR` in one place.

- **`DownstreamConnection.close()` closing both sockets**: The pair (to_sock, from_sock) is
  always closed together. Splitting this into separate calls at two different callsites
  would introduce teardown ordering bugs.

- **`_wait_for_from_conn` polling**: The IMS dual-socket model has an inherent race — the
  `from_conn` registration (via 0x80 frame) can arrive after the first request on `to_conn`.
  The 2-second polling loop handles this without locks between accept threads. In C++, a
  `std::condition_variable` wait on the `from_connections` map would be cleaner.

- **Session-level reconnect event separate from process-level stop event**: `reconnect_event`
  is created fresh per session; `stop_event` lives for the process lifetime. This separation
  means a session tear-down does not kill the process — the reconnect loop in `run()` just
  creates a new session. In C++, model these as two separate `std::atomic<bool>` flags.
