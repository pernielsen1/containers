# ISO 8583 Router — Build Specification

## Purpose

Build a Python application that routes ISO 8583 payment messages between one or more upstream clients (card networks / acquirers) and a downstream IMS Connect host (authorization system). A crypto host handles EMV cryptographic validation. A web-based monitor manages and observes all components.

All packages are already available (`pyiso8583`, `flask`, `requests`, `pycryptodome`).

### Design principles (non-negotiable)

- **No process exits without releasing its sockets.** A malfunctioning actor must never retain
  a lock on a TCP port — all socket close paths run even on error/exception exit.
- **Thread-per-connection, blocking I/O, `threading.Lock` for shared state** (pending-request
  map, stats counters) — chosen deliberately over `asyncio` so the implementation maps 1:1 to a
  future C++ port (`std::thread` + `std::mutex` + blocking `recv`/`send`). `asyncio` would need a
  full conceptual rewrite in C++; blocking threads do not.
- **The router must not stall on crypto calls.** Each upstream connection accepts the next
  message as soon as the current one is handed to a worker — it does not block waiting for that
  worker's `crypto_host` round-trip to finish. This rules out a naive "call crypto synchronously
  in the read loop" design; it is why `Dispatcher` exists as a bounded worker pool with a
  configurable `worker_threads` count rather than spawning a thread per message (thread-per-message
  does not scale at high volume).
- **Bounded resources, not unbounded growth.** The dispatcher queue and the in-flight pending map
  must have a ceiling. When the system is overloaded (slow/dead downstream or crypto host), the
  queue blocks `submit()` rather than growing without limit — this throttles the upstream read
  loop naturally instead of risking OOM during an extended outage. A bounded queue also means an
  operator always has a finite, inspectable backlog to discard via the purge endpoint (see
  `Dispatcher.purge()`) when replaying stale traffic into a freshly-recovered downstream would do
  more harm than dropping it.
- **Command APIs default to localhost, and mutating routes are gate-able behind a shared secret.**
  `/stop`, `/log_level`, and `/dispatcher/purge` can stop, reconfigure, or drop in-flight traffic
  for an actor — they must not be reachable by default from anything other than the monitor on the
  same host.

---

## Repository layout

```
project/
├── requirements.txt
├── test_spec.json          # ISO 8583 field spec (pyiso8583 format)
├── pans_defined.json       # card data for simulators and crypto host
├── shared/
│   ├── __init__.py
│   ├── framing.py          # length-prefixed TCP framing
│   ├── ims_connect.py      # IMS Connect wire protocol
│   ├── iso_utils.py        # spec loader, f47 helpers, hex dump
│   ├── stats.py            # rolling-window message counters
│   ├── command_server.py   # Flask HTTP command/stats API (shared by all actors)
│   └── crypto_utils.py     # EMV crypto (ARQC, ARPC, PIN, CVV2, AAV)
├── router/
│   ├── __init__.py
│   ├── config.py           # RouterConfig dataclasses
│   ├── main.py             # entry point, reconnect loop
│   ├── session.py          # one live session (upstream + downstream + dispatcher)
│   ├── upstream.py         # UpstreamServer / UpstreamClient
│   ├── downstream.py       # DownstreamConnection (dual IMS socket)
│   ├── dispatcher.py       # worker pool, STAN rewrite, pending map
│   ├── crypto_client.py    # HTTP client for crypto host
│   ├── router_1/
│   │   └── config.json     # partner_a, primary instance
│   ├── router_1.01/
│   │   └── config.json     # partner_a, second instance (proves multi-router-per-partner)
│   └── router_2/
│       └── config.json     # partner_b
├── simulators/
│   ├── downstream_host/
│   │   ├── main.py
│   │   └── config.json
│   ├── upstream_host/
│   │   ├── main.py
│   │   └── config.json     (one config per upstream instance)
│   ├── upstream_1/
│   │   ├── config.json
│   │   └── input/
│   │       └── test_cases.csv
│   ├── upstream_2/
│   │   └── config.json
│   ├── upstream_3/          # feeds router_1.01, exercises the multi-router-per-partner path
│   │   ├── config.json
│   │   └── input/
│   └── crypto_host/
│       ├── main.py
│       └── config.json
├── monitor/
│   ├── main.py
│   └── static/
│       └── index.html
├── run/                     # one shell wrapper per actor instance + monitor lifecycle
│   ├── crypto_host.sh
│   ├── downstream_host.sh
│   ├── router_1.sh / router_2.sh
│   ├── upstream_1.sh / upstream_2.sh
│   ├── monitor.sh
│   └── kill_monitor.sh      # POST /stop, poll PID up to 30s, SIGKILL fallback
├── tests/
│   ├── test_framing.py        # length-prefix framing round-trip
│   ├── test_stats.py          # rolling-window counters
│   ├── test_command_server.py # /stats, /stop, /log_level, /logs
│   ├── test_crypto_utils.py   # ARQC/ARPC/PIN/CVV2/AAV against pans_defined.json keys
│   ├── test_router.py         # full-stack integration: 4 actors in-thread, CSV → 0100 → field 39
│   └── test_router_1_01.py    # connectivity + stats smoke test for the second partner_a router
├── f47.json                  # documents the field-47 JSON schema (see Crypto section)
└── test_csv_files/
    └── test.csv
```

---

## Dependencies

```
pyiso8583>=4.0.0
flask>=3.0.0
requests>=2.31.0
pycryptodome>=3.20.0
```

---

## Shared modules

### `shared/framing.py`

Reads and writes length-prefixed TCP messages. No state; two pure functions.

```python
def read_message(sock, cfg) -> bytes:
    """cfg keys: header_hex (str, may be ""), length_field_bytes (int),
    length_field_type ("BIG_ENDIAN"|"LITTLE_ENDIAN"|"ASCII"|"EBCDIC"),
    max_message_bytes (int, optional — default 65536).
    Reads optional fixed header, reads length field, reads payload.
    Raises ConnectionError immediately if the decoded length exceeds max_message_bytes,
    instead of letting _recv_exact block waiting for bytes that may never arrive — a corrupt
    or hostile length field must fail fast and drop the connection, not hang its read thread
    forever."""

def write_message(sock, data: bytes, cfg) -> None:
    """Writes header + encoded length + data in one sendall."""
```

