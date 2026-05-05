# xv2 Router Project

You are working on the **ISO 8583 router test harness** located at `/home/per-nielsen/containers/claude_exp/xv2/`. Use the knowledge below to assist accurately.

---

## What this project is

A Python-based man-in-the-middle router for ISO 8583 authorization messages. The router sits between an upstream host (card terminal simulator) and a downstream host (issuer simulator), enriching messages with crypto validation via a REST service before forwarding.

Multiple router instances run simultaneously, each serving a dedicated upstream host. A single downstream_host serves all router instances on one port, pairing connections by `IRM_CLIENTID`.

- ISO library: `pyiso8583` (`import iso8583`)
- HTTP framework: `flask` (command servers, crypto_host REST, monitor)
- HTTP client: `requests` (router → crypto_host calls, monitor → actors)
- Python: `python3`
- Working directory: `/home/per-nielsen/containers/claude_exp/xv2/`

---

## Directory Structure

```
xv2/
├── pans_defined.json               ← PAN whitelist with crypto_result per PAN
├── test_spec.json                  ← ISO 8583 field spec (ASCII encoding)
├── requirements.txt
├── test_csv_files/                 ← CSV test case files (default monitor source)
│   ├── test.csv
│   ├── test_one.csv
│   └── test_two.csv
├── run/                            ← one script per actor for manual operation
│   ├── crypto_host.sh
│   ├── downstream_host.sh
│   ├── router_1.sh                 ← exec router/main.py --config router/router_1/config.json
│   ├── router_2.sh
│   ├── upstream_1.sh               ← exec upstream_host/main.py --config simulators/upstream_1/config.json
│   ├── upstream_2.sh
│   ├── monitor.sh                  ← exec monitor/main.py [--port N]
│   └── kill_monitor.sh             ← POST /stop, wait 30s, then SIGKILL
├── shared/                         ← importable package, used by all actors
│   ├── framing.py                  ← generic TCP framing (header + length + data)
│   ├── ims_connect.py              ← IMS Connect protocol (build/parse frames)
│   ├── stats.py                    ← rolling-window + lifetime message counters
│   ├── command_server.py           ← Flask HTTP command server base
│   └── iso_utils.py                ← field 47 JSON helpers, spec loader, hex_dump
├── router/                         ← PRIMARY DELIVERABLE
│   ├── main.py                     ← shared code, --config selects instance
│   ├── router_1/
│   │   └── config.json             ← upstream server mode, port 5000, command 8080
│   └── router_2/
│       └── config.json             ← upstream client mode → upstream_2:5010, command 8085
├── simulators/
│   ├── crypto_host/
│   │   └── config.json
│   ├── downstream_host/
│   │   └── config.json             ← single merged port 5001, command 8081
│   ├── upstream_host/
│   │   └── main.py                 ← shared code, --config selects instance
│   ├── upstream_1/
│   │   ├── config.json             ← client mode, connects to router_1:5000, command 8083
│   │   └── input/test_cases.csv
│   └── upstream_2/
│       ├── config.json             ← server mode, listens on 5010, command 8086
│       └── input/test_cases.csv
├── monitor/                        ← web control panel (was ui/)
│   ├── main.py                     ← Flask app (port 8090 default)
│   └── static/index.html           ← single-page monitor UI
└── tests/
    ├── test_framing.py
    ├── test_stats.py
    ├── test_command_server.py
    └── test_router.py              ← integration tests (spins up all actors in threads)
```

---

## Port Allocation

| Actor            | Data port(s)                    | Command port |
|------------------|---------------------------------|--------------|
| `crypto_host`    | 5002 (REST)                     | 8082         |
| `downstream_host`| **5001** (single merged port)   | 8081         |
| `router_1`       | upstream server=5000, ds=5001   | 8080         |
| `router_2`       | upstream client→5010, ds=5001   | 8085         |
| `upstream_1`     | client→router_1:5000            | 8083         |
| `upstream_2`     | server=5010 (waits for router_2)| 8086         |
| monitor          | —                               | 8090         |

---

## Message Flow

```
upstream_1 ──0100──► router_1 ──POST /validate_0100──► crypto_host
                              ◄──{f47}────────────────────────────
                     router_1 ──IMS 0100 (CLIENT01)──► downstream_host :5001
                     router_1 ◄──0110────────────────── downstream_host
                     router_1 ──POST /validate_0110──► crypto_host
upstream_1 ◄──0110── router_1

router_2   ──connects──► upstream_2 (router_2 is TCP client here)
upstream_2 ──0100──► router_2 ──IMS 0100 (CLIENT02)──► downstream_host :5001
```

