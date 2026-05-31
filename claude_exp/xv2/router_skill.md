# Router Skill

Provide context and assistance for the ISO 8583 router project at `/home/perni/containers/claude_exp/xv2/`.

## What was built

A multi-instance ISO 8583 message router with:
- Two **routers** that accept upstream connections and forward 0100/0120/0420 requests downstream
- Two **upstream_hosts** (simulators) that connect to routers and send 0100/0120/0420/0800 messages
- One **downstream_host** (simulator) that processes auth/advice/reversal requests and replies 0110/0130/0430
- One **crypto_host** (simulator) that validates PANs and signs field 47 (REST service)
- A **monitor** web UI (Flask + vanilla JS) at `http://localhost:8090` that starts/stops/monitors all actors

## Architecture

```
upstream_1 ──→ router_1 ──→┐
upstream_2 ──→ router_2 ──→┤──→ downstream_host
                            └──→ crypto_host (REST, both routers)
```

### Message flow (0100 auth)

1. upstream sends `0100` to router (ISO 8583, ASCII-length-framed)
2. router calls `crypto_host /validate_0100` (REST) — enriches field 47
3. router forwards enriched `0100` to downstream_host (IMS-connect framing)
4. downstream_host replies `0110` back through router
5. router calls `crypto_host /validate_0110` (REST) — validates field 47
6. router returns `0110` to upstream

### Message flow (0120 advice)

1. upstream sends `0120` (decision already taken — F38/F39 pre-filled)
2. router forwards to downstream_host as-is (no crypto call)
3. downstream_host always replies `0130` with F39=00 (approved)
4. router returns `0130` to upstream

### Message flow (0420 reversal)

1. upstream sends `0420` (command to revert a prior transaction)
2. router forwards to downstream_host as-is (no crypto call)
3. downstream_host always replies `0430` with F39=00 (accepted)
4. router returns `0430` to upstream

### Keepalive (0800/0810)

- upstream sends `0800` ping every `ping_0800_seconds` (default 30s)
- downstream_host replies `0810`
- router forwards both directions transparently
- if no `0810` received within `yellow_threshold_seconds` → actor goes **yellow**

## Port allocation

| Process           | Data port(s)                     | Command port |
|-------------------|----------------------------------|-------------|
| `crypto_host`     | 5002 (REST)                      | 8082        |
| `downstream_host` | 5001 (IMS-connect, single port)  | 8081        |
| `router_1`        | upstream=5000, downstream=5001   | 8080        |
| `router_2`        | upstream=5010 (client), ds=5001  | 8085        |
| `upstream_1`      | connects to 5000                 | 8083        |
| `upstream_2`      | connects to 5010                 | 8086        |
| `monitor`         | —                                | 8090        |

## Directory layout

```
xv2/
├── router/
│   ├── __init__.py
│   ├── main.py          # entry point (~60 lines): arg parse, command server, reconnect loop
│   ├── config.py        # RouterConfig dataclass + sub-configs (Framing, Upstream, Downstream, Crypto)
│   ├── session.py       # RouterSession: owns one connected session, teardown order
│   ├── dispatcher.py    # Dispatcher: STAN generator, pending map, worker pool, routing logic
│   ├── upstream.py      # UpstreamServer / UpstreamClient (clean split of two modes)
│   ├── downstream.py    # DownstreamConnection: IMS pair + thread-safe send()
│   ├── crypto_client.py # CryptoClient: HTTP session, single validate() method
│   ├── router_1/config.json   # upstream server mode (listens on 5000)
│   └── router_2/config.json   # upstream client mode (connects to 5010)
├── simulators/
│   ├── upstream_host/main.py  # shared by upstream_1 and upstream_2
│   ├── upstream_1/config.json
│   ├── upstream_2/config.json
│   ├── downstream_host/main.py
│   ├── downstream_host/config.json
│   ├── crypto_host/main.py
│   └── crypto_host/config.json
├── monitor/
│   ├── main.py                # Flask monitor server (port 8090)
│   └── static/index.html      # single-page monitor UI
├── shared/
│   ├── stats.py               # Stats class — sent/recv counters + last_recv_datetime
│   ├── command_server.py      # HTTP command server (stats, stop, log_level, logs)
│   ├── framing.py             # ISO 8583 length-field framing
│   ├── ims_connect.py         # IMS-connect protocol (EBCDIC, resume TPIPE, etc.)
│   └── iso_utils.py           # ISO 8583 helpers (build_0800, build_0810, f47 encode/decode)
├── run/
│   ├── monitor.sh             # Start the monitor (bash run/monitor.sh)
│   └── kill_monitor.sh
├── test_spec.json             # ISO 8583 field spec
├── pans_defined.json          # PAN whitelist with crypto_result flags
├── router_skill.md            # this file
└── test_csv_files/            # Sample CSV files for test runs
```

## Router module responsibilities

