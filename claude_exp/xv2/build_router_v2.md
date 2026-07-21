# ISO 8583 Router — Build Specification (v2)

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
- **Daemon threads that are the sole reader of a connection must never die silently.** Any
  exception inside the ds-receiver or an upstream read thread that is not caught and logged will
  leave the session in a broken state with no diagnostic output. Wrap dispatch calls (not just I/O)
  in `try/except Exception` inside these threads.
- **Any script meant to be re-run (not just code meant to be re-imported) must fail loud, not
  fail silent.** `run_test.sh`, `monitor.sh`, and `kill_monitor.sh` are never exercised by
  `pytest` — they are the only thing that drives the real multi-process system end-to-end, so a
  bug in one of them is invisible until a human actually runs it. See the "Glue-script safety
  checklist" under Testing, and "`set -e` + command substitution defeats retry loops" under
  Common pitfalls — both were added after independently rebuilding this project from spec twice
  (xv3, then xv4) produced two structurally different `run_test.sh` implementations, one of which
  had a fatal, silent bug the other happened not to.

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
│   ├── monitor.sh           # writes its own PID to run/.monitor.pid before exec
│   └── kill_monitor.sh      # POST /stop, poll PID from run/.monitor.pid up to 30s, SIGKILL fallback
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

**Dev/testing dependencies** (not in `requirements.txt`, not imported by app code):

```
pytest
playwright
```

After `pip install playwright`, also run `playwright install chromium` once (downloads the
headless browser binary — not pulled in by pip alone). Playwright + headless Chromium is how UI
changes to `monitor/static/index.html` get verified: drive it via short Python scripts using the
sync API, capture screenshots with `page.screenshot(path=...)`, view them with the Read tool. This
is how the SIGTERM/atexit subprocess-leak bug and the `/start`-button connection race were both
actually found — by loading the dashboard and clicking through it, not just reading the code.
Don't skip this step for monitor UI changes; static review of the JS/HTML missed both bugs.

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

Internal helper `_recv_exact(sock, n)` loops on `sock.recv` until `n` bytes are collected;
raises `ConnectionError` on empty read (remote disconnect), **and also catches any `OSError`
from `sock.recv()` itself and re-raises it as `ConnectionError`** (`raise ConnectionError(...)
from e`). The second case is not just defensive: a socket closed by another thread while this
call is blocked in `recv()` (e.g. during session teardown) surfaces as a plain `OSError` such
as EBADF, which is *not* a `ConnectionError` subclass — without this wrapping, every caller
built on `read_message`/`read_request` would need to catch both exception types separately to
handle a local-close-during-teardown race, and it is easy to forget the second one.

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

**Initialization order matters:** `logging.basicConfig(level=..., ...)` must be called **before**
`CommandServer(...)`. `basicConfig` is a no-op when the root logger already has handlers;
`CommandServer.__init__` adds a `LogBuffer` handler to the root logger as a side effect. If
`basicConfig` is called after, the root logger level stays at the default `WARNING` regardless of
what `basicConfig` was asked to set, and INFO/DEBUG log messages silently disappear.

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
    queue_maxsize: int = 1000
    pending_ttl_seconds: int = 30
    crypto_breaker_threshold: int = 5
    crypto_breaker_cooldown_seconds: int = 30
    reconnect_jitter_seconds: float = 2.0
    command_bind_host: str = "127.0.0.1"
    command_auth_token: str = None

    @classmethod
    def from_file(cls, path: str) -> RouterConfig: ...
