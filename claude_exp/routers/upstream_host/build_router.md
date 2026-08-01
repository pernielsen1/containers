# upstream_host — shared stress-test load generator

## Purpose

The ISO 8583 upstream card-network client used to functionally test and stress-test all three
router implementations in this project (`../router_py`, `../router_java`, `../router_cpp`). Promoted out of
`router_py/simulators/upstream_host/` (the original, and only, implementation — router_java's and router_cpp's
copies were line-by-line ports of it) into this standalone component so it doesn't have to be
independently reimplemented and maintained three times.

Unlike `crypto_host`, this is **not** a real performance bottleneck under comparison, and it isn't
containerized: it's test infrastructure — uploads a CSV of test transactions, sends `0100`
messages at a configured rate for a configured duration, tracks round-trip latency — with no
language-comparison value of its own. Running it as a plain host-side Python process, alongside the
existing per-implementation `monitor` tooling (also host-side), avoids a docker build/rebuild cycle
on the piece that's actively iterated on during perf-harness work, and removes the three duplicate
reimplementations that existed only for parity. See `../divide_and_conquer.md` (part 2) for the
original design discussion.

`downstream_host` (a trivial echo) intentionally stays embedded per-language, unlike this — it's
not worth the same consolidation.

## Wire contract

Same as before the consolidation — nothing changed on the wire, only where the code lives:

- TCP client to the router's upstream-listen port, framed per `config.json`'s `framing` block
  (`header_hex`, `length_field_type`, `length_field_bytes` — no header, ASCII 4-byte length prefix
  by default, identical across all three router implementations).
- Encodes/decodes ISO 8583 messages per `test_spec.json` (the `pyiso8583`-compatible JSON spec
  format — the proven, wire-compatible spec all three routers already tested against).
- Sends an `0800` keepalive immediately on connect, then every `ping_0800_seconds`.
- STAN: incrementing counter mod 1,000,000, zero-padded to 6 digits.

**Known cross-language gotchas** (found migrating router_java/router_cpp onto this shared component —
each router had only ever been tested against its own same-language upstream_host before, so an
internally-consistent-but-different convention on either side never surfaced until now):
- j8583 (router_java) defaults to a text/ASCII-hex bitmap; this spec's `p`/`1` fields
  (`"data_enc": "b"`) are raw binary bytes. router_java's `IsoUtils.loadFactory()` now calls
  `factory.setUseBinaryBitmap(true)` to match.
- router_cpp's hand-rolled codec used to encode the MTI as 2 binary bytes; this spec's `t` field is 4
  ASCII characters ("0100"). Fixed in `iso_codec.cpp`.
See `../divide_and_conquer.md` for the "test_spec should be the single source of truth for
encoding conventions, not per-language hardcoded assumptions" follow-up this prompted.

HTTP command API (`CommandServer`, same shared module every actor in this project uses):

- `POST /upload` — multipart CSV upload.
- `GET /start?rate=&duration=` — cycles the uploaded CSV's rows at `1/rate` intervals for
  `duration` seconds (omit both for a legacy single pass through the CSV).
- `GET /results` — array of completed request/response pairs.
- `GET /stress_stats` — `sent`, `received`, `errors`, `elapsed_s`, `achieved_tps`, `p50_ms`,
  `p95_ms`, `p99_ms`, `max_ms`.
- `GET /slow_responses?n=` — the `n` slowest completed round trips, `sent_offset_s`/`latency_ms`.
- `GET /latency_buckets?bucket_s=` — round trips grouped into fixed time windows since run start,
  `count`/`p50_ms`/`max_ms` per bucket (tells a smooth queueing-backlog ramp apart from scattered
  spikes).
- Plus the built-ins every `CommandServer` exposes: `/stats`, `/stop`, `/log_level`, `/logs`.

Round-trip and elapsed-time measurement uses `time.monotonic()`, not wall-clock `time.time()` — a
mid-run NTP/`hv_utils` clock resync on the WSL2 dev host this runs on previously corrupted latency
stats with bogus multi-minute spikes; monotonic time is immune to that.

## Repository layout

```
upstream_host/
├── main.py             # the whole implementation (UpstreamHostSim + HTTP routes)
├── config.json          # single shared config — see below
├── test_spec.json        # ISO 8583 field spec (pyiso8583 JSON format)
├── requirements.txt      # pyiso8583, flask, requests
├── upstream_shared/      # copied from router_py/shared/ (forked, not import-path-shared — router_py's router
│                         # still needs its own copy for its own use, so this is an independent
│                         # fork rather than a cross-reference). Named upstream_shared, not shared,
│                         # because router_py's pytest suite imports UpstreamHostSim in-process
│                         # alongside router_py's own "shared" package - a same-named package would
│                         # silently collide in sys.modules within that one process.
│   ├── command_server.py
│   ├── framing.py
│   ├── iso_utils.py
│   └── stats.py
└── input/                # CSV upload landing dir, created at runtime, gitignored
```

## Configuration

`config.json`:

```json
{
  "name": "upstream_1",
  "type": "upstream",
  "is_active": true,
  "command_port": 8083,
  "router": { "host": "localhost", "port": 5000 },
  "framing": { "header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4 },
  "iso_spec": "test_spec.json",
  "input_dir": "input",
  "ping_0800_seconds": 30,
  "yellow_threshold_seconds": 40
}
```

One file, not one per implementation: `router.port` (5000) and the framing block are identical
across router_py/router_java/router_cpp, and the three are mutually exclusive at runtime (same host ports, only
one implementation's stack up at a time), so there's nothing implementation-specific left to
configure per-copy. Each implementation's own router config keeps its own `upstream` block (port,
framing) for its own listen-socket setup — that doesn't go away, it's just no longer *also*
upstream_host's config source.

## Build & run

No build step — it's a plain Python script.

```bash
python3 main.py --config config.json
# or, with no --config: defaults to config.json next to main.py
```

Each implementation's `stress_run.sh`/`run_test.sh` launches this as a bare host subprocess
(`python3 <path-to-here>/main.py --config <path-to-here>/config.json &`), the same way router_py always
launched its own copy — not via `docker exec` or a compose `command:` block. Each implementation's
`monitor` (`<impl>/monitor/main.py`) launches/tracks it the same way, with an explicit synthesized
actor entry pointing at this directory's `config.json` (since each monitor's actor auto-discovery
walks its own project tree, which no longer contains upstream_host's config).

### Manual smoke test

```bash
python3 main.py --config config.json &
curl -s localhost:8083/stats
kill %1
```
