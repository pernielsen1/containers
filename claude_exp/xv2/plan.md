# Multi-Instance Architecture Plan

## What changes and why

**The core protocol change** (monitor.md §"making it multi"): downstream_host currently listens on
two separate ports (5001 = to-downstream, 5003 = from-downstream). The new design collapses these
into **one port**. The first IMS frame received on a new connection determines its role:

- `IRM_F0 = 0x80` (resume TPIPE) → response-back ("from_downstream") socket
- `IRM_F0 = 0x00` (non-resume) → request-in ("to_downstream") socket

Routers are still paired by `IRM_CLIENTID`. Two routers simply need different `client_id` values.

---

## Port allocation

| Process          | Port(s)                          | Command port      |
|------------------|----------------------------------|-------------------|
| `crypto_host`    | 5002                             | 8082 (unchanged)  |
| `downstream_host`| **5001** (merged)                | 8081 (unchanged)  |
| `router_1`       | upstream=5000, downstream=5001   | 8080 (unchanged)  |
| `router_2`       | upstream=5010, downstream=5001   | 8085 (new)        |
| `upstream_1`     | — (connects to 5000)             | 8083 (unchanged)  |
| `upstream_2`     | — (connects to 5010)             | 8086 (new)        |
| `ui`             | 8090                             | —                 |

---

## Files changed

### 1. `simulators/downstream_host/main.py` — merge accept loop

Replace the two separate accept loops (one per port) with a single accept loop on one port.
A new `_handle_new_conn` dispatcher reads the first IMS frame and routes to either the existing
from-conn or to-conn logic. The to-conn handler must be adapted to process the first already-read
frame, then loop normally.

### 2. `simulators/downstream_host/config.json`

Remove `to_downstream_port` / `from_downstream_port`, replace with single `"port": 5001`.

### 3. `router/main.py` — single downstream port + `--config` arg

- `_connect_downstream_ims`: currently opens two sockets to two ports; change to open both to the
  same single port.
- Add `argparse` with `--config <path>` so the same `main.py` runs as router_1 or router_2.
- `load_config`: default `--config` to `router/router_1/config.json` (relative to `main.py`);
  remove `router/config.json`.
- Relative paths in config (`iso_spec`) resolve relative to the config file's directory.

### 4. `router/router_1/config.json` (new)

```json
{
  "name": "router_1",
  "log_level": "DEBUG",
  "command_port": 8080,
  "upstream": {
    "port": 5000,
    "framing": { "header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4 }
  },
  "downstream": {
    "host": "localhost",
    "port": 5001,
    "irm_id": "IRM_ID01",
    "client_id": "CLIENT01"
  },
  "crypto": { "host": "localhost", "port": 5002 },
  "iso_spec": "../../test_spec.json",
  "worker_threads": 8
}
```

### 5. `router/router_2/config.json` (new)

Same structure, `upstream.port=5010`, `client_id=CLIENT02`, `command_port=8085`.

### 6. `simulators/upstream_host/main.py` — `--config` arg

Add `--config <path>` via argparse; default to `simulators/upstream_1/config.json` (relative to
`main.py`); remove `simulators/upstream_host/config.json`. Resolve relative paths (iso_spec,
input_dir) from the config file's directory. The upload handler stores CSV relative to the config
directory's `input_dir`.

### 7. `simulators/upstream_1/config.json` (new, with `input/` subdir)

```json
{
  "name": "upstream_1",
  "log_level": "DEBUG",
  "command_port": 8083,
  "router": { "host": "localhost", "port": 5000 },
  "framing": { "header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4 },
  "iso_spec": "../../test_spec.json",
  "input_dir": "input"
}
```

### 8. `simulators/upstream_2/config.json` (new)

Same structure, `router.port=5010`, `command_port=8086`, `name="upstream_2"`.

### 9. `ui/main.py` — new actor discovery + two-section layout

- `discover_actors()`: walk for any `config.json` that has both a `"name"` field and a `"type"`
  field (`"router"` | `"upstream"` | `"downstream"` | `"crypto"`). Picks up all named instances
  without hardcoding paths.
- `STARTUP_ORDER`: crypto → downstream → router_1 → router_2 → upstream_1 → upstream_2.
- `/api/actors` response includes `type` so the frontend can split into sections.
- Upload/start/results routes: actor name is now a parameter, not hardcoded to `upstream_host`.

### 10. `ui/static/index.html` — two-section layout

- **Routers section**: cards for `type=router`, stats only, no runner.
- **Simulators section**: cards for `type=upstream` / `downstream` / `crypto`.
- **Test Runner panel** (inside Simulators section):
  1. **Select upstream** dropdown (upstream_1 / upstream_2) — must be chosen first.
  2. **Select/upload CSV** — picker and upload button, enabled only after upstream is selected.
  3. **Start** button — enabled after successful upload.
  4. **Results** table with auto-refresh — scoped to the selected upstream.

### 11. Run scripts

- Add `run/router_1.sh` and `run/router_2.sh` (passing `--config router/router_1/config.json`)
- Add `run/upstream_1.sh` and `run/upstream_2.sh`
- Keep or update old scripts as needed.

---

## Config `"type"` field to add to each config.json

| File                                       | `"type"`       |
|--------------------------------------------|----------------|
| `simulators/crypto_host/config.json`       | `"crypto"`     |
| `simulators/downstream_host/config.json`   | `"downstream"` |
| `router/router_1/config.json`              | `"router"`     |
| `router/router_2/config.json`              | `"router"`     |
| `simulators/upstream_1/config.json`        | `"upstream"`   |
| `simulators/upstream_2/config.json`        | `"upstream"`   |