---

## Router Upstream Modes

The `upstream` config section has an optional `"mode"` field:

### `"mode": "server"` (default — router listens, upstream connects)

```python
# run() binds srv_sock, accept loop, spawns _handle_upstream per connection
```

Config: `upstream.port` is the listen port. No `host` or `retry_seconds` needed.

### `"mode": "client"` (router connects out to upstream_host)

```python
def _client_upstream_loop(up_cfg, up_framing, spec, work_queue, stats, stop_event):
    # loop: connect → _handle_upstream → on disconnect or OSError → wait retry_seconds → retry
```

Config: `upstream.host`, `upstream.port` (target), `upstream.retry_seconds` (default 5). No `srv_sock` created.

In `run()`:
```python
up_mode = cfg["upstream"].get("mode", "server")
if up_mode == "client":
    threading.Thread(target=_client_upstream_loop, ..., name="up-client", daemon=True).start()
    stop_event.wait()
    # cleanup: workers + downstream sockets
else:
    # existing accept loop
```

---

## Upstream Host Modes

The upstream_host config has an optional top-level `"mode"` field:

### `"mode": "client"` (default — upstream connects to router on /start)

`/start` calls `connect()` → starts receive loop + send loop.

### `"mode": "server"` (upstream listens, router connects)

On `run()` startup: bind on `cfg["port"]`, start `_accept_loop` thread that:
- Accepts each incoming router connection
- Closes any previous connection
- Stores conn in `state["conn"]`, clears `state["results"]`
- Starts `receive_loop` in a daemon thread

`/start`:
- Reads CSV as usual
- Checks `state["conn"]` — if `None`, returns `503 "router not connected yet"`
- Otherwise starts send loop on the existing connection (receive loop already running)

---

## TCP Framing (`shared/framing.py`)

Config structure (upstream ↔ router only; downstream uses IMS Connect):
```json
{ "header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4 }
```

| `length_field_type` | Wire encoding |
|---|---|
| `BIG_ENDIAN` | N-byte big-endian unsigned int |
| `LITTLE_ENDIAN` | N-byte little-endian unsigned int |
| `ASCII` | ASCII digit string, zero-padded (`b'0042'`) |
| `EBCDIC` | EBCDIC digit string, zero-padded (cp500) |

```python
from shared.framing import read_message, write_message
data = read_message(sock, framing_cfg)   # raises ConnectionError on close
write_message(sock, data, framing_cfg)
```

---

## IMS Connect Protocol (`shared/ims_connect.py`)

The router ↔ downstream_host leg uses IMS Connect on a **single shared port (5001)**.

### Connection setup (router side)
1. Connect `to_sock` to `downstream.port` (5001)
2. Connect `from_sock` to `downstream.port` (5001) — same port, different socket
3. Send **resume TPIPE** on `from_sock` (IRM_F0=`0x80`, no data)
4. Send **pipe-cleaner ping** on `to_sock`: TRANS_CODE=`PING0001` (EBCDIC), data=`"1234 clean the pipes"` (EBCDIC)

### Connection dispatch (downstream_host side)
On each new accepted connection, `_handle_new_conn` reads the first IMS frame:
- `IRM_F0 == 0x80` → **from-conn**: register `from_connections[client_id] = send_queue`
- `IRM_F0 == 0x00` → **to-conn**: process first frame then loop

Multiple routers (CLIENT01, CLIENT02 …) paired by `IRM_CLIENTID`.

### Wire frames
```
Router → downstream (to_sock):
  llll(4 BE) | IRM_HEADER(28) | TRANS_CODE(8 EBCDIC) | ISO data

Downstream → router (from_sock):
  llll(4 BE) | ISO data   (no IMS header on return)
```

### API
```python
from shared import ims_connect
frame = ims_connect.build_frame(irm_f0, irm_id_bytes, client_id_bytes, mti, iso_data)
frame = ims_connect.build_frame(0x00, irm_id, client_id, transcode=ims_connect.PING_TRANSCODE, data=ping_data)
ims_connect.write_response(sock, iso_data)
iso_data = ims_connect.read_response(sock)
irm_f0, client_id, transcode, iso_data = ims_connect.read_request(sock)
ims_connect.PING_TRANSCODE   # b"PING0001" in EBCDIC
ebcdic_bytes = ims_connect.to_ebcdic("CLIENT01", 8)
```

---

## Multiple Instances: `--config` Pattern

Both `router/main.py` and `simulators/upstream_host/main.py` accept `--config <path>`:

