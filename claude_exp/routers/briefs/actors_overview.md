
Four actors, one instance each, all defined under `config/`. All run inside the `router_java`
container; the monitor dashboard (not an actor itself) runs on the host and drives them over HTTP.
Full behavioral spec for each is in `build_router.md` — this file is just the current
wiring: who talks to whom, on which ports, from which config file.

```
                          ┌─────────────────┐
  upstream_1 ───(5000)───►│    router_1     │───(5001, IMS dual-socket)───► downstream_host
  (card network sim)      │ partner_a       │
                          └────────┬────────┘
                                   │ (5002, HTTP)
                                   ▼
                             crypto_host
```

## Actors

| Actor | Config file | Type | Role |
|---|---|---|---|
| `router_1` | `config/router_1.json` | router | Routes 0100/0110 between `upstream_1` and `downstream_host`, calling `crypto_host` for EMV validation on the way. Owns STAN rewriting and the pending-response map. |
| `crypto_host` | `config/crypto_host.json` | crypto | Stateless HTTP service: stub validation only — checks whether the PAN is present in `pans_defined.json` and stamps `response_code` (`00`/`14`) accordingly. No PIN/ARQC/CVV2/AAV math, no TCP actor loop. Real EMV cryptographic validation now lives in the shared `routers/crypto_host/` container (see `build_router.md`); a `config/router_1_perf.json` variant of `router_1` points at that shared container for performance runs (`stress_run.sh`) instead of this stub. |
| `downstream_host` | `config/downstream_host.json` | downstream | Simulates the IMS Connect authorization host `router_1` talks to. Approves/declines 0100s based on PAN presence and the crypto response code. |
| `upstream_1` | `config/upstream_1.json` | upstream | Simulates a card-network client: sends 0100s from an uploaded CSV, collects 0110 responses, sends 0800 keepalives. |

## Ports

| Actor | Wire port | Command port (HTTP: `/stats`, `/stop`, `/log_level`, `/logs`, …) |
|---|---|---|
| `router_1` | 5000 (upstream listen, server mode) | 8080 |
| `crypto_host` | 5002 (HTTP validate routes) | 8082 |
| `downstream_host` | 5001 (IMS Connect) | 8081 |
| `upstream_1` | — (connects out to `router_1:5000`) | 8083 |
| monitor (not an actor) | — | 8090 |

## Per-actor config

**`router_1.json`** — `partner_id: partner_a`, `log_level: DEBUG`, upstream framing is
ASCII/4-byte-length on port 5000 in server mode (router listens, upstream connects in),
downstream at `localhost:5001` with IMS identifiers `irm_id=IRM_ID01` / `client_id=CLIENT01`,
crypto at `localhost:5002`, `iso_spec: test_spec.xml`, 8 worker threads,
`yellow_threshold_seconds: 40`. All resilience fields (`queue_maxsize`,
`pending_ttl_seconds`, `crypto_breaker_threshold`, …) are left at their defaults.

**`crypto_host.json`** — port 5002, reads `pans_defined.json` and `test_spec.xml` from `config/`,
`yellow_threshold_seconds: 60` (higher than the others since it's request/response, not
streaming — a longer gap between calls is normal). `plugin_id`/`bearer_token` configure the
Fortanix-DSM-shaped route (`POST /sys/v1/plugins/{plugin_id}`, bearer auth) and must match the
same two values under `router_1.json`'s `crypto` block — see `build_router.md` for the full
interface. `router_1_perf.json` is a separate `router_1` variant, used only by `stress_run.sh`,
whose `crypto` block instead points at the shared `routers/crypto_host/` container's own
`plugin_id`/`bearer_token`.

**`downstream_host.json`** — port 5001, same `pans_defined.json`/`test_spec.xml`,
`yellow_threshold_seconds: 40`.

**`upstream_1.json`** — connects to `router_1` at `localhost:5000`, same ASCII/4-byte framing,
`input_dir: upstream_1_input` (gitignored; holds `test_cases.csv` at runtime, populated via
`/upload` or the dashboard), `ping_0800_seconds: 30`, `yellow_threshold_seconds: 40`.

## Scope notes

- Single instance of every actor type — no multi-router-per-partner or multi-upstream scenario
  configured (the underlying spec supports it; this configuration just doesn't use it yet).
- `is_active: true` on all four, so the monitor's "Start All" launches everything.
- Card data for `crypto_host`/`downstream_host` comes from `config/pans_defined.json` (4 PANs,
  each with its own `pin`/`pan_seq`/`imk_ac`/`cvk`/`pek`/`aav_key`) — shared by both actors since
  both need to recognize the same set of PANs.
- Sample traffic: `config/upstream_1_input/test_cases.csv` (gitignored) and
  `test_csv_files/test.csv` — 3 rows exercising a known-good PAN, a second known-good PAN, and an
  unrecognized PAN expected to decline with `39=01`.
