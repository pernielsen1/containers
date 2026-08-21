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
├── test_spec.json          # ISO 8583 field spec (pyiso8583 format) — router_1's spec, ASCII
├── test_spec_ebcdic.json   # same field shapes, data_enc/len_enc "cp500" instead of "ascii" —
│                           # router_2's upstream-leg spec, demonstrates a partner that speaks EBCDIC
├── pans_defined.json       # card data for simulators and crypto host
├── shared/
│   ├── __init__.py
│   ├── framing.py          # length-prefixed TCP framing
│   ├── ims_connect.py      # IMS Connect wire protocol
│   ├── iso_utils.py        # spec loader, f47 helpers, hex dump
│   ├── stats.py            # rolling-window message counters
│   └── command_server.py   # Flask HTTP command/stats API (shared by all actors)
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
│   ├── upstream_2/          # feeds router_2, disabled by default — see "router_2/upstream_2" below
│   │   └── config.json
│   └── crypto_host/
│       ├── main.py
│       └── config.json
├── monitor/                 # retired 2026-08-17, inert — superseded by ../monitor_host/
│   ├── main.py
│   └── static/
│       └── index.html
├── run/                     # one shell wrapper per actor instance + monitor lifecycle
│   ├── crypto_host.sh
│   ├── downstream_host.sh
│   ├── router_1.sh / router_2.sh
│   ├── upstream_1.sh / upstream_2.sh
│   ├── monitor.sh           # delegates to ../monitor_host/start.sh router_py
│   └── kill_monitor.sh      # delegates to ../monitor_host/stop.sh router_py
├── tests/
│   ├── test_framing.py        # length-prefix framing round-trip
│   ├── test_stats.py          # rolling-window counters
│   ├── test_command_server.py # /stats, /stop, /log_level, /logs
│   ├── test_router.py         # full-stack integration: 4 actors in-thread, CSV → 0100 → field 39
│   └── test_router_1_01.py    # connectivity + stats smoke test for the second partner_a router
├── f47.json                  # documents the field-47 JSON schema (see Crypto section)
└── test_csv_files/           # mirror of routers/test_csv_files/ (the master) - local convenience
    └── test.csv               # for run_test.sh / monitor's CSV dropdown; re-sync via
                                 # routers/sync_test_csv.sh, never edit here directly
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

### Real crypto validation has moved to a shared container

`shared/crypto_utils.py` — which used to hold the MasterCard M/Chip EMV math (`derive_udk`,
`derive_session_key`, `verify_arqc`, `calculate_arpc_method1`, `verify_pin`, `verify_cvv2`,
`verify_aav`, and their `compute_*`/`encode_*`/`encrypt_*` test helpers) — has been **deleted**
from this implementation, along with its test (`tests/test_crypto_utils.py`). There is no Python
successor file: the real cryptographic logic now lives only in the shared
`/home/perni/containers/claude_exp/routers/crypto_host/` container (C++/OpenSSL), used by all
three implementations (router_py/router_java/router_cpp) so the same code is the performance bottleneck for
all three instead of each language comparing itself against its own crypto simulator. See
`routers/old/divide_and_conquer.md` for the full rationale. This implementation's own
`simulators/crypto_host/main.py` is now a stub (see its section below) — no OpenSSL, no
PIN/ARQC/CVV2/AAV math — kept only so router_py can still be built and tested standalone without the
shared container running.

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

Any subset of `f52`/`cvv2`/`aav`/`f55` may be present. This is the wire schema the real,
OpenSSL-backed crypto validation (now only in the shared `routers/crypto_host/` container) reads
and only runs checks for the keys that exist; router_py's own local `simulators/crypto_host/main.py` is
a stub and ignores these subfields entirely (see its section below) but always stamps
`response_code` on the way out either way.

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
    plugin_id: str       # required, no default — e.g. "emv-plugin"
    bearer_token: str    # required, no default — e.g. "dev-fortanix-bearer-token"