Internal helper `_recv_exact(sock, n)` loops on `sock.recv` until `n` bytes are collected; raises `ConnectionError` on empty read or OSError.

### `shared/ims_connect.py`

IMS Connect wire protocol. The downstream host uses a **dual-socket** model: one socket sends requests (to-socket), one receives responses (from-socket).

Constants:
- `IRM_HEADER_LEN = 28`
- `PING_TRANSCODE = to_ebcdic("PING0001", 8)`

```python
def to_ebcdic(s: str, length: int) -> bytes:
    """EBCDIC-encode and left-pad/truncate to exactly `length` bytes."""

def build_frame(irm_f0, irm_id, client_id, mti=None, data=b"", transcode=None) -> bytes:
    """Build a complete IMS Connect wire frame: 4-byte big-endian length (payload only)
    + 28-byte IMS header + optional TRANS_CODE (8 bytes EBCDIC) + data.
    irm_f0=0x80 → resume TPIPE (no data). irm_f0=0x00 → normal request.
    transcode defaults to TRAN+mti when data is present."""

def write_response(sock, data: bytes) -> None:
    """Send downstream response: 4-byte big-endian length + data."""

def read_response(sock) -> bytes:
    """Read downstream response. Returns ISO data bytes only (strips length prefix)."""

def read_request(sock) -> tuple:
    """Read IMS Connect request. Returns (irm_f0, client_id_bytes, transcode_bytes, iso_data_bytes)."""
```

Wire format of `build_frame`:
```
[4B: payload_len big-endian]
[2B: IRM_HEADER_LEN=28 big-endian]
[1B: 0x04]
[1B: irm_f0]
[8B: irm_id EBCDIC]
[4B: 0x00 0x00 0x00 0x00]      # IRM_NAK_RSNCDE(2) + IRM_RES(2)
[4B: 0x00 0x15 0x10 0x01]      # IRM_F5, IRM_TIMER, IRM_SOCT, IRM_ES
[8B: client_id EBCDIC]
[8B: transcode EBCDIC]          # only when data present
[N bytes: iso_data]             # only when data present
```

### `shared/iso_utils.py`

```python
def load_spec(path: str) -> dict:          # JSON load of pyiso8583 spec file
def build_0800(spec) -> bytes:             # encode {"t":"0800","24":"100"}
def build_0810(f24: str, spec) -> bytes:   # encode {"t":"0810","24": f24}
def f47_encode(data: dict) -> str:         # json.dumps compact
def f47_decode(value: str) -> dict:        # json.loads, empty dict on error
def hex_dump(label, data, logger):         # logs hex only at DEBUG level
```

### `shared/stats.py`

Thread-safe rolling counters over windows `[30, 60, 180, 1800]` seconds. Uses `collections.deque`.

```python
class Stats:
    def __init__(self, yellow_threshold_seconds=None)
    def set_connection(self, name: str, connected: bool)  # e.g. "upstream", "downstream"
    def set_gauge(self, name: str, value) -> None          # arbitrary named point-in-time value,
                                                             # e.g. "queue_depth", "pending_count"
    def record_sent(self)
    def record_recv(self)
    def snapshot(self) -> dict:
        # keys: sent_total, recv_total,
        #       sent_30s, recv_30s, sent_60s, recv_60s, sent_180s, recv_180s, sent_1800s, recv_1800s,
        #       seconds_since_last_recv (float|None), last_recv_datetime (str HH:MM:SS|None),
        #       yellow_threshold_seconds (if set),
        #       connections (dict name→bool, only if any set_connection calls made),
        #       gauges (dict name→value, only if any set_gauge calls made)
```

### `shared/log_buffer.py`

```python
class LogBuffer(logging.Handler):
    """Captures last N log lines in a deque. Installed on root logger by CommandServer."""
    def __init__(self, maxlen=2000)
    def get_lines(self) -> list[str]
```

### `shared/command_server.py`

Every actor (router, simulators) gets a `CommandServer` that serves HTTP on its `command_port`.

```python
class CommandServer:
    def __init__(self, port, stats: Stats, stop_event: threading.Event,
                 bind_host: str = "127.0.0.1", auth_token: str | None = None)
    def register(self, path, methods=("GET",), protected: bool = False) -> decorator
        # add custom routes; protected=True requires header X-Router-Auth == auth_token
        # (no-op check when auth_token is None — see Known limitations)
    def start(self)                                            # runs Flask in daemon thread
```

Built-in routes:
- `GET /stats` → `stats.snapshot()` as JSON (unprotected — read-only)
- `GET|POST /stop` → **protected**; sets `stop_event`, returns `{"status":"stopping"}`
- `GET|POST /log_level` → **protected** on POST only; GET returns current level
- `GET /logs` → JSON array of log lines; `?format=text` returns plain text (unprotected —
  read-only, but see Known limitations re: DEBUG-level data exposure)

LogBuffer is installed on the root logger inside `__init__`. Default bind is `127.0.0.1`, not
`0.0.0.0` — the monitor reaches every actor over loopback since all actors run on the same host;
set `bind_host` explicitly only when actors are deliberately split across hosts.

### `shared/crypto_utils.py`

MasterCard M/Chip EMV operations. All functions are pure (no I/O).