```

**`from_file` exclusion set** — the dict comprehension that builds `extra_kwargs` (the fields
passed directly as kwargs to `RouterConfig(...)`) must explicitly exclude every JSON key that is
consumed by the parsing code above it. The complete set is:

```python
extra_kwargs = {
    k: v
    for k, v in data.items()
    if k not in ("upstream", "downstream", "crypto", "iso_spec", "type", "is_active")
}
```

`upstream`, `downstream`, `crypto`, `iso_spec` are parsed into typed objects above this line.
`type` and `is_active` are monitor-only metadata that `RouterConfig` has no field for. **Every
future JSON key that is handled explicitly before this comprehension must be added to this set
immediately** — omitting it causes `TypeError: __init__() got an unexpected keyword argument`
at router startup.

`from_file` resolves `iso_spec` relative to the config file's directory.
`irm_id` and `client_id` are loaded via `ims_connect.to_ebcdic(str, 8)`.

### `router/config.json` (example for `router_1`)

```json
{
  "name": "router_1",
  "type": "router",
  "is_active": true,
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

`is_active` controls whether the monitor's "Start All" launches this router. Set to `false` for
instances that are not part of the current test scope. JSON booleans are lowercase (`true` /
`false`) — Python's `True`/`False` are not valid JSON and will cause `json.JSONDecodeError` at
startup.

The resilience/security fields (`queue_maxsize`, `pending_ttl_seconds`,
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

### `router/dispatcher.py`

```python
@dataclass
class PendingEntry:
    up_conn: socket.socket
    up_write_lock: threading.Lock
    upstream_stan: str
    created_at: float           # time.monotonic() — used by the pending reaper

@dataclass
class RoutedMessage:
    req: dict
    up_conn: socket.socket
    up_write_lock: threading.Lock
    up_addr: tuple

class Dispatcher:
    """Worker pool. Routes 0100 upstream → crypto → downstream.
    Routes 0110/0130/0430 downstream → upstream (STAN lookup)."""

    def __init__(self, cfg, downstream, crypto, spec, stats, reconnect_event)
        # self._queue = queue.Queue(maxsize=cfg.queue_maxsize)
    def start(self)              # spawns cfg.worker_threads daemon workers + 1 pending-reaper thread
    def submit(self, msg: RoutedMessage) -> None   # blocking enqueue (backpressure)
    def handle_response(self, resp: dict)           # called from ds-receiver thread
    def purge(self) -> dict                         # operator drain; returns dropped counts
    def drain_and_stop(self)                        # None sentinels + join (session teardown)
```

**STAN rewriting** — each router maintains its own counter (6-digit, wraps at 1,000,000):
- On 0100: save `(upstream_conn, upstream_lock, upstream_stan, created_at)` keyed by `router_stan`; send to downstream with `router_stan` in field 11
- On 0110: look up `router_stan`, restore `upstream_stan` in field 11, forward back
- If a `router_stan` slot is still occupied when it would be reused (counter wrapped while the
  old entry was still outstanding), log at ERROR before overwriting it.

**Pending reaper** (`_pending_reaper`, daemon thread started in `start()`):
- Wakes every 1s, scans `self._pending` for entries older than `cfg.pending_ttl_seconds`
- For each expired entry: pops it, builds a local decline (`f39="91"`) and writes it to
  `entry.up_conn` under `entry.up_write_lock`, logs a warning

**Queue depth / pending count**: after every `submit()`/dequeue and every pending insert/pop,
the dispatcher calls `stats.set_gauge("queue_depth", self._queue.qsize())` and
`stats.set_gauge("pending_count", len(self._pending))`.

**Traffic counters**: `stats.record_sent()`/`stats.record_recv()` must be called at every actual
wire I/O point — both in the dispatcher (`_process` after `downstream.send()`,
`handle_response` after the write to `entry.up_conn`, the pending reaper after its decline
write) and in `RouterSession` (`_handle_upstream` after decoding a frame, `_downstream_receiver`
after decoding a frame, `_forward_0800`/`_forward_0810` after their writes). Skipping this is
easy to miss because nothing fails loudly: `/stats` still returns 200 and `sent_total`/
`recv_total` just silently stay at 0, which means `seconds_since_last_recv` stays `None`
forever and the monitor shows that router as permanently yellow regardless of real traffic.

**`_process(msg)` logic** (runs in worker thread):
1. Extract `mti`, `pan` (field 2), `upstream_stan` (field 11)
2. Generate `router_stan`
3. If `mti == "0100"`: call `crypto.validate("validate_0100", pan, req.get("47",""))`; put result in `fwd["47"]` if truthy
4. Encode `fwd` with pyiso8583
5. Insert `PendingEntry` into `self._pending[router_stan]`
6. Build IMS frame via `ims_connect.build_frame(0x00, irm_id, client_id, fwd["t"], encoded)`
7. `downstream.send(frame)` — OSError propagates to worker → sets `reconnect_event`; on success, `stats.record_sent()`

**`handle_response(resp)` logic** (runs in ds-receiver thread):
1. If `mti == "0810"`: return immediately (handled separately by session)
2. If `mti` not in `("0110", "0130", "0430")`: log warning, return
3. Look up `entry = self._pending.pop(router_stan, None)`
4. Restore `fwd["11"] = entry.upstream_stan`
5. If `mti == "0110"`: call `crypto.validate("validate_0110", pan, resp.get("47",""))`; update `fwd["47"]`
6. Encode and write to `entry.up_conn` under `entry.up_write_lock`, then `stats.record_sent()` —
   wrap the write in `try/except OSError`: this write runs on the ds-receiver thread, and
   session teardown closing the upstream socket from a different thread can race it.

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
        # 6. ds_thread.join(timeout=5)
```

**`_OrEvent`** — `_server_upstream_loop` and `_client_upstream_loop` pass a combined event to
`srv_sock.accept()` / `upstream_client.connect()` so both `stop_event` and `reconnect_event`
can wake the accept/connect loop without those APIs needing to know about both:

```python
class _OrEvent:
    def __init__(self, *events):
        self._events = events
    def is_set(self) -> bool:
        return any(e.is_set() for e in self._events)
```

**`_handle_upstream(conn, addr, write_lock)`** (read loop for one upstream):
- Sets `stats.set_connection("upstream", True)`
- Stores conn/lock in `_upstream_ref` (protected by `_up_ref_lock`)
- Reads frames → decodes ISO 8583 → `stats.record_recv()`
- MTI routing:
  - `0100 / 0120 / 0420` → `dispatcher.submit(RoutedMessage(...))`
  - `0800` → `_forward_0800(req)`: re-encode, wrap in IMS frame, send to downstream,
    `stats.record_sent()` on success — wrapped in `try/except OSError` since teardown can close
    the downstream socket from another thread while this write is in flight
  - other → log warning
- On `ConnectionError`: log warning, set `reconnect_event`
- On exit (finally): `stats.set_connection("upstream", False)`, clear `_upstream_ref`

**`_downstream_receiver()`**:
- Loops calling `downstream.recv()`
- Skips frames whose first 4 bytes == `"PING".encode("cp500")` — both halves of the EBCDIC
  marker must match byte-for-byte; an ASCII `"PING"` from the sender side will not be recognized
  and falls through to a `DecodeError`
- Decodes ISO 8583 → `stats.record_recv()`
- Routes decoded message:

```python
try:
    if resp.get("t") == "0810":
        self._forward_0810(resp)
    else:
        self.dispatcher.handle_response(resp)
except Exception:
    logger.exception("unexpected error dispatching downstream message mti=%s", resp.get("t"))
```

  The `try/except Exception` guard around the dispatch calls is required. Any non-OSError from
  `iso8583.encode`, internal logic, or similar inside `_forward_0810` or `handle_response` will
  propagate up and kill this daemon thread with no log if left unguarded — the session then
  silently stops processing downstream responses while the router happily continues accepting
  upstream messages.

- `ConnectionError` from `downstream.recv()` → `stats.set_connection("downstream", False)`, set
  `reconnect_event`, break

**`_forward_0810(resp)`**:
- Acquires `_up_ref_lock`, reads `_upstream_ref`; if None, logs warning and returns
- Re-encodes resp, writes to upstream conn under `write_lock`
- Wraps in `try/except OSError`: teardown can clear `_upstream_ref` and close the upstream socket
  from the main thread while this write is in flight on ds-receiver

**`_teardown(up_thread)`**:
1. `dispatcher.drain_and_stop()`
2. Acquire `_up_ref_lock`, clear `_upstream_ref`, close upstream conn if present
3. `downstream.close()` — wakes any blocked `recv()` on from_sock (ds-receiver gets EBADF,
   normalized to `ConnectionError` by `_recv_exact`, which sets `reconnect_event` and exits;
   this is the expected teardown path, not an error)
4. `up_thread.join(timeout=5)`

### `router/main.py`

```python
def load_config(path=None) -> (RouterConfig, config_base_dir):
    # default: router_1/config.json relative to main.py

def run(cfg=None, stop_event=None, stats=None, _config_base=None):
    # 1. logging.basicConfig(level=cfg.log_level, ...)   ← MUST come before CommandServer(...)
    # 2. Create Stats, CommandServer(bind_host=..., auth_token=...); start it
    #    Register protected POST /dispatcher/purge → current session's dispatcher.purge()
    #    (re-pointed at the new Dispatcher on each reconnect)
    # 3. If upstream.mode == "server": create UpstreamServer (lives outside session loop)
    # 4. Main loop (while not stop_event):
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
- `logging.basicConfig(level=..., ...)` **before** `CommandServer(...)`
- Create `Stats` + `CommandServer`; start both
- Expose custom routes via `cmd.register(path, methods)`

### `simulators/downstream_host/main.py`

Simulates an IMS Connect authorization host.

**Config:**
```json
{
  "name": "downstream_host",
  "type": "downstream",
  "is_active": true,
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
  - `PING_TRANSCODE` → send `"PING".encode("cp500") + "PIPES cleaned".encode("cp500")` to
    from-conn queue. **Both halves are EBCDIC, including the `"PING"` marker itself** — it
    must match `session.py`'s skip-check byte-for-byte (`data[:4] == "PING".encode("cp500")`).
    An ASCII `"PING"` prefix here will not be recognized as a ping by the router.
  - `0800` → encode 0810, put on queue
  - `0120` → 0130 with rc=00
  - `0420` → 0430 with rc=00
  - `0100` → `_process_0100(req, pans)`:
    - PAN not in `pans_defined` → rc=01
    - `f47_decode(req["47"]).get("response_code", "00")` not `"00"` → rc=01
    - else → rc=00, generate sequential 6-digit auth code (field 38)
    - **Every response must echo `f47` back**: take the request's `f47_decode(req.get("47", ""))`,
      set `message_type="0110"` and `response_code` to the decided rc, put `f47_encode(...)` into
      the response dict's `"47"` key. Required even though nothing above this point reads `f47`
      back out — `crypto_host`'s ARPC step only runs on `validate_0110`, and the only place the
      original `f55` cryptogram/ATC can reach that call is by `downstream_host` round-tripping the
      request's `f47` into its response. Skipping this means ARPC silently never gets computed.

- `_dispatch_new_conn`: reads the **first frame** off the accepted connection in a fresh thread
  (not the acceptor thread), then routes to `_handle_from_conn` or `_handle_to_conn`. Reading the
  first frame off-acceptor avoids a deadlock: the to-conn's first frame isn't sent until after
  the from-conn's resume-TPIPE, but the acceptor must accept both TCP connections before blocking
  on either read.

- `_wait_for_from_conn(client_id, timeout=2.0)`: polls the `from_connections` dict for up to 2s
  before processing the first request from a to-conn. The from-conn's resume-TPIPE can still be
  in flight when the to-conn's first frame (the pipe-cleaner ping) arrives; polling avoids
  dropping frames on that race.

**`pans_defined.json`** is a dict keyed by PAN string; downstream host only uses key presence.

### `simulators/upstream_host/main.py`

Simulates an upstream card network client. Sends ISO 8583 0100s from a CSV, collects 0110 responses.

**Config** (instance-specific, e.g. `upstream_1/config.json`):
```json
{
  "name": "upstream_1",
  "type": "upstream",
  "is_active": true,
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
- `GET /start` — reads CSV, launches `_send_loop` in daemon thread; returns `{"rows": N}`
- `GET /results` — returns list of result dicts

**`_send_loop(conn, rows)`:**
- For each row: build ISO 8583 0100 from CSV columns matching spec field keys
- Assign sequential STAN (field 11); store row in `pending[stan]`
- `write_message(conn, encoded, framing)`; sleep 20ms between messages

**`_receive_loop(conn, disc_evt)`:**
- Reads frames, decodes; ignores 0810 (`continue`)
- On 0110/0130/0430: pops `pending[stan]`, merges response fields as `resp_<field>` prefix, appends to `results`
- On `ConnectionError`: sets `disc_evt`, breaks

**`_keepalive_loop(conn, disc_evt)`** — sends 0800 immediately on connection, then waits:

```python
def _keepalive_loop(self, conn, disc_evt):
    while not disc_evt.is_set() and not self.stop_event.is_set():
        try:
            write_message(conn, build_0800(self.spec), self.framing)
            self.stats.record_sent()
        except OSError:
            return
        # interruptible wait — check disc_evt every second
        elapsed = 0.0
        while elapsed < self.ping_0800_seconds:
            if disc_evt.is_set() or self.stop_event.is_set():
                return
            time.sleep(min(1.0, self.ping_0800_seconds - elapsed))
            elapsed += 1.0
```

**Sending first, then waiting** is required. The loop that waits first produces a dead
`ping_0800_seconds` window on every new connection — the system appears to have zero traffic
and the monitor shows the router as permanently yellow until the first 0800 fires.

**`_run_connection(sock)`:**

```python
def _run_connection(self, sock):
    with self._conn_lock:
        self._conn = sock
    self.stats.set_connection("router", True)

    disc_evt = threading.Event()
    recv_thread = threading.Thread(target=self._receive_loop, args=(sock, disc_evt), daemon=True)
    recv_thread.start()
    keepalive_thread = threading.Thread(target=self._keepalive_loop, args=(sock, disc_evt), daemon=True)
    keepalive_thread.start()

    disc_evt.wait()

    with self._conn_lock:
        if self._conn is sock:
            self._conn = None
    self.stats.set_connection("router", False)
    try:
        sock.close()
    except OSError:
        pass
    recv_thread.join(timeout=2)
    keepalive_thread.join(timeout=2)
```

**`_client_connect_loop()`:**

```python
def _client_connect_loop(self):
    router_cfg = self.cfg["router"]
    retry_seconds = self.cfg.get("retry_seconds", 5)
    while not self.stop_event.is_set():
        try:
            sock = socket.create_connection((router_cfg["host"], router_cfg["port"]), timeout=5)
            sock.settimeout(None)   # switch to blocking; timeout=5 above is connect-only
        except OSError:
            self.stop_event.wait(retry_seconds)
            continue
        self._run_connection(sock)
```

**`sock.settimeout(None)` is required.** `socket.create_connection(addr, timeout=N)` sets the
timeout on the **returned socket**, not only on the TCP handshake. Omitting `settimeout(None)`
leaves the socket in N-second timeout mode for its entire lifetime: every `recv()` that blocks
longer than N seconds raises `socket.timeout` (an `OSError`), which `_recv_exact` normalizes to
`ConnectionError`, which `_receive_loop` treats as a disconnect. The symptom is the upstream
disconnecting from the router exactly N seconds after the last message was received, with no error
logged and a reconnect loop running every ~(`N + retry_seconds`) seconds. The intent of the
timeout was "fail fast if the router isn't reachable at connect time", which is correct; the
solution is to clear it immediately after a successful connect.

**CSV format:**
```
2;3;4;11;expected_39
4111111111111111;000000;000000000100;000001;00
```
Semicolon-delimited, utf-8-sig encoding. Column names are ISO 8583 field numbers. Field 11 (STAN) is overwritten by the sender. Non-matching columns are silently ignored.

**`POST /upload` overwrites `input_dir/test_cases.csv` in place.** Any manual run, monitor-driven
upload, or `upload_path` call against that instance permanently replaces its content. A test that
asserts against specific rows should write its own known content at setup time rather than trusting
whatever is currently on disk — see `test_router.py`.

### `simulators/crypto_host/main.py`

Stateless HTTP service for cryptographic validation.

**Config:**
```json
{
  "name": "crypto_host",
  "type": "crypto",
  "is_active": true,
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
- Read `is_active` from each config (default `True` when absent)
- `SCRIPTS_BY_TYPE = {"router": "router/main.py", "upstream": "simulators/upstream_host/main.py", "downstream": "simulators/downstream_host/main.py", "crypto": "simulators/crypto_host/main.py"}`
- Actors requiring `--config` arg: `{"router", "upstream"}`
- Startup order: crypto(0) → downstream(1) → router(2) → upstream(3)
- Result is cached once per monitor lifetime; restart monitor to pick up config changes

**`_start_all_worker()`**:
```python
for actor in get_actors():
    if not actor["is_active"]:
        continue            # skip actors with is_active=false
    if not is_running(actor["name"]):
        launch_actor(actor)
    wait_for_ready(actor, timeout=10)
```

**`wait_for_ready(actor, timeout=10)`** — polls `/stats` until:
- Any actor type: HTTP 200 received
- Router: `connections.downstream == true`
- Upstream: `connections.router == true`
Without the connection check, a `/start` called immediately after "Start All" can 503 with
"not connected to router" even though every `/stats` already answers 200.

**Monitor API routes:**
| Route | Purpose |
|---|---|
| `GET /` | Serve `static/index.html` |
| `GET /api/actors` | Ordered list with name/type/command_port/running/is_active |
| `GET /api/routers_by_partner` | Dict `partner_id → [{name, command_port}]` |
| `GET /api/status` | Parallel health check; green/yellow/red per actor |
| `GET /api/starting` | `{"starting": bool}` |
| `GET /api/csv_files` | List CSVs from `test_csv_files/` and each upstream's `input/` dir |
| `POST /api/actor/<name>/launch` | Start subprocess if not running |
| `POST /api/actor/<name>/stop` | Proxy to actor's `/stop` |
| `GET /api/actor/<name>/stats` | Proxy to actor's `/stats` |
| `GET /api/actor/<name>/start` | Proxy to actor's `/start` (upstream only) |
| `GET /api/actor/<name>/results` | Proxy to actor's `/results` |
| `GET\|POST /api/actor/<name>/log_level` | Proxy log level |
| `GET /api/actor/<name>/logs` | Proxy logs; `?format=text` for plain text |
| `POST /api/actor/<name>/upload` | Proxy multipart CSV upload |
| `POST /api/actor/<name>/upload_path` | Upload by relative project path `{"path": "..."}` |
| `POST /api/actor/<name>/dispatcher/purge` | Router only; proxies protected `/dispatcher/purge` |
| `POST /api/start_all` | Start active actors in order, waiting up to 10s each |
| `POST /api/stop_all` | Stop actors in reverse order |
| `POST /stop` | Stop monitor process (terminates all managed subprocesses) |

**Status logic** (per actor): fetch `/stats` → if `yellow_threshold_seconds` present, check `seconds_since_last_recv`; yellow if None or above threshold; green otherwise. Red if unreachable.

**Subprocess management:** `_processes` dict `name → Popen`. `atexit` handler terminates all on
exit, **and** a `signal.signal(signal.SIGTERM, ...)` handler calls the same termination routine
before `os._exit(0)`. Both are required: Python's `atexit` handlers do **not** run on a bare
`SIGTERM` (only on normal interpreter exit), so without the explicit signal handler, `kill <pid>`
orphans every actor subprocess, silently leaking processes and squatting on their ports.

Note this covers the case where the **monitor itself** is killed. It does not cover the case
where the **script that launched the monitor** (e.g. `run_test.sh`) dies first while the monitor
keeps running underneath it — see "Glue-script safety checklist" below for that failure mode,
which is a different bug with the same symptom (orphaned actor processes).

**Quiet logs:** every actor sets `logging.getLogger("werkzeug").setLevel(logging.ERROR)` —
Flask's default per-request access log would otherwise flood the console every 2 seconds.

### `monitor/static/index.html`

Single-page vanilla JS app (no build step, no framework).

**Layout:**
- Header: title + "Start All" / "Stop All" buttons + optional "Starting actors…" spinner
- Router Partners section: partner groups, each showing aggregate 30s/total stats and a grid of compact router cards
- Simulators section: cards for crypto, downstream, upstream actors
- Test Runner panel: upstream selector, CSV picker, Upload + Start buttons, results table

**Per-actor card (full size):** status dot, connection dots, 30s/60s and total sent/recv counters,
last-recv time, log-level selector, Logs / Start / Stop buttons. Router cards additionally show
`queue_depth`/`pending_count` gauges and a **Purge Queue** button (confirmation required).

**Polling:** `/api/status` + `/api/starting` every 2 seconds.

**Results table columns:** PAN, RC (green if "00"), Auth code (field 38), Field 47 (truncated).

**Log viewer modal:** fetches `/logs`, auto-refreshes every 2s, export to file.

---

## `test_spec.json` (ISO 8583 field spec)

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

**Keepalive (0800/0810):** upstream sends 0800 immediately on connect (and every `ping_0800_seconds` thereafter). Router forwards to downstream (IMS frame), downstream responds 0810, router forwards 0810 back to upstream. The 0810 path bypasses the dispatcher (handled directly in session).

---

## Message flow (0120 advice / 0420 reversal)

```
0120 Advice   (decision already taken upstream — F38/F39 pre-filled, no crypto call)
  upstream ──0120──→ router ──0120──→ downstream_host ──0130 (F39=00)──→ router ──0130──→ upstream

0420 Reversal (command to revert an earlier transaction, no crypto call)
  upstream ──0420──→ router ──0420──→ downstream_host ──0430 (F39=00)──→ router ──0430──→ upstream
```

Both ride the same `Dispatcher` path as `0100` (STAN rewrite, pending-map lookup) but **skip the
crypto call**. `downstream_host` always replies approved/accepted (`F39=00`); there is no decline
path for advice or reversal in this simulation.

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

**Every `main.py` under `router/` and `simulators/*/` must start with a `sys.path` bootstrap**
(insert the project root, computed from `__file__`, before the first `from shared...`/
`from router...` import). The bootstrap line differs by nesting depth: two `os.path.dirname()`
calls for `router/main.py`, three for `simulators/*/main.py`.

Equivalent `run/*.sh` wrappers exist for every instance, plus:
- `run/monitor.sh` — starts the monitor, first writing its own PID to `run/.monitor.pid`
  (`echo $$ > run/.monitor.pid` before `exec`)
- `run/kill_monitor.sh` — `POST /stop`, poll PID from `run/.monitor.pid` for up to 30s,
  then `SIGKILL` if not exited, then remove pidfile. Do not use `pgrep -f "monitor/main.py"`
  to find the PID — it can match unrelated processes and kill the wrong thing.

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
| `test_command_server_auth.py` | protected routes reject missing/wrong `X-Router-Auth`; unprotected routes unaffected; default bind is loopback |

`run_test.sh <csv_file>` is a separate end-to-end CLI driver (not pytest): launches all actors,
waits for readiness, uploads CSV, calls `/start`, polls `/results` for up to 30s, prints report.
`run_test.sh --manual <csv_file>` skips spawning and drives already-running actors.

### Glue-script safety checklist (`run_test.sh`, `monitor.sh`, `kill_monitor.sh`)

None of these scripts are exercised by `pytest` — they are the only thing that drives the real
multi-process system end-to-end, so a bug in one of them is invisible until a human runs it, and
whoever writes it from this spec is reinventing it from scratch each time (this spec deliberately
does not pin an exact implementation — only these required properties). Two independent rebuilds
of this project (xv3, then xv4) each produced a structurally different `run_test.sh`; one of them
had a fatal bug the other happened to avoid purely by writing the polling loop differently. Every
`run_test.sh` must satisfy all of the following, regardless of how it's structured internally:

- **Every HTTP readiness/polling check must fail-fast on a bad response, not feed it downstream.**
  Use `curl -s -f` (or equivalent) so a non-2xx response makes `curl` itself return non-zero,
  rather than piping a possibly-empty or possibly-HTML response into `python3 -c "...json.load..."`
  and hoping the retry loop notices the failure. A polling loop's whole point is to tolerate the
  target not being ready yet — don't let a transient miss produce a hard error from something
  downstream of the retry, whether that's a JSON parse or anything else.
- **Never let a single flaky iteration of a polling/retry loop kill the whole script.** If the
  script uses `set -e` (recommended — it catches real mistakes elsewhere), any command
  substitution assigned to a variable (`STATUS=$(curl ... | some_parser)`) must not be allowed to
  propagate a non-zero exit into the enclosing `set -e` context on a normal, expected retry path.
  Guard it explicitly (e.g. `STATUS=$(cmd) || STATUS=""`, or move the substitution inside an
  `if`/`while` conditional, which `set -e` does not abort on) — do not rely on `2>/dev/null` alone,
  which silences the error message but does nothing to the exit code that `set -e` reacts to.
- **Guarantee teardown with `trap ... EXIT`, not a final line at the bottom of the script.** If
  cleanup (killing spawned actors/monitor) is just the last few lines of the script, any early
  exit — from `set -e`, a `set -u` unbound variable, or a manual `Ctrl-C` — skips it, and every
  actor process (and the monitor, if the script started one) is orphaned, holding its ports open
  for the next run. `trap cleanup EXIT` runs on every exit path, including ones triggered by bugs
  in the script itself.
- **Prefer driving actors directly over going through the monitor's HTTP API, if simplicity is a
  goal.** A script that does `python3 router/main.py & PIDS+=("$!")` for each actor and kills
  `"${PIDS[@]}"` on exit has one less moving part (and one less network hop) than one that starts
  the monitor and drives `/api/start_all` + `/api/actor/<name>/upload_path` — either approach is
  valid, but the monitor-driven approach depends on the monitor itself staying healthy and adds a
  proxy layer between the script and the actor being tested.

---

## Threading model summary

| Thread | Owner | Lifecycle |
|---|---|---|
| `acceptor` (upstream server mode) | `UpstreamServer` (outside session) | Permanent |
| `up-server` / `up-client` | `RouterSession` | Per session |
| `ds-receiver` | `RouterSession` | Per session |
| `worker-N` (×8) | `Dispatcher` | Per session, drained on teardown |
| `pending-reaper` | `Dispatcher` | Per session, drained on teardown |
| Flask (command server) | `CommandServer` | Permanent daemon |
| Flask (crypto host) | `crypto_host/main.py` | Permanent (blocking main thread) |
| `acceptor` (downstream IMS) | `downstream_host/main.py` | Permanent daemon |
| per-connection handler | `downstream_host` | Per connection daemon |
| `_receive_loop` | `upstream_host` | Per connection daemon |
| `_keepalive_loop` | `upstream_host` | Per connection daemon |

Teardown order on session disconnect: drain workers → close upstream socket → close downstream
sockets → join upstream thread → join ds-receiver thread.

---

## Common pitfalls

These are implementation bugs that are easy to introduce and hard to diagnose because the symptom
is distant from the cause. Each was hit during xv3 or xv4 development.

### `create_connection(timeout=N)` sets socket timeout, not just connect timeout

`socket.create_connection(addr, timeout=5)` sets a **5-second timeout on the returned socket**
for its entire lifetime — not only for the TCP handshake. After a successful connect, every
`recv()` that blocks longer than 5 seconds raises `socket.timeout` (an `OSError`), which
`_recv_exact` normalizes to `ConnectionError`, which a receive loop treats as a remote
disconnect. The upstream closes cleanly (FIN, not RST); the router sees `ConnectionError(
"connection closed while reading")`; both sides log the disconnect as a remote event with no
indication that a local timeout fired. The symptom is a reconnect loop with a fixed period of
approximately `timeout + retry_seconds` seconds.

**Fix:** always call `sock.settimeout(None)` immediately after `create_connection` for sockets
that are used for long-lived persistent connections:

```python
sock = socket.create_connection(addr, timeout=5)
sock.settimeout(None)   # switch to blocking; timeout=5 above is connect-only
```

### `RouterConfig.from_file()` exclusion set must be kept in sync with config.json

`from_file()` passes a `**extra_kwargs` dict to the `RouterConfig` dataclass. Every JSON key
that is consumed by explicit parsing code above the comprehension — or that is monitor-only
metadata with no `RouterConfig` field — must be listed in the exclusion set. The error when a
key is missing from the set is `TypeError: __init__() got an unexpected keyword argument 'x'`
at router startup, which points to `from_file()` but gives no indication of which config file
caused it or that the fix is to extend the exclusion set.

### JSON booleans are lowercase

`"is_active": True` is Python syntax. JSON requires `"is_active": true`. The error is
`json.JSONDecodeError` at startup. Editors that open `.json` files with Python syntax
highlighting, or any copy-paste from a Python REPL, will silently produce the wrong literal.

### Keepalive loop must send before waiting

A loop that waits `ping_0800_seconds` before the first send produces a dead period of up to
30 seconds on every new connection. During this window, the router's `seconds_since_last_recv`
stays `None`, the monitor shows the actor as yellow, and the keepalive path appears broken even
though the connection is healthy. Send first; wait after.

### Daemon threads must guard all dispatch calls, not just I/O

The ds-receiver thread is a daemon — its death is silent. I/O calls (`recv`, `send`) are
protected by `_recv_exact`'s `OSError → ConnectionError` normalization. Dispatch calls
(`_forward_0810`, `dispatcher.handle_response`) are not: any non-OSError exception from
`iso8583.encode`, `iso8583.decode`, or internal logic propagates up and kills the thread with
no log. Wrap the entire dispatch block in `try/except Exception: logger.exception(...)`.

### `logging.basicConfig` must come before `CommandServer.__init__`

`CommandServer.__init__` adds a `LogBuffer` handler to the root logger. Python's `basicConfig`
is a no-op when the root logger already has handlers. If `basicConfig` is called after
`CommandServer(...)`, the root logger level is never set from `cfg.log_level`, and all INFO/DEBUG
messages are silently suppressed (the default root logger level is `WARNING`).

### `set -e` + command substitution defeats retry loops and orphans processes

**Hit during xv4 development.** A polling loop written as:

```bash
set -e
for i in $(seq 1 30); do
  STATUS=$(curl -s "http://127.0.0.1:$PORT/stats" | python3 -c "import sys,json; ...")
  if [ "$STATUS" = "True" ]; then break; fi
  sleep 1
done
```

looks like a normal retry-with-backoff loop, but it isn't one under `set -e`. On the very first
iteration where the target isn't ready yet, `curl` returns an empty (or partial) body, `python3`'s
`json.load` raises `JSONDecodeError`, the pipeline's exit status is non-zero, and — because this
is a plain variable assignment, not a command inside an `if`/`while` test — `set -e` terminates
the **entire script** right there. There is no error message (stderr of the failing `python3` was
redirected to `/dev/null`, and `set -e`'s own exit is silent), so the script just stops, mid-way
through actor startup, having printed nothing to suggest why. Every actor process already spawned
(and the monitor, if the script started one) is left running, orphaned, holding its ports for the
next run. This reproduces reliably: it depends only on the *first* readiness poll landing before
the target actor's HTTP server is listening, which is common right after `launch_actor()`.

**Fix:** don't let a retry-loop iteration's expected-to-sometimes-fail command propagate its exit
code into `set -e` (guard the assignment, or move it inside a conditional), and use `curl -f` so
an HTTP-level failure is a clean non-zero `curl` exit rather than a body that a downstream parser
chokes on. See the "Glue-script safety checklist" under Testing for the full set of requirements
this implies for `run_test.sh` specifically.

---

## Known limitations (intentionally out of scope for this simulation)

- **No authentication on the upstream or downstream TCP sockets.** First TCP connector wins.
- **`command_auth_token` defaults to `None`** (auth disabled) — set it explicitly before
  exposing any command port beyond loopback.
- **Crypto traffic is plaintext HTTP, unauthenticated.** PANs and ARQC/ARPC cross the link in
  the clear.
- **`pans_defined.json` stores master keys in plaintext JSON.** Fine as a test fixture only.
- **`test_csv_files/test_crypt.csv` is not wired up to anything in this spec.** Leave it alone
  until a direct crypto_host test is built.

---

## C++ portability notes

The blocking-threads model was chosen specifically because it maps 1:1 to a C++ port. These
notes identify where the boundary will matter most. The simulators will be replaced by real
external systems and do not need a C++ port — only `router/` needs to perform at volume.

### Hot path: framing and the per-connection read loop

`_recv_exact` is the innermost loop: `while remaining > 0: chunk = sock.recv(remaining)`.
In C++, this becomes a blocking `recv()` loop in a dedicated `std::thread` per connection,
with a pre-allocated stack buffer (e.g., `std::array<uint8_t, MAX_MSG_SIZE>`) — no heap
allocation inside the loop. The ISO 8583 decode (currently pyiso8583) will need a C++ field
parser; the field map is small enough for a lookup table.

### Pending map sharding

`Dispatcher._pending` is a `dict` guarded by one `threading.Lock`. At high TPS, this lock
becomes a contention point because workers insert and ds-receiver pops on every transaction.
In C++, shard by `router_stan % N_BUCKETS` across N `std::unordered_map<std::string,
PendingEntry>` each with its own `std::mutex`. 16 buckets cuts the per-lock rate by ~16× with
no algorithmic change.

### Pending reaper: linear scan vs. expiry heap

The Python reaper scans the entire `_pending` dict every second looking for entries older than
TTL. In C++, use a min-heap (e.g., `std::priority_queue` keyed on `expiry_time`) maintained
alongside the hash map: push on insert, pop and discard stale top entries on wake-up.
`std::chrono::steady_clock` (monotonic) rather than wall clock for all TTL arithmetic.

### Bounded queue

`queue.Queue(maxsize=N)` with blocking `put()` maps to a `std::deque<RoutedMessage>` +
`std::mutex` + `std::condition_variable`. `submit()` waits on the condition variable while
`deque.size() >= maxsize`; workers signal it after each dequeue. A lock-free bounded MPMC
ring queue (e.g., `moodycamel::ConcurrentQueue` or a hand-rolled ring buffer) avoids the
mutex entirely but adds implementation complexity — the mutex version is correct and simpler
to reason about first.

### `_OrEvent` → `std::atomic<bool>` or shared flag

`_OrEvent` polls `is_set()` in a 1-second loop (driven by `UpstreamServer`'s accept timeout).
In C++, replace with a single `std::atomic<bool> teardown_flag` set by either `stop_event` or
`reconnect_event`; use `accept()` with `SO_RCVTIMEO` or a self-pipe trick to interrupt the
blocking accept rather than polling. Edge-triggered is cleaner and cheaper than a 1-second poll.

### Teardown: `shutdown()` before `close()`

`_teardown` calls `conn.close()` to unblock a thread blocked in `recv()` on that socket.
On Linux, `close()` on a socket that another thread is blocking on is technically a race:
the fd number can be reused between the close and the blocked thread's return. The safe pattern
is `shutdown(fd, SHUT_RDWR)` first (signals EOF to the blocking `recv()`, which returns 0
without closing the fd), then join the thread, then `close()`. Python's GIL and fd lifetime
management paper over this for the current prototype; C++ does not.

### `write_lock` per upstream connection

Each upstream connection has one `threading.Lock` (= `std::mutex`) shared by the ds-receiver
thread and any worker thread writing a response back. This is correct and cheap — no
per-message allocation. In C++, an `std::mutex` per `UpstreamConn` struct is the direct
equivalent.