@dataclass
class RouterConfig:
    name: str
    command_port: int
    upstream: UpstreamConfig
    downstream: DownstreamConfig
    crypto: CryptoConfig
    iso_spec: str              # resolved absolute path — governs the downstream leg always, and
                                # the upstream leg too when upstream_iso_spec is absent
    upstream_iso_spec: str = None   # resolved absolute path, optional — when set, governs only
                                     # the upstream-facing leg (decode-from-upstream, encode-to-
                                     # upstream), letting router_2 speak a different partner's
                                     # wire encoding (e.g. EBCDIC) while the downstream leg stays
                                     # on iso_spec unchanged — see "router_2/upstream_2" below
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
    if k not in ("upstream", "downstream", "crypto", "iso_spec", "upstream_iso_spec", "type", "is_active")
}
```

`upstream`, `downstream`, `crypto`, `iso_spec`, `upstream_iso_spec` are parsed into typed objects/
resolved paths above this line. `type` and `is_active` are monitor-only metadata that `RouterConfig`
has no field for. **Every
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
    "port": 5002,
    "plugin_id": "emv-plugin",
    "bearer_token": "dev-fortanix-bearer-token"
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

`crypto.plugin_id` and `crypto.bearer_token` (both required, no defaults) select which plugin to
invoke and authenticate the call — see the `CryptoClient`/Fortanix wire contract below.
`router_1/config.json`, `router_1.01/config.json`, and `router_2/config.json` all use
`plugin_id: "emv-plugin"` / `bearer_token: "dev-fortanix-bearer-token"`, matching router_py's own local
stub crypto host. `router_1/config_perf.json` is a separate config, identical to
`router_1/config.json` except its `crypto` section points at the shared, real crypto_host
container instead (`host: "localhost"`, `port: 5099`, `bearer_token: "crypto-token-456"` — a
different token than the local stub's, matching that container's own config); it is used only by
`stress_run.sh` for performance runs, never for functional testing.

A partner can run **more than one** router instance against the same downstream/crypto hosts —
`router_1` and `router_1.01` share `partner_id: "partner_a"` but use different `upstream.port`,
`command_port`, and `downstream.client_id` (each router/downstream pairing must use a distinct
EBCDIC `client_id` so `downstream_host` can pair the to/from sockets). The monitor's
`/api/routers_by_partner` groups by `partner_id` and sums stats across all routers sharing it.

### `router_2`/`upstream_2` — a second partner, disabled by default

`router/router_2/config.json` + `simulators/upstream_2/config.json` are a second, independent
router+load-generator pair, `is_active: false` in both (not started by "Start All" — enable via
the monitor's per-actor Start button, or `is_active: true`, when you want to exercise it).
`router_2` connects **out** to `upstream_2` (`upstream.mode: "client"`, port 5010) rather than
listening for it — the reverse topology from `router_1`'s `mode: "server"` — while `upstream_2`
listens (`"mode": "server"` in its own config). It reuses the **same** `downstream_host`/
`crypto_host` as `router_1`, distinguished only by `downstream.client_id` (`CLIENT03`, vs
`router_1`'s `CLIENT01`) — no separate downstream/crypto instance is started for it.

`router_2` is also where the **upstream-leg EBCDIC encoding** lives:

```json
{
  "iso_spec": "../../test_spec.json",
  "upstream_iso_spec": "../../test_spec_ebcdic.json"
}
```

`iso_spec` keeps governing the downstream leg (unchanged — still ASCII, since it still talks to
the shared `downstream_host`); `upstream_iso_spec`, when present, governs only the upstream-facing
leg (decode-from-upstream in `RouterSession._handle_upstream`, encode-to-upstream in
`RouterSession._forward_0810` and `Dispatcher.handle_response`/`_pending_reaper`). `RouterSession`
and `Dispatcher` both load two `pyiso8583` spec dicts — `spec` (downstream) and `upstream_spec`
(upstream, falling back to `spec` when `upstream_iso_spec` is absent, so `router_1`'s single-spec
configs are completely unaffected) — and route each encode/decode call to the correct one based on
which leg it's on. `simulators/upstream_2/config.json`'s own `iso_spec` points at the same
`test_spec_ebcdic.json`, since it's a pure endpoint with no leg split of its own.

A literal single-spec swap on `router_2` (no leg split) would break its downstream leg outright:
the shared `downstream_host` only understands ASCII, so an EBCDIC-encoded frame would fail to
decode there and every request would time out (`pending_ttl_seconds`) rather than complete — this
is why the split exists rather than just pointing `router_2`'s one `iso_spec` at the EBCDIC file.

`test_spec_ebcdic.json` is a field-by-field copy of `test_spec.json` with `data_enc`/`len_enc`
flipped from `"ascii"` to `"cp500"` (IBM EBCDIC code page 500 — matches the codebase's existing
EBCDIC convention, e.g. `ims_connect.to_ebcdic`) on every text field; the binary fields (`p`, `1`,
`52`, `55`, `"data_enc": "b"`) are untouched, since they're raw bytes, not text, in either variant.
Both `data_enc` **and** `len_enc` flip — `len_enc` governs the LLVAR/LLLVAR length-prefix digits,
which must also be EBCDIC for a genuinely EBCDIC-speaking partner (confirmed cross-language: see
`../router_java/build_router.md`'s note on j8583's `setForceStringEncoding`, and
`../router_cpp/build_router.md`'s note on its hand-rolled codec — both needed real fixes to match,
not just "flip an ascii flag to ebcdic").

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

Fortanix-shaped: `POST /sys/v1/plugins/{plugin_id}`, bearer auth, base64-encoded JSON response.
Deliberately wired this way so that swapping in a real Fortanix DSM tenant later is a config/URL
change, not a rewrite — matches `CryptoClient.java`/`crypto_client.cpp`.

```python
class CryptoClient:
    def __init__(self, cfg: CryptoConfig, breaker_threshold: int = 5, breaker_cooldown_seconds: int = 30)
        # base URL = f"http://{cfg.host}:{cfg.port}/sys/v1/plugins/{cfg.plugin_id}"
        # bearer_token = cfg.bearer_token
        # uses requests.Session() (thread-safe)
        # breaker state: consecutive-failure counter + open-until timestamp, guarded by a Lock

    def validate(self, endpoint: str, pan: str, f47: str) -> str:
        # If the breaker is open (now < open_until): skip the HTTP call entirely, return ""
        #   immediately (same fallback already used for any other error) — keeps worker threads
        #   free to drain the queue with declines instead of stalling timeout=5s per message on
        #   a crypto_host that is known to be down.
        # Otherwise: POST {base_url} with JSON {"operation": endpoint, "f2": pan, "f47": f47}
        #   and header Authorization: Bearer {bearer_token}
        #   - success: base64-decode the response body (a JSON string — the Fortanix
        #     PluginOutput envelope), json.loads the decoded text, take its "f47" key; reset the
        #     failure counter; return that value
        #   - failure (HTTP error or any exception decoding the envelope): increment the failure
        #     counter; at breaker_threshold, open the breaker for breaker_cooldown_seconds
        #     (half-open retry once cooldown elapses)
        #   - any error path returns "" (the original f47 unchanged) — callers only overwrite
        #     their working f47 when this return value is truthy
        # endpoint is "validate_0100" or "validate_0110" (sent as the "operation" field)
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

