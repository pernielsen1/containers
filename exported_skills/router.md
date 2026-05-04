# xv2 Router Project

You are working on the **ISO 8583 router test harness** located at `/home/perni/containers/claude_exp/xv2/`. Use the knowledge below to assist accurately.

---

## What this project is

A Python-based man-in-the-middle router for ISO 8583 authorization messages. The router sits between an upstream host (card terminal simulator) and a downstream host (issuer simulator), enriching messages with crypto validation via a REST service before forwarding.

- ISO library: `pyiso8583` (`import iso8583`)
- HTTP framework: `flask` (command servers, crypto_host REST, UI)
- HTTP client: `requests` (router → crypto_host calls)
- Python: `python3`
- Working directory: `/home/perni/containers/claude_exp/xv2/`

---

## Directory Structure

```
xv2/
├── brief.md                        ← project requirements
├── brief_imsconnect.md             ← IMS Connect protocol spec
├── brief_ui.md                     ← UI requirements
├── pans_defined.json               ← PAN whitelist with crypto_result per PAN
├── test_spec.json                  ← ISO 8583 field spec (ASCII encoding)
├── requirements.txt
├── run_test.sh                     ← automated test run: ./run_test.sh [--manual] <csv>
├── run_test_manually.sh            ← shorthand for run_test.sh --manual
├── test_csv_files/                 ← CSV test case files (default UI source)
│   ├── test.csv
│   ├── test_one.csv
│   └── test_two.csv
├── run/                            ← one script per actor for manual operation
│   ├── crypto_host.sh
│   ├── downstream_host.sh
│   ├── router.sh
│   ├── upstream_host.sh
│   └── ui.sh
├── shared/                         ← importable package, used by all actors
│   ├── framing.py                  ← generic TCP framing (header + length + data)
│   ├── ims_connect.py              ← IMS Connect protocol (build/parse frames)
│   ├── stats.py                    ← rolling-window message counters
│   ├── command_server.py           ← Flask HTTP command server base
│   └── iso_utils.py                ← field 47 JSON helpers, spec loader, hex_dump
├── router/                         ← PRIMARY DELIVERABLE
│   ├── config.json
│   └── main.py
├── simulators/                     ← test infrastructure only
│   ├── crypto_host/
│   ├── downstream_host/
│   └── upstream_host/
│       └── input/                  ← uploaded CSV test cases land here
├── ui/                             ← web control panel
│   ├── main.py                     ← Flask app (port 8090 default)
│   └── static/index.html           ← single-page UI
└── tests/
    ├── test_framing.py
    ├── test_stats.py
    ├── test_command_server.py
    └── test_router.py              ← integration tests (spins up all actors in threads)
```

---

## Message Flow

```
upstream_host ──0100──► router ──POST /validate_0100──► crypto_host
                                ◄──{f47 with crypto_result}───────────
                        router ──IMS 0100──► downstream_host (to_sock)
                        router ◄──0110────── downstream_host (from_sock)
                        router ──POST /validate_0110──► crypto_host
                                ◄──{f47 with crypto_result}───────────
upstream_host ◄──0110── router (f47 enhanced)
```

**Key router behaviour:**
- Read loop per upstream connection immediately enqueues messages; a fixed thread pool (configurable `worker_threads`, default 8) processes crypto + downstream send — non-blocking within and across connections
- STAN (field 11) correlation: router generates its own STAN for the downstream leg, stores `pending[router_stan] = {up_conn, upstream_stan}`, restores original STAN in the 0110 reply
- Two persistent TCP connections to downstream_host: `to_sock` (send 0100) and `from_sock` (receive 0110), shared across all worker threads
- `ds_write_lock` serialises concurrent worker writes to `to_sock`

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

**Upstream ↔ router framing:** ASCII 4-byte. Downstream uses IMS Connect — see below.

---

## IMS Connect Protocol (`shared/ims_connect.py`)

The router ↔ downstream_host leg uses IMS Connect, not plain framing.

### Connection setup (router side)
1. Connect `to_sock` to `downstream.to_downstream_port`
2. Connect `from_sock` to `downstream.from_downstream_port`
3. Send **resume TPIPE** on `from_sock` (IRM_F0=`0x80`, no data)
4. All 0100s sent on `to_sock`; all 0110s received on `from_sock`