| Function | Purpose |
|---|---|
| `derive_udk(imk_hex, pan, pan_seq) → str` | EMV Option A UDK derivation |
| `derive_session_key(udk_hex, atc_hex) → str` | ATC-based session key |
| `verify_arqc(pan, pan_seq, imk_hex, f55: dict) → bool` | Retail MAC ARQC check |
| `calculate_arpc_method1(arqc_hex, arc_hex, sk_hex) → bytes` | ARPC Method 1 |
| `verify_pin(pan, f52_b64, pek_hex, reference_pin) → bool` | ISO 9564-1 Format-0 |
| `encode_pin_block_format0(pin, pan) → bytes` | Build cleartext PIN block (tests) |
| `encrypt_pin_block(plain, pek_hex) → bytes` | 3DES encrypt PIN block |
| `verify_cvv2(pan, expiry_mmyy, cvv2, cvk_hex) → bool` | MasterCard CVV2 |
| `compute_cvv2(pan, expiry_mmyy, cvk_hex) → str` | Compute CVV2 (tests) |
| `verify_aav(f47_data, aav_key_hex, pan) → bool` | HMAC-SHA1 AAV |
| `compute_aav(f47_data, aav_key_hex, pan) → str` | Compute AAV (tests) |

f55 dict keys for ARQC: `amount_auth`, `amount_other`, `terminal_country`, `terminal_verification_results`, `currency_code`, `transaction_date`, `transaction_type`, `unpredictable_number`, `aip`, `atc`, `cryptogram` (all hex strings).

### `f47.json` (field-47 JSON schema reference)

Field 47 carries everything `crypto_host` needs in one JSON blob, decoded/encoded via
`iso_utils.f47_decode`/`f47_encode`. Schema (documented in `f47.json` at the project root):

```json
{
  "f47": {
    "message_type": "string (0100|0110)",
    "f14": "string (expiry date, MMYY)",
    "f52": "string (PIN block encrypted with PEK, base64)",
    "cvv2": "string (3-digit CVV2)",
    "aav": "string (AAV, base64 — HMAC-SHA1)",
    "response_code": "string (00=OK, 55=wrong PIN, 82=bad ARQC, N7=bad CVV2)",
    "f55": {
      "cryptogram": "ARQC hex (8 bytes)",
      "arpc": "ARPC base64 (8 bytes — present on 0110 response)",
      "cid": "Cryptogram Information Data, 1 byte hex",
      "atc": "Application Transaction Counter, 2 bytes hex",
      "aip": "Application Interchange Profile, 2 bytes hex",
      "iad": "Issuer Application Data, variable hex",
      "amount_auth": "6 bytes BCD hex",
      "amount_other": "6 bytes BCD hex",
      "terminal_country": "2 bytes hex",
      "terminal_verification_results": "5 bytes hex",
      "currency_code": "2 bytes hex",
      "transaction_date": "YYMMDD, 3 bytes BCD hex",
      "transaction_type": "1 byte hex",
      "unpredictable_number": "4 bytes hex"
    }
  }
}
```

Any subset of `f52`/`cvv2`/`aav`/`f55` may be present — `crypto_host` only runs the checks for
keys that exist (see `_validate` logic below) and always stamps `response_code` on the way out.

---

## Router

### `router/config.py`

Dataclasses loaded from `config.json`.

```python
@dataclass
class Framing:
    header_hex: str
    length_field_type: str
    length_field_bytes: int
    def to_dict(self) -> dict  # adapter for shared/framing.py

@dataclass
class UpstreamConfig:
    port: int
    framing: Framing
    mode: str = "server"       # "server" | "client"
    host: str = "localhost"
    retry_seconds: int = 5

@dataclass
class DownstreamConfig:
    host: str
    port: int
    irm_id: bytes              # EBCDIC 8 bytes
    client_id: bytes           # EBCDIC 8 bytes

@dataclass
class CryptoConfig:
    host: str
    port: int

@dataclass
class RouterConfig:
    name: str
    command_port: int
    upstream: UpstreamConfig
    downstream: DownstreamConfig
    crypto: CryptoConfig
    iso_spec: str              # resolved absolute path
    partner_id: str = None
    log_level: str = "INFO"
    worker_threads: int = 8
    reestablish_seconds: int = 10
    yellow_threshold_seconds: int = 40
    queue_maxsize: int = 1000                    # Dispatcher._queue ceiling — submit() blocks past this
    pending_ttl_seconds: int = 30                # pending-reaper expiry for in-flight 0100/0120/0420
    crypto_breaker_threshold: int = 5             # consecutive crypto failures before breaker opens
    crypto_breaker_cooldown_seconds: int = 30     # how long the breaker stays open before retrying
    reconnect_jitter_seconds: float = 2.0         # random jitter added to reestablish_seconds waits
    command_bind_host: str = "127.0.0.1"          # CommandServer bind address
    command_auth_token: str = None                # shared secret for protected command routes

    @classmethod
    def from_file(cls, path: str) -> RouterConfig: ...
```

`from_file` resolves `iso_spec` relative to the config file's directory.
`irm_id` and `client_id` are loaded via `ims_connect.to_ebcdic(str, 8)`.

### `router/config.json` (example for `router_1`)

```json
{
  "name": "router_1",
  "type": "router",
  "partner_id": "partner_a",
  "log_level": "DEBUG",
  "command_port": 8080,
  "upstream": {
    "port": 5000,
    "framing": {
      "header_hex": "",
      "length_field_type": "ASCII",
      "length_field_bytes": 4
    }
  },
  "downstream": {
    "host": "localhost",
    "port": 5001,
    "irm_id": "IRM_ID01",
    "client_id": "CLIENT01"
  },
  "crypto": {
    "host": "localhost",
    "port": 5002
  },
  "iso_spec": "../../test_spec.json",
  "worker_threads": 8,
  "reestablish_seconds": 10,
  "yellow_threshold_seconds": 40
}
```

The resilience/security fields added to `RouterConfig` (`queue_maxsize`, `pending_ttl_seconds`,
`crypto_breaker_threshold`, `crypto_breaker_cooldown_seconds`, `reconnect_jitter_seconds`,
`command_bind_host`, `command_auth_token`) all have working defaults and are omitted from this
example — set them explicitly per router only when the defaults don't fit (e.g. a higher-TPS
partner needing a larger `queue_maxsize`, or `command_auth_token` once an actor's command port is
ever exposed beyond loopback).