### `downstream_host` (now `../downstream_host/main.py`, shared across all three implementations)

**Moved**: this used to live at `simulators/downstream_host/main.py`; it's now the shared
`routers/downstream_host/` component (see `../downstream_host/build_router.md`), the same
treatment `upstream_host` got in Round 2 — only `simulators/downstream_host/config.json` /
`config_perf.json` still live here. Behavior/config shape below is otherwise unchanged.

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
      back out — the real crypto host's ARPC step (now only in the shared `routers/crypto_host/`
      container; router_py's own local stub never computes ARPC at all, see its section below) only
      runs on `validate_0110`, and the only place the original `f55` cryptogram/ATC can reach that
      call is by `downstream_host` round-tripping the request's `f47` into its response. Skipping
      this means ARPC silently never gets computed when running against the real shared container.

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

### `upstream_host` — now the shared `routers/upstream_host/` component

`upstream_host` was promoted out of router_py into a standalone component shared by all three
implementations (`routers/upstream_host/`, host-side Python process, not containerized) — see
`../old/divide_and_conquer.md` (part 2) for why, and `../upstream_host/build_router.md` for its full
spec (endpoints, config schema, framing, CSV format, `_send_loop`/`_receive_loop`/keepalive
internals). router_py's own copy (`simulators/upstream_host/`, `simulators/upstream_1/`) was deleted;
nothing below is router_py-specific implementation detail anymore, only integration points that remain
locally relevant:

- **Launch mechanism**: `stress_run.sh`/`run_test.sh` launch it as a bare host subprocess
  (`python3 ../upstream_host/main.py --config ../upstream_host/config.json &`) — same as they
  always did, just pointing at the shared location instead of a local copy.