### Wire frame (router → downstream, `to_sock`)
```
llll (4 bytes BIG_ENDIAN)  = IRM_HEADER_LEN(28) + TRANS_CODE_LEN(8) + len(ISO data)
IRM_LEN      2 bytes = 0x001C (28)
IRM_ARCH     1 byte  = 0x04
IRM_F0       1 byte  = 0x00 (normal) | 0x80 (resume TPIPE)
IRM_ID       8 bytes EBCDIC  (configurable, e.g. "IRM_ID01")
IRM_NAK_RSNCDE 2 bytes = 0x0000
IRM_RES      2 bytes = 0x0000
IRM_F5       1 byte  = 0x00
IRM_TIMER    1 byte  = 0x15
IRM_SOCT     1 byte  = 0x10
IRM_ES       1 byte  = 0x01
IRM_CLIENTID 8 bytes EBCDIC  (configurable, e.g. "CLIENT01")
TRANS_CODE   8 bytes EBCDIC  = "TRAN" + MTI  (e.g. "TRAN0100") — only if data present
ISO data     N bytes
```

Resume TPIPE: IRM_F0=`0x80`, `llll`=28, no TRANS_CODE, no data.

### Wire frame (downstream → router, `from_sock`)
```
llll (4 bytes BIG_ENDIAN) = len(ISO data)
ISO data     N bytes       (no IMS header on return)
```

### API
```python
from shared import ims_connect

# encoding
frame = ims_connect.build_frame(irm_f0, irm_id_bytes, client_id_bytes, mti, iso_data)
ims_connect.write_response(sock, iso_data)   # downstream simulator side

# decoding
iso_data = ims_connect.read_response(sock)                       # router from_sock
irm_f0, client_id, iso_data = ims_connect.read_request(sock)    # simulator to_sock

# helpers
ebcdic_bytes = ims_connect.to_ebcdic("CLIENT01", 8)
```

IRM_CLIENTID is at byte offset 20 within the 28-byte IMS header; used as correlation key between `to_sock` and `from_sock` in the downstream simulator.

---

## Stats (`shared/stats.py`)

```python
from shared.stats import Stats
s = Stats()
s.record_sent(); s.record_recv()
snap = s.snapshot()
# keys: sent_30s, recv_30s, sent_60s, recv_60s, sent_180s, recv_180s, sent_1800s, recv_1800s
```

Thread-safe. `time_func` monkeypatchable for time-travel in tests.

---

## Command Server (`shared/command_server.py`)

Every actor exposes an HTTP server on `command_port`.

