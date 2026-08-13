# downstream_host — shared IMS Connect authorization-host stub

## Purpose

Trivial echo/approve-decline authorization host used to functionally test and stress-test all
three router implementations (`../router_py`, `../router_java`, `../router_cpp`). Promoted out of
`router_py/simulators/downstream_host/` (the original, and only, implementation — router_java's
and router_cpp's copies were line-by-line ports of it) into this standalone component, the same
treatment `../upstream_host` got in Round 2 (see `../divide_and_conquer.md`, part 2) — it's pure
test infrastructure with zero language-comparison value, and three reimplementations existed only
for parity, not because the language mattered.

Unlike `upstream_host`, this consolidation only removes the *code* duplication. Configuration
stays per-language: each implementation's `pans_defined.json` (test PAN/key data) genuinely
differs — router_py's own set, and a different set shared by router_java/router_cpp, and a third,
different again, real set used by the shared `../crypto_host` container. So there is no single
`config.json` here the way `upstream_host` has one; each implementation keeps its own config
file(s) (`config.json`/`config_perf.json`, or router_java/router_cpp's `config/downstream_host*.json`)
pointing at this shared `main.py`.

## Wire contract

Same as before the consolidation — nothing changed on the wire, only where the code lives:

- IMS Connect framing (`ims_connect.py` — TPIPE resume/from-conn + to-conn split, EBCDIC "PING"
  pipe-cleaner) on a plain TCP listen socket, optionally TLS-wrapped per `ssl_active`/
  `certfile`/`keyfile`/`cafile` in config.
- Decodes/encodes ISO 8583 messages per `iso_spec` (pyiso8583 JSON spec format).
- `0800`/`0120`/`0420` are trivially echoed back with an approved response code.
- `0100` is decided by PAN presence in `pans_defined` plus field 47's embedded response code;
  approved responses get a synthetic auth code, and field 47 is always echoed back with
  `message_type`/`response_code` updated — required for `crypto_host`'s ARPC step on `0110`,
  which only runs if the original cryptogram/ATC round-trips through field 47.

HTTP command API (`CommandServer`, same shared module every actor in this project uses): the
built-ins every actor exposes — `/stats`, `/stop`, `/log_level`, `/logs`.

## Repository layout

```
downstream_host/
├── main.py               # the whole implementation (DownstreamHostSim + entry point)
├── requirements.txt        # pyiso8583, flask
└── downstream_shared/       # forked copy of router_py/shared's small utility modules (not
                             # import-path-shared — router_py's own pytest suite imports
                             # DownstreamHostSim in-process alongside router_py's own "shared"
                             # package, so this is an independent fork, same reasoning and
                             # pattern as upstream_host/upstream_shared/)
    ├── command_server.py
    ├── framing.py           # only needed because ims_connect.py depends on it (_recv_exact)
    ├── ims_connect.py
    ├── iso_utils.py
    ├── json_log.py
    ├── log_buffer.py
    ├── ssl_utils.py
    └── stats.py
```

## Configuration

No single shared config file (see "Purpose" above for why) — every launcher passes its own
`--config <path>`. Shape (router_py's `simulators/downstream_host/config.json` shown, others are
the same fields with different values/relative paths):

```json
{
  "name": "downstream_host",
  "type": "downstream",
  "is_active": true,
  "port": 5001,
  "command_port": 8081,
  "ssl_active": true,
  "certfile": "...",
  "keyfile": "...",
  "cafile": "...",
  "iso_spec": "...",
  "pans_defined": "...",
  "yellow_threshold_seconds": 40
}
```

`iso_spec`/`pans_defined`/`certfile`/`keyfile`/`cafile` are resolved relative to the config file's
own directory (see `load_config()`), so each implementation's config can point at its own copies
without this component needing to know where they live.

## Build & run

No build step — it's a plain Python script.

```bash
python3 main.py --config <path-to-a-downstream_host-config.json>
```

Each implementation's `run_test.sh`/`stress_run.sh`/`monitor/main.py` launches this as a bare host
subprocess (`python3 <path-to-here>/main.py --config <path> &`), the same way `upstream_host` is
launched — not via `docker exec` or a compose `command:` block.

### Manual smoke test

```bash
python3 main.py --config ../router_py/simulators/downstream_host/config.json &
curl -s localhost:8081/stats
kill %1
```