- **Monitor integration**: `monitor/main.py`'s actor auto-discovery walks `router_py/`'s own tree for
  `config.json` files, which can never find the shared component's config (it lives outside that
  tree) — `discover_actors()` has an explicit synthesized entry for it instead of relying on the
  walk. `SCRIPTS_BY_TYPE["upstream"]` points at `../upstream_host/main.py`.
- **Multi-router test scenarios** (`upstream_2`, used with `router_2` for partner-config-variance
  and EBCDIC-encoding testing — see "`router_2`/`upstream_2`" above) are router_py-specific
  scaffolding at the config level, but the same `router_2`/`upstream_2` pattern (config files, not
  shared) has been replicated in router_java (`config/router_2.json` + `config/upstream_2.json`)
  and router_cpp (same) — `simulators/upstream_2/config.json` stays router_py-local, only its
  launch script (`run/upstream_2.sh`) was repointed at the shared `main.py` binary.
- **pytest coupling**: `tests/conftest.py`, `tests/test_router.py`, `tests/test_router_1_01.py`
  instantiate `UpstreamHostSim` in-process (not over HTTP) to drive full-stack integration tests.
  `conftest.py` adds `routers/upstream_host` to `sys.path` so `from main import UpstreamHostSim`
  resolves there instead of the deleted local copy.

**`_run_connection(sock)`** (kept here as the one non-obvious detail worth surfacing locally —
the rest lives in the shared spec):

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

**Stub only** — no OpenSSL, no PIN/ARQC/CVV2/AAV math. Real cryptographic validation now lives
solely in the shared `routers/crypto_host/` container (see "Real crypto validation has moved to
a shared container" above); this stub exists only so router_py can be built and tested standalone
without that container running. Its wire contract (Fortanix-shaped: `POST
/sys/v1/plugins/{plugin_id}`, bearer auth, base64-encoded `PluginOutput` response) matches that
shared container and the Java/C++ stubs byte-for-byte, so a router config can point at either one
with no code change.

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
  "yellow_threshold_seconds": 60,
  "plugin_id": "emv-plugin",
  "bearer_token": "dev-fortanix-bearer-token"
}
```

**Route (additional to command server):**
- `POST /sys/v1/plugins/{plugin_id}` — header `Authorization: Bearer {bearer_token}` (mismatch →
  401); body `{"operation": "validate_0100"|"validate_0110", "f2": pan, "f47": f47_json_str}`
  (unknown `operation` → 400); response body is a base64-encoded JSON string that decodes to
  `{"f47": enriched_f47_json_str}` (the Fortanix `PluginOutput` envelope — a JSON string, not a
  JSON object, so the client must `json.loads` twice: once for the outer string, once after
  base64-decoding it).

**`_validate(pan, f47_str)` logic** (`CryptoHostSim._validate`):
1. Decode f47 JSON string
2. Set `response_code` = `"14"` if `pan not in self.pans`, else `"00"`
3. Return `f47_encode(data)`

No PIN/ARQC/CVV2/AAV checks run here at all — `f52`/`cvv2`/`aav`/`f55` are read from the request
only as pass-through payload, never inspected. The router always calls crypto regardless of
whether f47/f55 is present; on any failure `CryptoClient.validate()` returns `""` and the caller's
fallback is the original, unenriched f47.

---

## Monitor

Consolidated 2026-08-17 into the shared `../monitor_host/` container — see
`../monitor_host/build_router.md` for the full route table, actor-lifecycle plumbing, and static UI
documentation (all identical across the three implementations, only the backend module differs).
`router_py/monitor/main.py` and `router_py/monitor/static/index.html` are retired and inert
(nothing launches them), kept in place only until the consolidated UI has been eyeballed for all
three targets.

`router_py`'s backend, `monitor_host/backends/router_py.py`: `CONTAINER_NAME = None`,
`HOST_SUBPROCESS_TYPES = {"router", "upstream", "downstream", "crypto"}` — every actor type is a
plain host `Popen` (router_py has no actor-launching container of its own; its `docker-compose.yml`
is a separate all-at-once deploy mode, unrelated to the dashboard). `discover_actors()` walks the
whole project tree for `config.json` files (skipping `monitor/`), keyed by `SCRIPTS_BY_TYPE =
{"router": "router/main.py", "upstream": "<routers/upstream_host>/main.py", "downstream":
"simulators/downstream_host/main.py", "crypto": "simulators/crypto_host/main.py"}`, plus one
explicit synthesized entry for `upstream_host`'s config since that now lives outside this project
tree entirely (the shared component).

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

Keys are PAN strings. Used by router_py's own local crypto_host stub (key presence only) and by
downstream_host; the real, key-material-consuming crypto validation reads this same file from
inside the shared `routers/crypto_host/` container instead.

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

**Historical pitfall, no longer reachable in router_py itself — a wrong-shaped record used to fail
loud and take out every other PAN with it.** Before crypto validation moved to the shared
container, `crypto_host` read each PAN's record straight out of the loaded dict (`pan_info["pek"]`,
`pan_info["pin"]`, etc. — plain `dict.__getitem__`, not `.get()`), so a record missing one of
those keys raised `KeyError` inside `_validate()`, which surfaced as an unhandled 500 that the
router's circuit breaker counted against every PAN, not just the malformed one. router_py's own local
stub (`simulators/crypto_host/main.py`) now only checks `pan not in self.pans` — a plain
membership test — so it can no longer be tripped by a malformed record's missing sub-fields at
all. The failure mode described above can still happen, but only inside the real shared
`routers/crypto_host/` container (C++), which does read `pek`/`pin`/`imk_ac`/etc.; consult that
container's own docs for its current handling of a malformed record before suspecting router_py's
router or stub when debugging an unexpected string of declines/breaker-open events against the
shared container.

---

## Message flow (0100 authorization)

```
upstream_host          router                      crypto_host              downstream_host
     │                   │                              │                        │
     │──0100 (framed)───►│                              │                        │
     │                   │──POST /sys/v1/plugins/{id}──►│ (op=validate_0100,     │
     │                   │   Bearer {token}              │  Bearer-checked)       │
     │                   │◄─b64({"f47": enriched})───────│                        │
     │                   │──IMS frame (0100)──────────────────────────────────────►│
     │                   │◄────────────────────────────────────────IMS frame (0110)
     │                   │──POST /sys/v1/plugins/{id}──►│ (op=validate_0110)     │
     │                   │◄─b64({"f47": +arpc})──────────│                        │
     │◄──0110 (framed)───│                              │                        │