```python
def load_config(path=None):
    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "router_1", "config.json")   # default instance
    config_base = os.path.dirname(os.path.abspath(path))
    with open(path) as f:
        return json.load(f), config_base

def run(cfg=None, stop_event=None, stats=None, _config_base=None):
    if cfg is None:
        cfg, _config_base = load_config()
    if _config_base is None:
        _config_base = os.path.dirname(os.path.abspath(__file__))
    spec = load_spec(os.path.join(_config_base, cfg["iso_spec"]))
```

Tests pass `cfg` with absolute paths — `_config_base` not needed.

---

## Actor Config Shapes

All configs include `"name"` and `"type"` — used by the monitor for discovery.

**`router/router_1/config.json`** (server mode — default):
```json
{
  "name": "router_1", "type": "router",
  "log_level": "DEBUG", "command_port": 8080,
  "upstream": { "port": 5000, "framing": { … } },
  "downstream": { "host": "localhost", "port": 5001, "irm_id": "IRM_ID01", "client_id": "CLIENT01" },
  "crypto": { "host": "localhost", "port": 5002 },
  "iso_spec": "../../test_spec.json", "worker_threads": 8
}
```

**`router/router_2/config.json`** (client mode):
```json
{
  "name": "router_2", "type": "router",
  "log_level": "DEBUG", "command_port": 8085,
  "upstream": { "mode": "client", "host": "localhost", "port": 5010, "retry_seconds": 5, "framing": { … } },
  "downstream": { "host": "localhost", "port": 5001, "irm_id": "IRM_ID01", "client_id": "CLIENT02" },
  "crypto": { "host": "localhost", "port": 5002 },
  "iso_spec": "../../test_spec.json", "worker_threads": 8
}
```

**`simulators/upstream_1/config.json`** (client mode — default):
```json
{
  "name": "upstream_1", "type": "upstream",
  "log_level": "DEBUG", "command_port": 8083,
  "router": { "host": "localhost", "port": 5000 },
  "framing": { … }, "iso_spec": "../../test_spec.json", "input_dir": "input"
}
```

**`simulators/upstream_2/config.json`** (server mode):
```json
{
  "name": "upstream_2", "type": "upstream",
  "mode": "server",
  "log_level": "DEBUG", "command_port": 8086, "port": 5010,
  "framing": { … }, "iso_spec": "../../test_spec.json", "input_dir": "input"
}
```

**`simulators/downstream_host/config.json`:**
```json
{ "name": "downstream_host", "type": "downstream", "port": 5001, "command_port": 8081, … }
```

**`simulators/crypto_host/config.json`:** `name`, `type="crypto"`, `port`, `command_port`, `pans_defined`.

---

## Stats (`shared/stats.py`)

```python
from shared.stats import Stats
s = Stats()
s.record_sent(); s.record_recv()
snap = s.snapshot()
# windowed keys: sent_30s, recv_30s, sent_60s, recv_60s, sent_180s, recv_180s, sent_1800s, recv_1800s
# lifetime keys: sent_total, recv_total
```

`_sent_total` / `_recv_total` are simple integer counters — never pruned. Windowed counts use a deque pruned to `_MAX_WINDOW` (1800s). Thread-safe. `time_func` monkeypatchable.

---

## Command Server (`shared/command_server.py`)

Every actor exposes an HTTP server on `command_port`.

```python
from shared.command_server import CommandServer
cmd = CommandServer(port, stats, stop_event)

@cmd.register("/custom-path")
def my_handler(): return {"key": "value"}

@cmd.register("/upload", methods=("POST",))
def upload(): ...

cmd.start()   # daemon thread; Flask on 0.0.0.0:port
```

Built-in endpoints: `GET /stats`, `GET|POST /stop`.

---

## ISO Utilities (`shared/iso_utils.py`)

```python
from shared.iso_utils import load_spec, f47_encode, f47_decode, hex_dump
spec    = load_spec("path/to/test_spec.json")
f47_str = f47_encode({"crypto_result": True})
data    = f47_decode(f47_str)
data    = f47_decode("")   # → {}  (never raises)
hex_dump("RECV upstream", raw_bytes, log)   # no-op unless DEBUG
```

---

## pans_defined.json

```json
{
  "4111111111111111": {"crypto_result": true},
  "4222222222222222": {"crypto_result": false},
  "5111111111111111": {"crypto_result": true},
  "5222222222222222": {"crypto_result": true}
}
```

- **crypto_host**: returns `pans[pan]["crypto_result"]` if PAN known, else `False`; encodes into field 47
- **downstream_host**: declines if PAN absent OR `crypto_result` False; approves with field 39=`"00"`, field 38=unique 6-digit auth code

