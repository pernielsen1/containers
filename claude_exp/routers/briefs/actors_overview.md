
Four actors, one instance each. This wiring is implemented three
times over — once per router language (`router_py`, `router_java`, `router_cpp`) — with the same
names, ports, and config shape in each; only the router itself differs between implementations
(that's the point of the project, see `../divide_and_conquer_v2.md`). The three are mutually
exclusive on one machine (same host ports), never run side by side. **Python (`router_py`) is
currently the primary implementation**; java/cpp remain as comparison contenders.

The monitor dashboard (not an actor itself) is the shared `monitor_host` container
(`--network host`, see `../monitor_host/build_router.md`), started with `--target
router_py|router_java|router_cpp` to drive one implementation's set of actors over HTTP at a time.
For the full container/process map (what's containerized vs. a host subprocess, and what changes
in a remote `serverhp.home` deployment), see `solution_overview.md`.

Full behavioral spec for each is in that implementation's own `build_router.md` — this file is
just the current wiring: who talks to whom, on which ports, from which config file. Everything
below is language-agnostic except where a table calls out a per-implementation difference.

All three of `router_1`'s legs (upstream, downstream, crypto) run mTLS by default
(`ssl_active: true` in each block, certs under `certs/`) — see each implementation's
`build_router.md`'s SSL section for the toggle-off-for-debugging escape hatch.

```
                          ┌─────────────────┐
  upstream_1 ───(5000)───►│    router_1     │───(5001, IMS dual-socket)───► downstream_host
  (card network sim)      │ (py / java / cpp)│
                          └────────┬────────┘
                                   │ (5002, HTTP)
                                   ▼
                             crypto_host
```

## Actors

| Actor | Type | Role |
|---|---|---|
| `router_1` | router | Routes 0100/0110 between `upstream_1` and `downstream_host`, calling `crypto_host` for EMV validation on the way. Owns STAN rewriting and the pending-response map. |
| `crypto_host` | crypto | Stateless HTTP service: stub validation only — checks whether the PAN is present in `pans_defined.json` and stamps `response_code` (`00`/`14`) accordingly. No PIN/ARQC/CVV2/AAV math, no TCP actor loop. Real EMV cryptographic validation now lives in the shared `routers/crypto_host/` container (see its own `build_router.md`); a `router_1_perf` config variant points at that shared container for performance runs (`stress_run.sh`) instead of this stub. |
| `downstream_host` | downstream | Simulates the IMS Connect authorization host `router_1` talks to. Approves/declines 0100s based on PAN presence and the crypto response code. Shared Python implementation (`routers/downstream_host/main.py`) across all three router languages — only its config/PAN data is per-implementation. |
| `upstream_1` | upstream | Simulates a card-network client: sends 0100s from an uploaded CSV, collects 0110 responses, sends 0800 keepalives. Shared Python implementation (`routers/upstream_host/main.py`) across all three router languages, driven by one shared `routers/upstream_host/config.json`. |

### Config file locations by implementation

Same field shapes and default port numbers everywhere (see the Ports/Per-actor sections below),
but the config files themselves live in different places per language — this table is the map for
"where do I edit this actor's settings" in whichever implementation you're looking at.

| Actor | `router_py` | `router_java` | `router_cpp` |
|---|---|---|---|
| `router_1` | `router/router_1/config.json` (+ `config_perf.json`) | `config/router_1.json` (+ `router_1_perf.json`) | `config/router_1.json` (+ `router_1_perf.json`) — one file also holds `crypto`/`downstream`/`upstream` as nested blocks, see below |
| `crypto_host` (stub) | `simulators/crypto_host/config.json` | `config/crypto_host.json` | nested `crypto` block inside `config/router_1.json` — no standalone file |
| `downstream_host` | `simulators/downstream_host/config.json` (+ `config_perf.json`) | `config/downstream_host.json` (+ `downstream_host_perf.json`) | `config/downstream_host.json` (+ `downstream_host_perf.json`) |
| `upstream_1` | `../upstream_host/config.json` (shared, one file for all three) | same shared file | same shared file |

`router_cpp`'s single `config/router_1.json` nests `upstream`/`downstream`/`crypto` blocks with
their own `port`/`command_port` pairs inside it, rather than four separate files — see
`monitor_host/backends/router_cpp.py`'s module docstring for how the monitor synthesizes four
logical actor descriptors out of that one file.

## Ports

| Actor | Wire port | Command port (HTTP: `/stats`, `/stop`, `/log_level`, `/logs`, …) |
|---|---|---|
| `router_1` | 5000 (upstream listen, server mode) | 8080 — also `/pending` (live in-flight STANs) and `/trace` (on-demand per-hop capture), router-only routes from the debug-tracing tooling |
| `crypto_host` | 5002 (HTTP validate routes) | 8082 |
| `downstream_host` | 5001 (IMS Connect) | 8081 |
| `upstream_1` | — (connects out to `router_1:5000`) | 8083 |
| monitor (not an actor) | — | 8090 |

## Per-actor config

Field *names* and default port numbers below are the same across all three implementations;
`partner_id` and a handful of other string values genuinely differ per language config (e.g.
`router_java`'s `router_1.json` uses `partner_id: partner_a`, `router_py`'s uses `partner_X`) —
treat those as illustrative, not literal, and check the actual file (see the location table
above) for the current value in whichever implementation you're touching.

**`router_1`** — `log_level: DEBUG`, upstream framing is ASCII/4-byte-length on port 5000 in
server mode (router listens, upstream connects in), downstream at `localhost:5001` with IMS
identifiers (`irm_id`/`client_id`), crypto at `localhost:5002` by default (or the shared real
`crypto_host` container when using a `*_perf` config variant), `iso_spec: test_spec.xml`/`.json`,
8 worker threads, `yellow_threshold_seconds: 40`. All resilience fields (`queue_maxsize`,
`pending_ttl_seconds`, `crypto_breaker_threshold`, …) are left at their defaults.

**`crypto_host`** (stub) — port 5002, reads `pans_defined.json` and the ISO spec, `plugin_id`/
`bearer_token` configure the Fortanix-DSM-shaped route (`POST /sys/v1/plugins/{plugin_id}`,
bearer auth) and must match the same two values under `router_1`'s `crypto` block — see the
implementation's `build_router.md` for the full interface. `yellow_threshold_seconds: 60`
(higher than the others since it's request/response, not streaming — a longer gap between calls
is normal). A `router_1_perf` config variant, used only by `stress_run.sh`, points `router_1`'s
`crypto` block at the shared `routers/crypto_host/` container's own `plugin_id`/`bearer_token`
instead of this in-process stub.

**`downstream_host`** — port 5001, same `pans_defined.json`/ISO spec, `yellow_threshold_seconds:
40`.

**`upstream_1`** — connects to `router_1` at `localhost:5000`, same ASCII/4-byte framing,
`input_dir: input` (gitignored; holds `test_cases.csv` at runtime, populated via `/upload` or the
dashboard), `ping_0800_seconds: 30`, `yellow_threshold_seconds: 40`. One shared config
(`routers/upstream_host/config.json`) for all three implementations.

## Scope notes

- The four actors above are the default single-instance-per-type topology this file describes,
  present identically in all three implementations. A second, disabled-by-default router+upstream
  pair now also exists in each implementation too (`router_2`/`upstream_2`, `is_active: false`) —
  a reversed-topology partner speaking EBCDIC on its upstream leg only, sharing the same
  `downstream_host`/`crypto_host`. File locations follow the same per-implementation pattern as
  the config table above (e.g. `router_java`'s `config/router_2.json` + `config/upstream_2.json`
  vs. `router_py`'s `router/router_2/config.json` + `simulators/upstream_2/config.json`). Not
  covered by the diagram/tables above, which stay scoped to the default `router_1` topology; see
  each implementation's `build_router.md` for the `router_2`/EBCDIC details.
- `is_active: true` on all four actors described here, so the monitor's "Start All" launches
  everything in this file's scope (not `router_2`/`upstream_2`, which stay off by default).
- Card data for `crypto_host`/`downstream_host` comes from each implementation's own
  `pans_defined.json` (4 PANs, each with its own `pin`/`pan_seq`/`imk_ac`/`cvk`/`pek`/`aav_key`) —
  shared by both actors within one implementation since both need to recognize the same set of
  PANs, but genuinely different data between `router_py`, `router_java`/`router_cpp` (which share
  a set), and the real `routers/crypto_host/` container's own set.
- Sample traffic: `routers/upstream_host/input/test_cases.csv` (gitignored, populated via
  `/upload` or the dashboard) and the master `routers/test_csv_files/test.csv` — 3 rows exercising
  a known-good PAN, a second known-good PAN, and an unrecognized PAN expected to decline with
  `39=01`.
- This file describes the wire-level actor contract only. For which of these actors run as
  containers vs. host processes (locally and on a remote `serverhp.home` deployment), and for a
  reference of every orchestration script in the repo, see `solution_overview.md`.