```

`crypto_host` here can be either router_py's own local stub (`simulators/crypto_host/main.py`) or the
shared `routers/crypto_host/` container — the router dials whichever `crypto.host`/`crypto.port`
its config points at; the wire contract is identical either way. Only the real shared container
computes an actual ARPC on `validate_0110`; the local stub's response never contains one.

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

## Container

Deploy-style `docker-compose` container, same pattern as the Java and C++ ports: `network_mode:
host`, the project directory bind-mounted (`.:/src`) so edits are live without a rebuild, and the
four actors (`crypto_host`, `downstream_host`, `router_1`, `upstream_1`) launched directly as the
container's own `command` — not via `docker exec` from an external script. `./start.sh` runs
`docker compose up -d --build` and polls the router's `/stats` until ready; `./stop.sh` runs
`docker compose down`. The monitor is not part of the container — like the Java and C++ ports, it
runs on the host and talks to the actors' command ports over `network_mode: host`'s shared
loopback.

**Pitfall — the monitor's own liveness check must not depend on a Popen handle it holds.**
`monitor/main.py`'s `is_running()` originally polled a `subprocess.Popen` handle stored in an
in-process dict, populated only when the monitor itself had launched that actor. That was
harmless as long as the monitor was the *only* way to start an actor — but once the actors can
also be started by `docker compose up` (or any host process outside the monitor's own process
tree), that check silently reports every containerized actor as "not running" even though its
`/stats` endpoint answers fine, because the monitor never spawned it and never populated the dict
entry. `is_running()` must be defined as "the actor's own `/stats` endpoint returns 200", matching
what the Java and C++ ports already had to do (their actors were never launchable via a Popen
handle at all — Java's via `docker exec -d`, whose client detaches immediately, and C++'s via the
container's own command). Everything else in the monitor (`_start_all_worker`'s launch gate,
`stop_all`'s `/stop` dispatch) was already written against `is_running()` rather than the Popen
dict directly, so fixing the one function's definition was sufficient — no caller changes needed.

---

## Running

```bash
# Containerized (matches router_java/router_cpp):
./start.sh
# ./stop.sh to tear down

