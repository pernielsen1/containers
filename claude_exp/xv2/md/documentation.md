# ISO 8583 Router — Operations Documentation

## System overview

Two independent partners each run a router that accepts ISO 8583 messages from an upstream simulator and forwards them to a shared downstream host. A shared crypto host validates field 47 on authorization flows. The monitor UI at `:8090` provides start/stop and live status for all actors.

```
Partner A                             Shared
─────────────────────────────────     ──────────────────────────
upstream_1 :8083  →  router_1 :8080 ─→ downstream_host :8081
                                     → crypto_host     :8082

Partner B
─────────────────────────────────
upstream_2 :8086  ←  router_2 :8085 ─→ downstream_host :8081
                                     → crypto_host     :8082
```

> Partner A: upstream connects **to** the router (router is server on `:5000`).  
> Partner B: router connects **to** the upstream (upstream is server on `:5010`).

---

## Port reference

| Actor            | Data port | Command port | Config                                  |
|------------------|----------:|-------------:|-----------------------------------------|
| `upstream_1`     | → 5000    | **8083**     | `simulators/upstream_1/config.json`     |
| `router_1`       | 5000 ←    | **8080**     | `router/router_1/config.json`           |
| `upstream_2`     | 5010 ←    | **8086**     | `simulators/upstream_2/config.json`     |
| `router_2`       | → 5010    | **8085**     | `router/router_2/config.json`           |
| `downstream_host`| 5001      | **8081**     | `simulators/downstream_host/config.json`|
| `crypto_host`    | 5002      | **8082**     | `simulators/crypto_host/config.json`    |
| `monitor`        | —         | **8090**     | —                                       |

---

## Message flows

All flows pass through the router. Crypto is called only on `0100` authorization.

```
0100 Authorization
  upstream ──0100──→ router ──0100──→ downstream_host ──0110──→ router ──0110──→ upstream
                         ↕ crypto_host (validate_0100 / validate_0110)

0120 Advice  (decision already taken; always approved)
  upstream ──0120──→ router ──0120──→ downstream_host ──0130──→ router ──0130──→ upstream

0420 Reversal  (revert a prior transaction; always accepted)
  upstream ──0420──→ router ──0420──→ downstream_host ──0430──→ router ──0430──→ upstream

0800/0810 Keepalive  (every 30 s)
  upstream ──0800──→ router ──0800──→ downstream_host ──0810──→ router ──0810──→ upstream
```

---

## Starting actors

### Via monitor UI

```
http://localhost:8090  →  Start All
```

### Via command line (individual actors)

```bash
# Shared — start first
bash run/crypto_host.sh
bash run/downstream_host.sh

# Partner A
bash run/router_1.sh
bash run/upstream_1.sh

# Partner B
bash run/router_2.sh
bash run/upstream_2.sh

# Monitor
bash run/monitor.sh
```

Recommended start order: `crypto_host` → `downstream_host` → `router` → `upstream`.

---

## Stopping actors

### Graceful stop (HTTP)

```bash
curl -s -X POST http://localhost:8080/stop   # router_1
curl -s -X POST http://localhost:8083/stop   # upstream_1
curl -s -X POST http://localhost:8085/stop   # router_2
curl -s -X POST http://localhost:8086/stop   # upstream_2
curl -s -X POST http://localhost:8081/stop   # downstream_host
curl -s -X POST http://localhost:8082/stop   # crypto_host
```

### Force kill (if unresponsive)

```bash
ps aux | grep python3 | grep main.py | awk '{print $2}' | xargs kill -9
```

---

## Command server API

Every actor exposes the same HTTP interface on its command port.

| Endpoint      | Method   | Description                          |
|---------------|----------|--------------------------------------|
| `/stats`      | GET      | Sent/recv counters, last recv time   |
| `/stop`       | POST     | Graceful shutdown                    |
| `/log_level`  | GET/POST | Get or set log level (`DEBUG`/`INFO`)|
| `/logs`       | GET      | Last 2000 log lines                  |
| `/upload`     | POST     | Upload test CSV (upstream only)      |
| `/start`      | GET      | Start test run (upstream only)       |
| `/results`    | GET      | Test results (upstream only)         |

Example:

```bash
curl http://localhost:8080/stats        # router_1 stats
curl -X POST http://localhost:8080/log_level -d '{"level":"DEBUG"}'
```

---

## Status indicators

| Colour | Meaning                                                    |
|--------|------------------------------------------------------------|
| Green  | Running and received traffic within threshold              |
| Yellow | Running but silent — idle or peer disconnected             |
| Red    | Not responding — process is down                           |

Yellow thresholds: `40 s` for all actors except `crypto_host` (`60 s`).

When a peer stops, connected actors turn yellow after their threshold, then reconnect automatically once the peer restarts.

---

## Running a test

1. Ensure all actors are green in the monitor.
2. Prepare a semicolon-separated CSV with UTF-8 BOM. Required column: `2` (PAN).
3. Upload and start via UI, or via curl:

```bash
curl -X POST http://localhost:8083/upload -F "file=@test_csv_files/test.csv"
curl -s http://localhost:8083/start
curl -s http://localhost:8083/results
```

---

## Key configuration parameters

| Parameter                | Where                    | Default | Effect                              |
|--------------------------|--------------------------|---------|-------------------------------------|
| `worker_threads`         | router config            | 8       | Parallel downstream requests        |
| `reestablish_seconds`    | router / upstream config | 10      | Reconnect delay after disconnect    |
| `yellow_threshold_seconds`| all configs             | 40 / 60 | Silence before yellow status        |
| `ping_0800_seconds`      | upstream config          | 30      | Keepalive interval                  |
| `log_level`              | all configs              | DEBUG   | Change via `/log_level` at runtime  |