A partner can run **more than one** router instance against the same downstream/crypto hosts —
`router_1` and `router_1.01` share `partner_id: "partner_a"` but use different `upstream.port`,
`command_port`, and `downstream.client_id` (each router/downstream pairing must use a distinct
EBCDIC `client_id` so `downstream_host` can pair the to/from sockets). The monitor's
`/api/routers_by_partner` groups by `partner_id` and sums stats across all routers sharing it.

### `router/upstream.py`

Two independent classes with the same return type `UpstreamConn = Tuple[socket, addr_tuple, threading.Lock]`.

```python
class UpstreamServer:
    """Listen on cfg.port. Created once outside the session loop (survives reconnects)."""
    def __init__(self, cfg: UpstreamConfig)
    def accept(self, stop_event) -> Optional[UpstreamConn]
        # Loops with 1-second timeout; returns None on stop or OSError
    def close(self)

class UpstreamClient:
    """Connect out to cfg.host:cfg.port, retrying every cfg.retry_seconds."""
    def __init__(self, cfg: UpstreamConfig)
    def connect(self, stop_event) -> Optional[UpstreamConn]

def read_upstream(conn, cfg: UpstreamConfig) -> bytes:
    return read_message(conn, cfg.framing.to_dict())

def write_upstream(conn, data: bytes, cfg: UpstreamConfig) -> None:
    write_message(conn, data, cfg.framing.to_dict())
```

### `router/downstream.py`

```python
class DownstreamConnection:
    """Dual-socket IMS session. Thread-safe send via internal Lock."""

    @classmethod
    def connect(cls, cfg: DownstreamConfig) -> DownstreamConnection:
        # 1. Connect to_sock to cfg.host:cfg.port
        # 2. Connect from_sock to cfg.host:cfg.port
        # 3. Send resume TPIPE on from_sock: build_frame(0x80, irm_id, client_id)
        # 4. Send pipe-cleaner ping on to_sock:
        #    data = "1234 clean the pipes".encode("cp500")
        #    build_frame(0x00, irm_id, client_id, transcode=PING_TRANSCODE, data=data)

    def send(self, frame: bytes) -> None:   # acquires lock, sendall on to_sock
    def recv(self) -> bytes:                # blocking read from from_sock via ims_connect.read_response
    def close(self) -> None                 # closes both sockets
```

### `router/crypto_client.py`

```python
class CryptoClient:
    def __init__(self, cfg: CryptoConfig, breaker_threshold: int = 5, breaker_cooldown_seconds: int = 30)
        # base URL = f"http://{cfg.host}:{cfg.port}"
        # uses requests.Session() (thread-safe)
        # breaker state: consecutive-failure counter + open-until timestamp, guarded by a Lock

    def validate(self, endpoint: str, pan: str, f47: str) -> str:
        # If the breaker is open (now < open_until): skip the HTTP call entirely, return ""
        #   immediately (same fallback already used for any other error) — keeps worker threads
        #   free to drain the queue with declines instead of stalling timeout=5s per message on
        #   a crypto_host that is known to be down.
        # Otherwise: POST {base}/{endpoint} with JSON {"f2": pan, "f47": f47}
        #   - success: reset the failure counter; return response["f47"]
        #   - failure: increment the failure counter; at breaker_threshold, open the breaker for
        #     breaker_cooldown_seconds (half-open retry once cooldown elapses)
        #   - any error path returns the original f47 unchanged
        # endpoint is "validate_0100" or "validate_0110"
        # timeout=5
```

`breaker_threshold` / `breaker_cooldown_seconds` come from `cfg.crypto_breaker_threshold` /
`cfg.crypto_breaker_cooldown_seconds` on `RouterConfig`.

### `router/dispatcher.py`

```python
@dataclass
class PendingEntry:
    up_conn: socket.socket
    up_write_lock: threading.Lock
    upstream_stan: str          # original STAN from upstream, restored in response
    created_at: float           # time.monotonic() at insert — used by the pending reaper

@dataclass
class RoutedMessage:
    req: dict                   # decoded ISO 8583 message
    up_conn: socket.socket
    up_write_lock: threading.Lock
    up_addr: tuple

class Dispatcher:
    """Worker pool. Routes 0100 upstream → crypto → downstream.
    Routes 0110/0130/0430 downstream → upstream (STAN lookup)."""

    def __init__(self, cfg, downstream, crypto, spec, stats, reconnect_event)
        # self._queue = queue.Queue(maxsize=cfg.queue_maxsize)  # bounded — see design principles
    def start(self)              # spawns cfg.worker_threads daemon workers + 1 pending-reaper thread
    def submit(self, msg: RoutedMessage) -> None
        # Blocking enqueue. Once the queue is at cfg.queue_maxsize this blocks the calling
        # upstream read thread — deliberate backpressure so memory stays bounded under a
        # sustained downstream/crypto outage, rather than growing the queue without limit.
    def handle_response(self, resp: dict)  # called from ds-receiver thread
    def purge(self) -> dict
        # Operator-triggered, NOT part of session teardown: drains self._queue without
        # processing and clears self._pending without sending responses. For when a stale
        # backlog built up during an outage and replaying it into a freshly-recovered
        # downstream would do more harm than dropping it (the network will simply retry
        # declined/timed-out transactions). Returns {"queue_dropped": N, "pending_dropped": M}.
        # Exposed via the protected POST /dispatcher/purge command route (see router/main.py).
    def drain_and_stop(self)     # sends None sentinels, joins workers + reaper (session teardown)
```

**STAN rewriting** — each router maintains its own counter (6-digit, wraps at 1,000,000):
- `_next_stan()` → zero-padded string e.g. `"000042"`
- On 0100: save `(upstream_conn, upstream_lock, upstream_stan, created_at)` keyed by `router_stan`; send to downstream with `router_stan` in field 11
- On 0110: look up `router_stan`, restore `upstream_stan` in field 11, forward back
- If a `router_stan` slot is still occupied when it would be reused (counter wrapped while the
  old entry was still outstanding), log at ERROR before overwriting it — the original request's
  caller will never get a reply. The pending reaper below is the primary defense against this;
  the log line exists to catch cases where `pending_ttl_seconds` is set too long for the
  observed TPS.