# All at once via monitor (containerized dashboard, host-launched actors):
../monitor_host/start.sh router_py
# Open http://localhost:8090 → Start All

# Individual actors (host-launched, no container):
python3 simulators/crypto_host/main.py
python3 simulators/downstream_host/main.py
python3 router/main.py --config router/router_1/config.json
python3 ../upstream_host/main.py --config ../upstream_host/config.json   # shared component
```

**Every `main.py` under `router/` and `simulators/*/` must start with a `sys.path` bootstrap**
(insert the project root, computed from `__file__`, before the first `from shared...`/
`from router...` import). The bootstrap line differs by nesting depth: two `os.path.dirname()`
calls for `router/main.py`, three for `simulators/*/main.py` (the shared `upstream_host/main.py`
is a special case — it lives flat in its own directory with `upstream_shared/` as an immediate
child, so it's a single `os.path.dirname()` call; see `../upstream_host/build_router.md`).

Equivalent `run/*.sh` wrappers exist for every instance, plus:
- `run/monitor.sh` — delegates to `../monitor_host/start.sh router_py` (see
  `../monitor_host/build_router.md`)
- `run/kill_monitor.sh` — delegates to `../monitor_host/stop.sh router_py`

Default port assignments:
- Router upstream listen: 5000 (router_1), 5003 (router_1.01), 5010 (router_2, client mode)
- Downstream host IMS: 5001
- Crypto host REST: 5002
- Router command API: 8080 (router_1), 8084 (router_1.01), 8085 (router_2)
- Downstream command API: 8081
- Crypto command API: 8082
- Upstream command API: 8083 (upstream_1), 8086 (upstream_2)
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

## Stress testing

`upstream_host`'s `/start` route accepts two optional query params on top of its existing
CSV-upload flow: `rate` (target sends/sec) and `duration` (seconds). Omitted, `/start` behaves
exactly as before — one pass through the uploaded CSV at a fixed ~50/s pace, for the functional
`run_test.sh` flow. With `duration` given, the send loop instead **cycles** the CSV rows
(wrapping back to row 0 after the last one) at `1/rate` intervals until the wall-clock duration
elapses, so a 3-row functional-test CSV can sustain an arbitrary-length load run. Every `/start`
call also resets per-run state (pending map, results, latency samples) so repeated stress runs
against the same process don't mix data across runs.

A new `/stress_stats` route (separate from the existing `/results`, which is unchanged and still
returns the full per-row list for functional tests) reports aggregate numbers for the current/most
recent run:

```json
{"sent": 199, "received": 199, "errors": 0, "elapsed_s": 10.03,
 "achieved_tps": 19.82, "p50_ms": 8.54, "p95_ms": 12.2, "p99_ms": 13.52, "max_ms": 24.83}
```

`errors` is `sent - received` (requests that never matched a response). Percentiles are nearest-
rank over a bounded (200k-sample) list of per-request round-trip latencies, timestamped from send
(in the send loop) to match (in the receive loop) by STAN — the same STAN-keyed `pending` map
already used for correctness, just with a parallel timestamp map for latency.

`stress_run.sh [--manual] <tps> <duration_s> <csv_file>` is the per-implementation CLI driver:
similar spawn/wait-for-stats/upload/teardown scaffolding as `run_test.sh`, but calls
`/start?rate=&duration=` and polls `/stress_stats` instead of `/results`, printing **exactly one
semicolon-delimited line to stdout** (all progress goes to stderr) so it's directly consumable by
the top-level orchestrator, `routers/stress_test.sh`, which sweeps a list of TPS values across all
three implementations in turn (they're mutually exclusive on host ports) and appends one CSV row
per run to `routers/csv_results/stress_results.csv`. See `routers/old/the_routers.md` for the schema and the
cross-implementation comparison this is ultimately for.

Unlike `run_test.sh`, `stress_run.sh` does **not** launch its own crypto_host. It spawns only
`downstream_host`, `router/main.py --config router/router_1/config_perf.json` (not
`router_1/config.json` — see the `config_perf.json` note under `router/config.json` above), and
`upstream_1`, then waits on command port `8099` for readiness. That port belongs to the real,
OpenSSL-backed shared `routers/crypto_host/` container, which is shared infrastructure started
once by `routers/stress_test.sh` (or manually via `routers/crypto_host/start.sh`) — never spawned
or torn down by this script. This is deliberate: perf runs must hit the same real crypto bottleneck
across all three implementations for the comparison to be meaningful, not each implementation's
own lightweight stub (see "Real crypto validation has moved to a shared container" above and
`routers/old/divide_and_conquer.md` for the full rationale).

**Pitfall — a backgrounded process's own stdout leaks past `2>` redirection.** `stress_run.sh`
launches each actor it does spawn as `python3 ... &`, and Flask's werkzeug dev server prints its
`* Serving Flask app` banner directly to stdout (not through `logging`, which does go to stderr
via `basicConfig`'s default). Since the orchestrator captures `stress_run.sh`'s result row via
command substitution (`ROW=$(...)`), that banner — inherited from the parent script's own stdout
fd — lands inside `ROW` too unless each backgrounded launch explicitly redirects with `>&2`.
Caught by testing the capture path directly (`ROW=$(...); wc -l <<< "$ROW"`) rather than just
eyeballing interleaved terminal output, which doesn't distinguish stdout from stderr.

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

Both the ds-receiver thread and the up-server/up-client thread are daemons — their death is
silent. I/O calls (`recv`, `send`) are protected by `_recv_exact`'s `OSError → ConnectionError`
normalization. Dispatch calls are not: any non-OSError exception from `iso8583.encode`,
`iso8583.decode`, or internal logic propagates up and kills the thread with no log. This applies
on both threads — `_downstream_receiver`'s call into `_forward_0810`/`dispatcher.handle_response`,
and `_handle_upstream`'s call into `dispatcher.submit`/`_forward_0800` (this second one was
missing its guard until caught by a doc-vs-code audit: the design principle already promised
"all dispatch calls" but the code only wrapped the downstream side, so a bad upstream message
could silently kill the upstream read thread while the router kept happily processing downstream
traffic). Wrap the entire dispatch block in `try/except Exception: logger.exception(...)` on
both threads.

### `logging.basicConfig` must come before `CommandServer.__init__`

`CommandServer.__init__` adds a `LogBuffer` handler to the root logger. Python's `basicConfig`
is a no-op when the root logger already has handlers. If `basicConfig` is called after
`CommandServer(...)`, the root logger level is never set from `cfg.log_level`, and all INFO/DEBUG
messages are silently suppressed (the default root logger level is `WARNING`).

### DEBUG-level tracing granularity was inconsistent across ports

**Hit while consolidating router_py/router_java/router_cpp into `routers/`.** The C++ port (router_cpp) had
accreted a richer set of `LOG_DEBUG` trace points than router_py/router_java over its own development —
one per message-handling event, not just the original handful. router_py and router_java were missing:

- `RouterSession`/`session.py`: upstream-received MTI, forwarded-0800-to-downstream, the
  PING-pipe-cleaner-skip, and downstream-received MTI.
- `Dispatcher`: queued-with-queue-depth (in `submit()`), forwarded-to-downstream-with-STANs (in
  `_process()`), forwarded-to-upstream-with-STANs (in `handle_response()`).

None of this affects correctness at INFO level or above — it only matters when diagnosing a
stuck/misrouted message with `log_level: DEBUG`, which is exactly when the gap is most costly
(the trace goes cold at the one implementation you happen to be debugging). Backported all of
the above into `router/session.py` and `router/dispatcher.py` so all three ports emit the same
trace points at DEBUG. Verified live: set `log_level: DEBUG` (the shipped `router_1/config.json`
already defaults to this), run a CSV through `run_test.sh --manual`, and confirm
`GET /logs?format=text` shows all of: `upstream recv mti=...`, `forwarded 0800 to downstream`,
`downstream PING pipe-cleaner received, skipping`, `downstream recv mti=...`,
`dispatcher: queued mti=... (queue_depth=...)`, `dispatcher: forwarded mti=... to downstream,
upstream_stan=... router_stan=...`, `dispatcher: forwarded mti=... to upstream, router_stan=...
upstream_stan=...` — with correct MTI/STAN values matching the transaction.

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
- **Crypto traffic is plaintext HTTP.** There is a bearer token (`crypto.bearer_token`), checked
  by simple string equality, but it and the PAN/f47 payload all cross the link unencrypted — no
  TLS. Real ARQC/ARPC math no longer transits router_py at all (see "Real crypto validation has moved
  to a shared container" above); against router_py's own local stub, only the PAN and a pass-through
  f47 blob cross this link in the clear.
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