```python
from shared.command_server import CommandServer
cmd = CommandServer(port, stats, stop_event)

@cmd.register("/custom-path")
def my_handler(): return {"key": "value"}   # auto-wrapped in jsonify

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
f47_str = f47_encode({"crypto_result": True})   # → '{"crypto_result":true}'
data    = f47_decode(f47_str)                    # → {"crypto_result": True}
data    = f47_decode("")                         # → {}  (never raises)
hex_dump("RECV upstream", raw_bytes, log)        # no-op unless DEBUG
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
- **downstream_host**: declines if PAN absent OR `f47_decode(f47)["crypto_result"]` is `False`; approves otherwise (field 39 = `"00"`, field 38 = unique 6-digit auth code per session)

---

## Actor config.json shapes

**router/config.json:**
```json
{
  "log_level": "INFO",
  "command_port": 8080,
  "upstream": { "port": 5000, "framing": { "header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4 } },
  "downstream": {
    "host": "localhost",
    "to_downstream_port": 5001,
    "from_downstream_port": 5003,
    "irm_id": "IRM_ID01",
    "client_id": "CLIENT01"
  },
  "crypto": { "host": "localhost", "port": 5002 },
  "iso_spec": "../test_spec.json",
  "worker_threads": 8
}
```

**downstream_host/config.json:**
```json
{
  "log_level": "INFO",
  "to_downstream_port": 5001,
  "from_downstream_port": 5003,
  "command_port": 8081,
  "iso_spec": "../../test_spec.json",
  "pans_defined": "../../pans_defined.json"
}
```

**crypto_host/config.json:** `port`, `command_port`, `pans_defined`.

**upstream_host/config.json:** `command_port`, `router.host/port`, `framing` (ASCII 4-byte), `iso_spec`, `pans_defined`, `input_dir`.

`log_level` accepts: `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`. At DEBUG, hex dumps of every received raw message are logged.

---

## upstream_host command endpoints

| Endpoint | Method | Description |
|---|---|---|
| `POST /upload` | multipart `file` field | Save CSV to `input/test_cases.csv` |
| `GET /start` | — | Connect to router and begin sending CSV rows |
| `GET /results` | — | Return list of request+response rows as JSON |
| `GET /stats` | — | Rolling-window message counts |
| `POST /stop` | — | Graceful shutdown |

CSV format: semicolon-separated, utf-8-sig, first row = column headers (ISO 8583 field numbers). Fixed-length fields are zero-padded automatically.

---

## Running

```bash
# Automated test run (starts/stops all actors)
./run_test.sh test_csv_files/test.csv

# Manual mode (actors already running)
./run_test.sh --manual test_csv_files/test.csv
./run_test_manually.sh test_csv_files/test.csv   # shorthand

# Start actors manually in order: crypto → downstream → router → upstream
./run/crypto_host.sh
./run/downstream_host.sh
./run/router.sh
./run/upstream_host.sh

# Web UI (port 8090, start/stop actors, upload CSV, view results)
./run/ui.sh            # → http://localhost:8090
./run/ui.sh --port 9000

# Upload and run from CLI
curl -X POST -F "file=@test_csv_files/test.csv" http://localhost:8083/upload
curl http://localhost:8083/start
curl http://localhost:8083/results

# Stop any actor
curl -X POST http://localhost:<command_port>/stop
```

**Default ports:**

| Actor | Data port(s) | Command port |
|---|---|---|
| upstream_host | connects to router:5000 | 8083 |
| router upstream | 5000 | 8080 |
| downstream_host to_sock | 5001 | 8081 |
| downstream_host from_sock | 5003 | — |
| crypto_host | 5002 (REST) | 8082 |
| UI | — | 8090 |

---

## Web UI (`ui/main.py`)

Flask app that proxies to all actor command ports. Auto-discovers actors by scanning for `config.json` files. Can start/stop all actors as subprocesses (in dependency order with readiness waiting).

Key API routes:
- `GET /api/actors` — list of discovered actors
- `GET /api/status` — batch liveness check (all actors, parallel, 0.5s timeout each)
- `GET /api/csv_files` — scans `test_csv_files/` and `simulators/upstream_host/input/` for CSVs
- `POST /api/actor/<name>/upload_path` — `{"path": "test_csv_files/test.csv"}` — server-side read (avoids Windows file dialog in WSL)
- `POST /api/start_all` / `POST /api/stop_all`
- Per-actor: `/api/actor/<name>/stats|stop|upload|start|results`

---

## Resilience

- All server sockets use `SO_REUSEADDR`
- Accept loops use `settimeout(1)` to poll `stop_event`
- All sockets closed in `finally` blocks
- Daemon threads — clean exit when `stop_event.wait()` returns

---

## Concurrency model

Threading. Chosen over asyncio for C++ portability.

**Upstream path:** One reader thread per upstream connection → `queue.Queue` → fixed pool of `worker_threads` (default 8) threads. Workers call crypto (blocking HTTP) then write to `to_sock`. `ds_write_lock` serialises concurrent writes to `to_sock`.

**Downstream path:** Single `ds-receiver` thread reads from `from_sock`, calls crypto, writes reply back to the originating upstream connection socket.

Shared state: `pending` dict + `Stats` counters, both protected by `threading.Lock`.

---

## Test suite

```bash
python3 -m pytest tests/ -v
```

29 tests: 12 framing, 8 stats, 4 command server, 5 integration. Integration tests spin up all four actors as threads (not subprocesses) using isolated high-numbered ports (15000–15003 data, 15001/15003 IMS Connect, 18080–18083 command).