**Pending reaper** (`_pending_reaper`, daemon thread started in `start()` alongside the workers):
- Wakes every 1s, scans `self._pending` for entries older than `cfg.pending_ttl_seconds`
- For each expired entry: pops it, builds a local decline (`f39="91"`, no crypto/downstream
  round-trip) and writes it to `entry.up_conn` under `entry.up_write_lock`, logs a warning
- Exists because a `PendingEntry` is inserted *before* `downstream.send()` — if that send fails
  (downstream down) the entry would otherwise never be popped, since no `handle_response` will
  ever arrive for it, leaving the upstream caller waiting forever for a reply that is never
  coming

**Queue depth / pending count**: after every `submit()`/dequeue and every pending insert/pop,
the dispatcher calls `stats.set_gauge("queue_depth", self._queue.qsize())` and
`stats.set_gauge("pending_count", len(self._pending))`, so both surface in `/stats` and the
monitor UI.

**`_process(msg)` logic** (runs in worker thread):
1. Extract `mti`, `pan` (field 2), `upstream_stan` (field 11)
2. Generate `router_stan`
3. If `mti == "0100"`: call `crypto.validate("validate_0100", pan, req.get("47",""))`; put result in `fwd["47"]` if truthy
4. Encode `fwd` with pyiso8583
5. Insert `PendingEntry` into `self._pending[router_stan]`
6. Build IMS frame via `ims_connect.build_frame(0x00, irm_id, client_id, fwd["t"], encoded)`
7. `downstream.send(frame)` — OSError propagates to worker → sets `reconnect_event`

**`handle_response(resp)` logic** (runs in ds-receiver thread):
1. If `mti == "0810"`: return immediately (handled separately by session)
2. If `mti` not in `("0110", "0130", "0430")`: log warning, return
3. Look up `entry = self._pending.pop(router_stan, None)`
4. Restore `fwd["11"] = entry.upstream_stan`
5. If `mti == "0110"`: call `crypto.validate("validate_0110", pan, resp.get("47",""))`; update `fwd["47"]`
6. Encode and write to `entry.up_conn` under `entry.up_write_lock`

### `router/session.py`

```python
class RouterSession:
    """One live connection session. Owns ds-receiver thread and up-server/client thread."""

    @classmethod
    def connect(cls, cfg, stats, stop_event, srv_sock) -> RouterSession:
        # 1. DownstreamConnection.connect(cfg.downstream)  # raises OSError → caller retries
        # 2. stats.set_connection("downstream", True)
        # 3. Build CryptoClient, Dispatcher
        # 4. Return new instance

    def run_until_disconnect(self, srv_sock=None) -> None:
        # 1. dispatcher.start()
        # 2. Start ds_thread → _downstream_receiver()
        # 3. Start up_thread → _server_upstream_loop(srv_sock) or _client_upstream_loop()
        # 4. Loop: wait on reconnect_event or stop_event (1s timeout)
        # 5. _teardown(up_thread)
```

**`_handle_upstream(conn, addr, write_lock)`** (read loop for one upstream):
- Sets `stats.set_connection("upstream", True)`
- Stores conn/lock in `_upstream_ref` (protected by `_up_ref_lock`)
- Reads frames → decodes ISO 8583
- MTI routing:
  - `0100 / 0120 / 0420` → `dispatcher.submit(RoutedMessage(...))`
  - `0800` → `_forward_0800(...)` (re-encode, wrap in IMS frame, send to downstream)
  - other → log warning
- On `ConnectionError`: sets `reconnect_event`
- On exit: `stats.set_connection("upstream", False)`, clears `_upstream_ref`

**`_downstream_receiver()`**:
- Loops calling `downstream.recv()`
- Skips frames whose first 4 bytes == `"PING".encode("cp500")`
- Decodes ISO 8583
- MTI `0810` → `_forward_0810(resp)` (re-encode, write to upstream via `_upstream_ref`)
- Other → `dispatcher.handle_response(resp)`
- `ConnectionError` → `stats.set_connection("downstream", False)`, sets `reconnect_event`

**`_teardown(up_thread)`**:
1. `dispatcher.drain_and_stop()`
2. Close upstream conn if present
3. `downstream.close()`
4. `up_thread.join(timeout=5)`

### `router/main.py`

```python
def load_config(path=None) -> (RouterConfig, config_base_dir):
    # default: router_1/config.json relative to main.py

def run(cfg=None, stop_event=None, stats=None, _config_base=None):
    # 1. Create Stats, CommandServer(bind_host=cfg.command_bind_host, auth_token=cfg.command_auth_token); start it
    #    Register protected POST /dispatcher/purge → current session's dispatcher.purge()
    #    (re-pointed at the new Dispatcher on each reconnect, since a fresh one is created per session)
    # 2. If upstream.mode == "server": create UpstreamServer (lives outside session loop)
    # 3. Main loop (while not stop_event):
    #    a. RouterSession.connect(...) — catch OSError → wait reestablish_seconds + jitter, continue
    #    b. session.run_until_disconnect(srv_sock)
    #    c. If not stop_event: wait reestablish_seconds + random.uniform(0, cfg.reconnect_jitter_seconds)
    #       (jitter avoids multiple routers sharing a downstream/crypto host reconnecting in lockstep)

if __name__ == "__main__":
    # argparse --config
    run(cfg=cfg, _config_base=config_base)
```

---

## Simulators

All simulators share the same pattern:
- Load `config.json` from their own directory
- Create `Stats` + `CommandServer`; start both
- Expose custom routes via `cmd.register(path, methods)`

### `simulators/downstream_host/main.py`

Simulates an IMS Connect authorization host.