| Module            | Class / key items              | C++ equivalent                            |
|-------------------|--------------------------------|-------------------------------------------|
| `config.py`       | `RouterConfig` dataclass       | Plain struct + `from_file()` factory      |
| `crypto_client.py`| `CryptoClient.validate()`      | libcurl/cpp-httplib wrapper class         |
| `downstream.py`   | `DownstreamConnection`         | RAII class, two fds + `std::mutex`        |
| `dispatcher.py`   | `Dispatcher`, `PendingEntry`, `RoutedMessage` | Thread pool + `std::unordered_map` + `std::queue` |
| `upstream.py`     | `UpstreamServer`, `UpstreamClient` | Abstract factory / acceptor+connector |
| `session.py`      | `RouterSession`                | RAII session, `std::atomic<bool>` reconnect flag |
| `main.py`         | `run()` loop                   | `main()` — just the retry loop            |

## Starting and stopping

```bash
# Start monitor (starts first, then use UI to launch actors)
bash run/monitor.sh

# Or start all via API
curl -X POST http://localhost:8090/api/start_all

# Stop all
curl -X POST http://localhost:8090/api/stop_all

# Kill stale processes if ports are stuck
ps aux | grep python3 | grep main.py | awk '{print $2}' | xargs kill -9
```

## IMS-connect framing (downstream)

downstream_host listens on a **single port** (5001). The first frame on a new connection determines its role:
- `IRM_F0 = 0x80` (resume TPIPE) → response-back socket (`from_downstream`)
- `IRM_F0 = 0x00` (non-resume) → request-in socket (`to_downstream`)

Routers are paired by `IRM_CLIENTID` (EBCDIC, 8 bytes). `router_1` uses `CLIENT01`, `router_2` uses `CLIENT02`.

## Upstream framing

ISO 8583 with ASCII length prefix (4 bytes, e.g. `0042` for a 42-byte message). No header.

```json
"framing": { "header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4 }
```

## Command server API (all actors)

Each actor exposes HTTP on its `command_port`:

| Endpoint         | Method    | Description                        |
|------------------|-----------|------------------------------------|
| `/stats`         | GET       | Counters + last_recv_datetime      |
| `/stop`          | POST      | Graceful stop                      |
| `/log_level`     | GET/POST  | Get or set log level               |
| `/logs`          | GET       | Last 2000 log lines (JSON or text) |
| `/upload`        | POST      | Upload CSV (upstream only)         |
| `/start`         | GET       | Start test run (upstream only)     |
| `/results`       | GET       | Test results (upstream only)       |

## Resilience

| Actor              | Reconnects?         | Yellow after    | Notes                              |
|--------------------|---------------------|-----------------|------------------------------------|
| `router`           | ✅ to downstream    | 40s no recv     | `reestablish_seconds: 10`          |
| `upstream_host`    | ✅ to router        | 40s no recv     | `reestablish_seconds: 10` (client) |
| `downstream_host`  | passive (accepts)   | 40s no recv     | —                                  |
| `crypto_host`      | passive (REST)      | 60s no recv     | only gets traffic on 0100 flow     |

### Status colours in monitor

- 🟢 **green** — running, received traffic within `yellow_threshold_seconds`
- 🟡 **yellow** — running, but silent (idle or connection lost)
- 🔴 **red** — not responding (process down)

When you stop an actor:
1. That actor → red immediately
2. Connected peers → yellow after `yellow_threshold_seconds` (silence detected)
3. Peers reconnect automatically once the actor restarts

## Running a test

1. Open monitor at `http://localhost:8090`
2. Click **Start All** and wait for green dots
3. In the Test Runner panel, select an upstream (upstream_1 or upstream_2)
4. Pick a CSV from the dropdown (or browse/upload one)
5. Click **Upload**, then **Start**
6. Results appear in the table (sorted by PAN); auto-refresh every 1s

### CSV format

Semicolon-separated, UTF-8 with BOM. Required column: `2` (PAN). Optional ISO 8583 field columns by number.

```
2;4;3
4111111111111111;000000010000;000000
```

## Known decisions

- **router_1** is in *server* mode (upstream connects to it on port 5000)
- **router_2** is in *client* mode (it connects out to upstream_2 on port 5010)
- `Framing.to_dict()` adapts the dataclass for `shared/framing.py` which still expects a dict
- `Stats.last_recv_datetime` stores wall-clock `HH:MM:SS` of last received message
- Monitor poll bug fixed: `status` variable was shadowed in `for...of` loop — renamed to `statuses`/`st`
- Router refactored from single 454-line `main.py` into 7 typed modules (see `md/refactor_plan.md`)
- Thread-per-connection + blocking I/O model is intentional — maps 1:1 to C++ `std::thread`
- 0120 (advice) and 0420 (reversal) bypass crypto — decision already taken; simulator always returns F39=00
- Dispatcher routes 0100/0120/0420 identically via STAN rewrite + pending map; crypto only runs for 0100
- Dispatcher accepts 0110/0130/0430 responses; crypto validate_0110 only runs on 0110
