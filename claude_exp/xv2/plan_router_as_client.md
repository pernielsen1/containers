# Plan: Router Upstream Client Mode

## What changes

The `upstream` config section gets a `"mode"` field: `"server"` (default, current behaviour —
router listens) or `"client"` (new — router connects out to upstream_host with retry).

Symmetrically, `upstream_host` gets a top-level `"mode"` field: `"client"` (default, current —
connects to router on `/start`) or `"server"` (new — listens on startup, accepts the router's
connection, then `/start` triggers the send loop).

`router_2` → client mode. `upstream_2` → server mode.

---

## File Changes

### 1. `router/main.py` — add client upstream mode

Add `_client_upstream_loop(up_cfg, up_framing, spec, work_queue, stats, stop_event)`:
- Loop: try `socket.connect((host, port))` → on success hand off to existing `_handle_upstream`
  (unchanged); on `OSError` log and `stop_event.wait(retry_seconds)` before retrying.
- When `_handle_upstream` returns (upstream disconnected), loop again to reconnect.

In `run()`: branch on `cfg["upstream"].get("mode", "server")`:
- `"server"`: current accept loop (unchanged)
- `"client"`: start `_client_upstream_loop` in a thread instead; no `srv_sock`

### 2. `simulators/upstream_host/main.py` — add server mode

Check `cfg.get("mode", "client")`:

**Client mode** (unchanged): `/start` connects → receive loop → send loop.

**Server mode**:
- On `run()` startup: bind and listen on `cfg["port"]`; start an accept thread that stores the
  first connection in `state["conn"]` and starts the receive loop.
- `/start`: if `state["conn"]` is set, start the send loop immediately; if not yet connected,
  return `503` with `"router not connected yet"`.

### 3. `router/router_2/config.json`

Add `"mode": "client"`, `"host": "localhost"`, `"retry_seconds": 5` inside `upstream`.
Keep `port` (5010 — the port upstream_2 will listen on).

```json
"upstream": {
  "mode": "client",
  "host": "localhost",
  "port": 5010,
  "retry_seconds": 5,
  "framing": { "header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4 }
}
```

### 4. `simulators/upstream_2/config.json`

Replace `"router": {…}` with top-level `"mode": "server"` and `"port": 5010`. Remove `router` key.

```json
{
  "name": "upstream_2",
  "type": "upstream",
  "mode": "server",
  "log_level": "DEBUG",
  "port": 5010,
  "command_port": 8086,
  "framing": { "header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4 },
  "iso_spec": "../../test_spec.json",
  "input_dir": "input"
}
```

---

## No Changes Needed

- `router_1/config.json` and `upstream_1/config.json` — stay as-is (default `"server"`/`"client"`)
- `downstream_host`, `crypto_host`, `shared/`, UI — unaffected
- Tests — integration test uses server mode; stays unchanged