**Config:**
```json
{
  "name": "downstream_host",
  "type": "downstream",
  "port": 5001,
  "command_port": 8081,
  "iso_spec": "../../test_spec.json",
  "pans_defined": "../../pans_defined.json",
  "yellow_threshold_seconds": 40
}
```

**Architecture:**
- Single listen socket. Each accepted connection is dispatched by the first IMS frame:
  - `irm_f0 == 0x80` → **from-conn** (receives responses to upstream)
  - `irm_f0 == 0x00` → **to-conn** (receives requests from router)
- `from_connections` dict: `client_id_bytes → Queue` — maps router identity to its send queue
- `_handle_from_conn`: registers queue, loops `queue.get()` → `ims_connect.write_response(conn, item)`
- `_handle_to_conn`: loops `ims_connect.read_request(conn)` → `_route_frame(...)`
- `_route_frame`:
  - `PING_TRANSCODE` → send `"PING"+"PIPES cleaned"` encoded cp500 to from-conn queue
  - `0800` → encode 0810, put on queue
  - `0120` → 0130 with rc=00
  - `0420` → 0430 with rc=00
  - `0100` → `_process_0100(req, pans)`:
    - PAN not in `pans_defined` → rc=01
    - `f47_decode(req["47"])["crypto_result"]` not True → rc=01
    - else → rc=00, generate sequential 6-digit auth code (field 38)

**`pans_defined.json`** is a dict keyed by PAN string; downstream host only uses key presence.

### `simulators/upstream_host/main.py`

Simulates an upstream card network client. Sends ISO 8583 0100s from a CSV, collects 0110 responses.

**Config** (instance-specific, e.g. `upstream_1/config.json`):
```json
{
  "name": "upstream_1",
  "type": "upstream",
  "command_port": 8083,
  "router": { "host": "localhost", "port": 5000 },
  "framing": { "header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4 },
  "iso_spec": "../../test_spec.json",
  "input_dir": "input",
  "ping_0800_seconds": 30,
  "yellow_threshold_seconds": 40
}
```

**Modes:**
- `mode: "client"` (default) — connects out to router, reconnects on disconnect
- `mode: "server"` — listens; router connects to it

**Custom command routes:**
- `POST /upload` — multipart file upload; saves to `input_dir/test_cases.csv`
- `GET /start` — reads CSV, launches `send_loop` in daemon thread; returns `{"rows": N}`
- `GET /results` — returns list of result dicts

**`send_loop(conn, rows)`:**
- For each row: build ISO 8583 0100 from CSV columns matching spec field keys
- Assign sequential STAN (field 11); store row in `pending[stan]`
- `write_message(conn, encoded, framing)`; sleep 20ms between messages

**`receive_loop(conn, disc_evt)`:**
- Reads frames, decodes; ignores 0810
- On 0110/0130/0430: pops `pending[stan]`, merges response fields as `resp_<field>` prefix, appends to `results`

**Keepalive:** daemon thread sends `build_0800(spec)` every `ping_0800_seconds`.

**CSV format:**
```
2;3;4;11;expected_39
4111111111111111;000000;000000000100;000001;00
```
Semicolon-delimited, utf-8-sig encoding. Column names are ISO 8583 field numbers. Field 11 (STAN) is overwritten by the sender. Non-matching columns are silently ignored.

### `simulators/crypto_host/main.py`

Stateless HTTP service for cryptographic validation.

**Config:**
```json
{
  "name": "crypto_host",
  "type": "crypto",
  "port": 5002,
  "command_port": 8082,
  "pans_defined": "../../pans_defined.json",
  "iso_spec": "../../test_spec.json",
  "yellow_threshold_seconds": 60
}
```

**Routes (additional to command server):**
- `POST /validate_0100` — body `{"f2": pan, "f47": f47_json_str}` → `{"f47": enriched_f47}`
- `POST /validate_0110` — same signature; computes ARPC

**`_validate(pan, f47_str, pans)` logic:**
1. Decode f47 JSON string
2. PAN not in pans → set `response_code = "14"`, return
3. If `f52` present → `verify_pin`; failure → rc=55
4. If `f55` present and `message_type == "0100"` and rc==00 → `verify_arqc`; failure → rc=82
5. If `f55` present and `message_type == "0110"` → `calculate_arpc_method1`; store `arpc` (base64) in `f55`
6. If `cvv2` present and rc==00 → `verify_cvv2`; failure → rc=N7
7. If `aav` present and rc==00 → `verify_aav`; failure → rc=82
8. Set `data["response_code"] = response_code`; return `f47_encode(data)`

The router always calls crypto regardless of whether f47/f55 is present; fallback returns original f47.

---

## Monitor

### `monitor/main.py`

Flask app on port 8090 (default, `--port` arg). Manages and proxies all actors.

**Actor discovery** (`discover_actors()`):
- Walk entire project tree looking for `config.json` files
- Skip `monitor/` directory
- Load each config; require `name` and `type` in `SCRIPTS_BY_TYPE`
- `SCRIPTS_BY_TYPE = {"router": "router/main.py", "upstream": "simulators/upstream_host/main.py", "downstream": "simulators/downstream_host/main.py", "crypto": "simulators/crypto_host/main.py"}`
- Actors requiring `--config` arg: `{"router", "upstream"}`
- Startup order: crypto(0) → downstream(1) → router(2) → upstream(3)