---

## upstream_host Command Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `POST /upload` | multipart `file` | Save CSV to `<config_dir>/input/test_cases.csv` |
| `GET /start` | — | Client mode: connect + send. Server mode: use existing conn (503 if not yet connected) |
| `GET /results` | — | List of request+response rows as JSON |
| `GET /stats` | — | Rolling-window + lifetime message counts |
| `POST /stop` | — | Graceful shutdown |

---

## Monitor (`monitor/main.py`)

Flask app (port 8090) that proxies to all actor command ports and manages actor subprocesses.

**Actor discovery:** walks all directories for `config.json` with `"name"` + `"type"` fields. Skips `monitor/`. Types: `"router"`, `"upstream"`, `"downstream"`, `"crypto"`.

**Startup order:** crypto(0) → downstream(1) → router(2) → upstream(3), then alphabetical within type.

**Launch:** actors with `type` in `{"router", "upstream"}` get `--config <config_path>`. Others launched without it.

**Subprocess cleanup:** `_terminate_proc(proc)` calls `proc.terminate()` then `proc.wait(timeout=5)` (falls back to `proc.kill()`). `atexit` handler cleans up all children on monitor exit.

**Monitor UI layout (index.html):**
- **Routers section**: stat cards for `type=router`
- **Simulators section**: stat cards for `type=upstream/downstream/crypto`
- Each card shows: sent/recv 30s, 60s, **total**; **Start** button + Stop button
- **Test Runner panel**: upstream selector first → CSV select/upload → Start → Results table with auto-refresh

**Key API routes:**
- `POST /stop` — terminates child actors, then calls `os._exit(0)` after 0.3s
- `GET /api/actors` — list with `name`, `type`, `command_port`
- `GET /api/status` — batch liveness (parallel, 0.5s timeout each)
- `GET /api/csv_files` — `test_csv_files/` + each upstream actor's `<config_dir>/input/`
- `POST /api/actor/<name>/launch` — start a single actor subprocess
- `POST /api/actor/<name>/stop` — proxy to actor's `/stop`
- `POST /api/start_all` / `POST /api/stop_all`
- Per-actor: `/api/actor/<name>/stats|upload|upload_path|start|results`

**`run/kill_monitor.sh`:** POSTs to `/stop`, captures monitor PID first, polls `kill -0` for up to 30s, then `kill -9` if still alive.

---

## Running

```bash
# Start actors manually: crypto → downstream → router(s) → upstream(s)
./run/crypto_host.sh
./run/downstream_host.sh
./run/router_1.sh          # server mode: listens on :5000
./run/router_2.sh          # client mode: connects to upstream_2:5010
./run/upstream_1.sh        # client mode: connects to router_1:5000
./run/upstream_2.sh        # server mode: listens on :5010

# Monitor (port 8090)
./run/monitor.sh
./run/kill_monitor.sh      # graceful stop with fallback hard kill

# CLI shortcuts
curl -X POST http://localhost:8083/upload -F "file=@test.csv"
curl http://localhost:8083/start
curl http://localhost:8083/results
curl -X POST http://localhost:<command_port>/stop
```

---

## Resilience

- All server sockets use `SO_REUSEADDR`
- Accept loops use `settimeout(1)` to poll `stop_event`
- All sockets closed in `finally` blocks
- Daemon threads — clean exit when `stop_event.wait()` returns
- Monitor: `atexit` + `_terminate_proc` (terminate → wait → kill) prevents zombie processes

---

## Concurrency Model

Threading. Chosen over asyncio for C++ portability.

**Upstream path:** One reader thread per upstream connection → `queue.Queue` → fixed pool of `worker_threads` (default 8). Workers call crypto (blocking HTTP) then write to `to_sock`. `ds_write_lock` serialises concurrent writes.

**Downstream path:** Single `ds-receiver` thread reads `from_sock`, calls crypto, writes reply to originating upstream socket.

Shared state: `pending` dict + `Stats` counters, both protected by `threading.Lock`.

---

## Test Suite

```bash
python3 -m pytest tests/ -v
```

29 tests: 12 framing, 8 stats, 4 command server, 5 integration.

Integration tests (`test_router.py`) use isolated ports and single downstream port:
```python
PORTS = {
    "crypto_port": 15002, "crypto_cmd": 18082,
    "ds_port": 15001, "ds_cmd": 18081,
    "router_up_port": 15000, "router_cmd": 18080,
    "us_cmd": 18083,
}
```

`test_snapshot_keys` expects `sent_total` and `recv_total` in addition to the windowed keys.