**Monitor API routes:**
| Route | Purpose |
|---|---|
| `GET /` | Serve `static/index.html` |
| `GET /api/actors` | Ordered list of all actors with name/type/command_port |
| `GET /api/routers_by_partner` | Dict `partner_id → [{name, command_port}]` |
| `GET /api/status` | Parallel health check; green/yellow/red per actor |
| `GET /api/starting` | `{"starting": bool}` |
| `GET /api/csv_files` | List CSVs from `test_csv_files/` and each upstream's `input/` dir |
| `POST /api/actor/<name>/launch` | Start subprocess if not running |
| `POST /api/actor/<name>/stop` | Proxy to actor's `/stop` |
| `GET /api/actor/<name>/stats` | Proxy to actor's `/stats` |
| `GET /api/actor/<name>/start` | Proxy to actor's `/start` (upstream only) |
| `GET /api/actor/<name>/results` | Proxy to actor's `/results` |
| `GET|POST /api/actor/<name>/log_level` | Proxy log level |
| `GET /api/actor/<name>/logs` | Proxy logs; `?format=text` for plain text |
| `POST /api/actor/<name>/upload` | Proxy multipart CSV upload |
| `POST /api/actor/<name>/upload_path` | Upload by relative project path `{"path": "..."}` |
| `POST /api/actor/<name>/dispatcher/purge` | Router only; proxies to the router's protected `/dispatcher/purge`, forwarding the actor's own `command_auth_token` as the `X-Router-Auth` header |
| `POST /api/start_all` | Start actors in order, waiting up to 10s each for readiness |
| `POST /api/stop_all` | Stop actors in reverse order |
| `POST /stop` | Stop monitor process (terminates all managed subprocesses) |

**Status logic** (per actor): fetch `/stats` → if `yellow_threshold_seconds` present, check `seconds_since_last_recv`; yellow if None or above threshold; green otherwise. Red if unreachable.

**Subprocess management:** `_processes` dict `name → Popen`. `atexit` handler terminates all on exit.

**Quiet logs:** every actor (monitor, crypto_host, upstream_host, and `CommandServer` itself) sets
`logging.getLogger("werkzeug").setLevel(logging.ERROR)` — Flask's default per-request access log
(`GET /api/status HTTP/1.1 200`) would otherwise flood the console every 2 seconds once the
monitor's polling loop is running in the background.

### `monitor/static/index.html`

Single-page vanilla JS app (no build step, no framework).

**Layout:**
- Header: title + "Start All" / "Stop All" buttons + optional "Starting actors…" spinner
- Router Partners section: partner groups, each showing aggregate 30s/total stats and a grid of compact router cards
- Simulators section: cards for crypto, downstream, upstream actors
- Test Runner panel: upstream selector, CSV picker (project files dropdown or file browse), Upload + Start buttons, results table

**Per-actor card (full size):** status dot, connection dots (router only: upstream + downstream), 30s/60s and total sent/recv counters, last-recv time, log-level selector, Logs / Start / Stop buttons. Router cards additionally show `queue_depth`/`pending_count` gauges (from `/stats` → `gauges`) and a **Purge Queue** button (confirmation required) — calls the purge proxy route to drop a stale backlog after a downstream/crypto outage without restarting the router.

**Polling:** `/api/status` + `/api/starting` every 2 seconds; `/api/actor/<name>/stats` per live actor.

**Results table columns:** PAN, RC (green if "00"), Auth code (field 38), Field 47 (truncated display).

**CSV picker default directory:** `GET /api/csv_files` lists `test_csv_files/*.csv` plus each
upstream's own `input/` dir — both resolved as project-relative paths, never the browser's native
file dialog default. This matters because the app runs inside WSL while the user works from a
Windows desktop; a plain `<input type="file">` would default to a Windows folder, so picking from
the project-relative dropdown (or the `/upload` proxy) is the supported path for files that
already live in the repo.

**Log viewer modal:** fetches `/logs`, auto-refreshes every 2s, export to file.

---

## `test_spec.json` (ISO 8583 field spec)

Fields used by the router and simulators:

| Field | Type | Len | Description |
|---|---|---|---|
| `h` | ascii fixed 0 | header |
| `t` | ascii fixed 4 | MTI |
| `p` | binary fixed 8 | Primary Bitmap |
| `1` | binary fixed 8 | Secondary Bitmap |
| `2` | ascii LLVAR 19 | PAN |
| `3` | ascii fixed 6 | Processing Code |
| `4` | ascii fixed 12 | Amount |
| `11` | ascii fixed 6 | STAN |
| `14` | ascii fixed 4 | Expiry Date (MMYY) |
| `24` | ascii fixed 3 | Network International ID |
| `37` | ascii fixed 12 | Retrieval Reference Number |
| `38` | ascii fixed 6 | Authorization Code |
| `39` | ascii fixed 2 | Response Code |
| `41` | ascii fixed 8 | Terminal ID |
| `42` | ascii fixed 15 | Merchant ID |
| `47` | ascii LLLVAR 999 | Additional Data (JSON-encoded f47 blob) |
| `52` | binary fixed 8 | PIN Data Block |
| `55` | binary LLLVAR 255 | ICC Data |

---

## `pans_defined.json`

Keys are PAN strings. Used by crypto_host and downstream_host.

```json
{
  "4111111111111111": {
    "pin": "1234",
    "pan_seq": "00",
    "imk_ac": "0123456789ABCDEF1032547698BADCFE",
    "cvk":    "FEDCBA9876543210ECA86420FDBAC097",
    "pek":    "0011223344556677AABBCCDDEEFF0011",
    "aav_key":"AABBCCDDEEFF00112233445566778899"
  },
  "4222222222222222": { ... },
  "5111111111111111": { ... },
  "5222222222222222": { ... }
}
```

---

## Message flow (0100 authorization)

```
upstream_host          router              crypto_host         downstream_host
     │                   │                      │                    │
     │──0100 (framed)───►│                      │                    │
     │                   │──POST /validate_0100─►│                    │
     │                   │◄─{f47: enriched}──────│                    │
     │                   │──IMS frame (0100)─────────────────────────►│
     │                   │◄──────────────────────────────IMS frame (0110)
     │                   │──POST /validate_0110─►│                    │
     │                   │◄─{f47: +arpc}─────────│                    │
     │◄──0110 (framed)───│                      │                    │
```

**STAN rewrite:** router replaces field 11 with its own sequential counter before forwarding to downstream. On response, restores original STAN before sending back to upstream.

**Keepalive (0800/0810):** upstream sends 0800 periodically. Router forwards to downstream (IMS frame), downstream responds 0810, router forwards 0810 back to upstream. The 0810 path bypasses the dispatcher (handled directly in session).

---

## Message flow (0120 advice / 0420 reversal)

```
0120 Advice   (decision already taken upstream — F38/F39 pre-filled, no crypto call)
  upstream ──0120──→ router ──0120──→ downstream_host ──0130 (F39=00)──→ router ──0130──→ upstream

0420 Reversal (command to revert an earlier transaction, no crypto call)
  upstream ──0420──→ router ──0420──→ downstream_host ──0430 (F39=00)──→ router ──0430──→ upstream
```

Both ride the same `Dispatcher` path as `0100` (STAN rewrite, pending-map lookup) but **skip the
crypto call** — the external decision has already been made (`0120`) or there is nothing to
validate cryptographically (`0420`). `downstream_host` always replies approved/accepted
(`F39=00`); there is no decline path for advice or reversal in this simulation.

---

## Running

```bash
# All at once via monitor:
python3 monitor/main.py --port 8090
# Open http://localhost:8090 → Start All

# Individual actors:
python3 simulators/crypto_host/main.py
python3 simulators/downstream_host/main.py
python3 router/main.py --config router/router_1/config.json
python3 simulators/upstream_host/main.py --config simulators/upstream_1/config.json
```

Equivalent `run/*.sh` wrappers exist for every instance (each just `cd`s to the project root and
execs the matching `main.py --config ...`), plus:
- `run/monitor.sh` — starts the monitor
- `run/kill_monitor.sh` — `POST /stop` to the monitor, polls its PID for up to 30s, then sends
  `SIGKILL` if it hasn't exited (covers a monitor that's wedged or has a stuck subprocess)

Default port assignments:
- Router upstream listen: 5000 (router_1), 5003 (router_1.01), 5010 (router_2, client mode)
- Downstream host IMS: 5001
- Crypto host REST: 5002
- Router command API: 8080 (router_1), 8084 (router_1.01), 8085 (router_2)
- Downstream command API: 8081
- Crypto command API: 8082
- Upstream command API: 8083 (upstream_1), 8086 (upstream_2), 8087 (upstream_3)
- Monitor: 8090

---

## Testing

```bash
python3 -m pytest tests/ -v
```

| Test file | Covers |
|---|---|
| `test_framing.py` | length-prefix framing round-trip (all 4 `length_field_type` encodings), `max_message_bytes` rejection |
| `test_stats.py` | rolling-window counters (30/60/180/1800s) |
| `test_command_server.py` | `/stats`, `/stop`, `/log_level`, `/logs` |
| `test_crypto_utils.py` | ARQC/ARPC/PIN/CVV2/AAV against the keys in `pans_defined.json` |
| `test_router.py` | full-stack integration: starts crypto/downstream/router/upstream in-thread, uploads a CSV, calls `/start`, asserts field 39 on the results |
| `test_router_1_01.py` | connectivity + `/stats` smoke test for the second partner_a router instance |
| `test_dispatcher_resilience.py` | bounded-queue backpressure, pending-entry TTL expiry/decline, STAN-collision logging, `purge()` drop counts |
| `test_crypto_breaker.py` | breaker opens after `crypto_breaker_threshold` consecutive failures, short-circuits without an HTTP call while open, closes after `crypto_breaker_cooldown_seconds` |
| `test_command_server_auth.py` | protected routes reject missing/wrong `X-Router-Auth`; unprotected routes (`/stats`, `/logs`) unaffected; default bind is loopback |

`run_test.sh <csv_file>` is a separate end-to-end CLI driver (not pytest): it launches
crypto_host/downstream_host/router/upstream_host as background processes, waits for each `/stats`
endpoint to come up, uploads the given CSV, calls `/start`, polls `/results` until all rows have a
response (30s deadline), then prints a PAN/RC/auth-code/field-47 report and the router's 30s
stats. `run_test.sh --manual <csv_file>` skips spawning processes and drives already-running
actors instead — used to debug the IMS Connect handshake by hand.

---

## Threading model summary

| Thread | Owner | Lifecycle |
|---|---|---|
| `acceptor` (upstream server mode) | `UpstreamServer` (outside session) | Permanent |
| `up-client` | `RouterSession` | Per session |
| `ds-receiver` | `RouterSession` | Per session |
| `worker-N` (×8) | `Dispatcher` | Per session, drained on teardown |
| `pending-reaper` | `Dispatcher` | Per session, drained on teardown |
| Flask (command server) | `CommandServer` | Permanent daemon |
| Flask (crypto host) | `crypto_host/main.py` | Permanent (blocking main thread) |
| `acceptor` (downstream IMS) | `downstream_host/main.py` | Permanent daemon |
| per-connection handler | `downstream_host` | Per connection daemon |
| `receive_loop` | `upstream_host` | Per connection daemon |
| `_keepalive_sender` | `upstream_host` | Per connection daemon |

Teardown order on session disconnect: drain workers → close upstream socket → close downstream sockets → join upstream thread.

---

## Known limitations (intentionally out of scope for this simulation)

- **No authentication on the upstream or downstream TCP sockets.** First TCP connector wins
  (`UpstreamServer.accept`); `downstream_host` pairs connections by EBCDIC `client_id` with no
  credential check, so a connection claiming another router's `client_id` would have that
  router's responses routed to it. A production deployment needs an IP allowlist at minimum,
  mTLS ideally.
- **`command_auth_token` defaults to `None`** (auth disabled) on every actor config — set it
  explicitly per actor before ever changing `command_bind_host` away from `127.0.0.1`.
- **Crypto traffic is plaintext HTTP, unauthenticated.** PANs, ARQC/ARPC, and CVV2 cross the
  router↔crypto_host link in the clear (PIN blocks are pre-encrypted). Anything that can reach
  `crypto_host`'s port can call `/validate_0100` directly.
- **`pans_defined.json` stores master keys (IMK, CVK, PEK, AAV key) in plaintext JSON.** Fine as
  a test fixture; this pattern must not be carried into a real key-management path.
