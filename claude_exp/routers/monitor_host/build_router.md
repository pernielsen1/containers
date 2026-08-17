# monitor_host — shared dashboard container

## Purpose

The dashboard for all three router implementations (`../router_py`, `../router_java`,
`../router_cpp`), consolidated out of three drifting per-language copies
(`<impl>/monitor/main.py` + `<impl>/monitor/static/index.html`, ~600 lines each). Started
2026-08-14, finished 2026-08-17. The three copies had already drifted in ways that cost real
friction — router_cpp's `is_running()` took an `actor` dict where router_py's/router_java's took
a `name` string, discovered during the 2026-08-16 resilience-suite port (see
`../to_do_java_cpp.md`) — and every dashboard bugfix (the log-level `<select>` re-render bug, the
CSV dropdown pitfall, the PID-1/`docker-init` substring-match kill hazard) had to be independently
found and fixed per copy, or silently wasn't.

Like `upstream_host`/`downstream_host`, this is test/ops infrastructure with no language-comparison
value of its own — collapsing it to one shared implementation removes the duplicate-maintenance
burden without touching what's actually being compared (the router/simulator perf and code under
`router_py`/`router_java`/`router_cpp`).

## Architecture

Unlike `upstream_host`/`downstream_host` (bare host subprocesses), this runs as **its own Docker
container** — `main.py`'s docstring specifies this explicitly. Rationale: the dashboard needs to
either `docker exec` into an already-running `router_java`/`router_cpp` container (to launch/kill
actors, tail logs) or spawn host-style subprocesses for `router_py`'s actors and the shared
`upstream_host`/`downstream_host` — and it needs the exact same `localhost:<port>` reachability a
bare host process would have had, so that browser-facing behavior doesn't change. Three things
make that work together:

- **`--network host`** — no port-mapping bookkeeping; every actor's command port is reachable at
  `localhost:<port>` exactly as if the dashboard itself were host-side.
- **`/var/run/docker.sock` bind-mounted in** — lets `backends/router_java.py` and
  `backends/router_cpp.py` run `docker exec`/`docker ps` against sibling containers from inside
  this one. The `Dockerfile` installs the `docker.io` package for the CLI client only; no Docker
  daemon runs inside the image.
- **The whole `routers/` repo bind-mounted at `/src`, not `COPY`'d into the image** — every
  `backends/<target>.py` resolves its own `ROUTERS_ROOT`/`PROJECT_ROOT` from `__file__` at import
  time, so a bind mount just needs the same relative layout the image was built with. This also
  means router source edits (a config change, a fixed backend module) don't require an image
  rebuild — only genuine dependency changes (`requirements.txt`) do.

This is why `main.py` and every `backends/*.py` module are unchanged in behavior from before the
consolidation — they're the same Flask app and lifecycle logic that used to run bare on the host,
just now running inside a container that reproduces the same reachability.

## Repository layout

```
monitor_host/
├── Dockerfile           # python:3.12-slim + docker.io (CLI only) + requirements.txt
├── requirements.txt      # flask, requests, pyiso8583
├── start.sh <target> [port]   # docker build + docker run -d --network host + docker.sock + repo bind mount
├── stop.sh <target> [port]    # POST /stop (best-effort) then docker rm -f
├── main.py               # shared Flask app + actor-lifecycle plumbing — see "main.py" below
├── backends/
│   ├── router_py.py       # CONTAINER_NAME = None; all 4 actor types are host subprocesses
│   ├── router_java.py     # CONTAINER_NAME = "router_java"; router/downstream/crypto via docker exec
│   └── router_cpp.py      # CONTAINER_NAME = "router_cpp"; router/crypto via docker exec
└── static/
    ├── router_py/index.html    # carried over unmodified from router_py/monitor/static/
    ├── router_java/index.html  # carried over unmodified from router_java/monitor/static/
    └── router_cpp/index.html   # carried over unmodified from router_cpp/monitor/static/
```

**The three `static/<target>/index.html` files are per-target, not shared**, and were copied over
byte-for-byte during the consolidation rather than merged into one. They had already diverged
before this consolidation — most notably, `router_cpp/monitor/static/index.html` had the
log-level-display fix (`patchCards()`, per-card DOM patching instead of whole-container
`innerHTML` rebuilds) that `router_py`'s and `router_java`'s copies never received. Do not assume
the three are identical; a UI fix made against one target's `index.html` does not apply to the
other two automatically.

## `main.py` — the backend contract

`main.py` parses `--port` (default 8090) and `--target` (`router_py`/`router_java`/`router_cpp`,
or the `MONITOR_TARGET` env var), then dynamically imports `backends.<target>` and drives every
route generically against whatever that module exposes. A backend module must provide:

```python
CONTAINER_NAME: str | None           # docker container to `docker exec` into, or None if every
                                      # actor type is a host subprocess
HOST_SUBPROCESS_TYPES: set[str]      # actor types launched as a plain Popen, not docker exec

def discover_actors() -> list[dict]: ...   # cached once per monitor process lifetime
def host_subprocess_cmd(actor) -> tuple[list[str], str]: ...   # (argv, cwd) for HOST_SUBPROCESS_TYPES
def launch_docker_actor(actor) -> None: ...           # docker exec -d into CONTAINER_NAME
def docker_actor_commands(actor) -> dict: ...          # {"kill": <script>, "tail": <command>}
```

Everything downstream of that contract — actor lifecycle, HTTP routes, status polling, the static
UI it serves — is identical across all three targets and was previously duplicated three times:

**Actor lifecycle** (`_start_all_worker`, one per active actor in the backend's declared startup
order): launch if not already running (host `Popen` for `HOST_SUBPROCESS_TYPES`, `docker exec -d`
otherwise), then `wait_for_ready(actor, timeout=10)` — polls `/stats` until HTTP 200, **and**, for
routers, until `connections.downstream == true`, for upstreams until `connections.router == true`.
Skipping the connection check means a `/start` called immediately after "Start All" can 503 with
"not connected to router" even though `/stats` itself already answers 200 — the HTTP server and the
actor's own TCP-level peer connection are two different milestones.

**Liveness** (`is_running(name)`): for `docker exec -d`-launched actors there is no OS process
handle to poll (the exec client detaches and exits the instant the command starts inside the
container), so liveness is always defined as "the actor's own `/stats` endpoint answers HTTP 200" —
arguably more honest regardless of transport, since a process that's alive but wedged wouldn't help
an operator either.

**Routes** (identical set across all three targets):

| Route | Purpose |
|---|---|
| `GET /` | serve `static/<target>/index.html` |
| `GET /api/actors` | ordered list: name/type/command_port/running/is_active/partner_id |
| `GET /api/actors_by_partner` / `GET /api/routers_by_partner` | dict `partner_id → [...]` |
| `GET /api/status` | parallel `/stats` health check per actor; green/yellow/red |
| `GET /api/starting` | `{"starting": bool}` — true while a background "start all" is in flight |
| `GET /api/csv_files` | CSVs under `test_csv_files/` plus each upstream's own `input_dir` |
| `GET /api/commands` | `{"shell": "docker exec -it <container> bash"}` (host-subprocess-only targets omit this) |
| `GET /api/actor/<name>/commands` | `{"kill": <script>, "tail": <command>}`, from `docker_actor_commands()` |
| `POST /api/actor/<name>/launch` | start if not already running |
| `POST /api/actor/<name>/stop` | proxy `/stop`, then poll liveness down to confirm |
| `GET /api/actor/<name>/stats` | proxy `/stats` |
| `GET /api/actor/<name>/start` \| `/results` | proxy (upstream only) |
| `GET\|POST /api/actor/<name>/log_level` | proxy log level |
| `GET /api/actor/<name>/logs` | proxy `/logs`; `?format=text` for plain text |
| `POST /api/actor/<name>/upload` \| `/upload_path` | proxy CSV upload |
| `POST /api/actor/<name>/dispatcher/purge` | router only |
| `POST /api/start_all` / `POST /api/stop_all` | in declared startup order / reverse |
| `POST /api/infra/*` | infra helpers (partner/router listing etc.) |
| `POST /stop` | stop the monitor process itself: best-effort `/stop` to every running actor first (background thread), then exit |

**Status logic** (per actor, `/api/status`): fetch `/stats`; non-200/unreachable → red; no
`yellow_threshold_seconds` key → green; `seconds_since_last_recv` is `null` or exceeds the
threshold → yellow; otherwise green.

**Quiet logs**: `logging.getLogger("werkzeug").setLevel(logging.ERROR)` — Flask's default
per-request access log would otherwise flood the console every 2 seconds from the UI's polling.

## Per-target backend summary

| | `router_py` | `router_java` | `router_cpp` |
|---|---|---|---|
| `CONTAINER_NAME` | `None` | `"router_java"` | `"router_cpp"` |
| `HOST_SUBPROCESS_TYPES` | `{router, crypto, upstream, downstream}` (all) | `{upstream, downstream}` | `{upstream, downstream}` |
| `docker exec` types | — | `router, downstream, crypto` | `router, crypto` |
| Actor discovery | walks the whole project tree for `config.json` files | walks flat `config/*.json` files | reads one shared `config/router_1.json`, synthesizes 4 logical actors (see below) |

`router_cpp`'s `discover_actors()` is the odd one out: all four binaries load the *same*
`config/router_1.json` (`command_port`/`command_auth_token` at the top level for the router, a
per-actor `command_port` nested under `upstream`/`downstream`/`crypto` for the other three), so
`backends/router_cpp.py` reads that one file once and synthesizes four actor descriptors from it,
rather than scanning a directory. It also conditionally loads `config/router_2.json` +
`config/upstream_2.json` (a second, `is_active: false` router+load-generator pair with genuinely
separate config files) and appends up to two more entries — see `_load_router_2_actors()` in
`backends/router_cpp.py`.

**`downstream_host` config path — a real regression found and fixed during this consolidation**:
`downstream_host` deliberately has no shared `config.json` of its own (see
`../downstream_host/build_router.md` — "no single shared config file, every implementation keeps
its own"). The pre-consolidation `router_cpp/monitor/main.py` correctly pointed at router_cpp's own
copy, `router_cpp/config/downstream_host.json`. The first cut of `backends/router_cpp.py` regressed
this to `downstream_host/config.json` (a path that doesn't exist), which surfaced immediately during
live verification as `FileNotFoundError` in the container log and `downstream_host` stuck at
"starting" forever. Fixed in `backends/router_cpp.py`'s `discover_actors()`:
`"config_path": str(PROJECT_ROOT / "config" / "downstream_host.json")`. `router_java` was not
affected — its `discover_actors()` walks `router_java/config/*.json` directly, which includes its
own `downstream_host.json` without any special-casing.

## Build & run

```bash
./start.sh <router_py|router_java|router_cpp> [port]   # default port 8090
# builds the monitor_host image (cheap after the first time — only rebuilds on requirements.txt/
# Dockerfile changes), then docker run -d --name monitor_<target> --network host --init
# -v /var/run/docker.sock:/var/run/docker.sock -v <repo_root>:/src -e MONITOR_TARGET=<target>
# monitor_host, polling /api/actors for up to 30s for readiness.

./stop.sh <router_py|router_java|router_cpp> [port]
# POST /stop (best-effort), then docker rm -f monitor_<target> — an exact container-name match,
# which is strictly safer than the old pidfile/pgrep-based kill each per-language monitor_stop.sh
# used to do.
```

Each language's own launcher now just delegates rather than running `monitor/main.py` directly —
see the "Monitor" section in each `build_router.md` for the exact delegation. Only one
`monitor_host` container per target should run at a time; nothing prevents running two targets'
monitors concurrently on different ports, but see the RAM caution below.

## Verification status (2026-08-17)

Live-verified end-to-end for **`router_py`** (host-subprocess path, all 8 actors incl. the
`router_1.01`/`router_2` extras) and **`router_cpp`** (both the `docker exec` path for
router/crypto and the host-subprocess path for upstream/downstream) — `docker build`, `start.sh`,
`GET /`, `GET /api/actors`, `POST /api/start_all` → `GET /api/status` all green, `POST
/api/stop_all`, `stop.sh`. This is also what surfaced and confirmed the fix for the
`downstream_host` config-path regression above.

**Not yet live-verified: `router_java`.** The host this was built on has only 2.8GB RAM (see
`../to_do_java_cpp.md`'s live-resilience-suite note for the same caution on the same host) —
verification was deliberately done one stack at a time, and router_java wasn't reached in this
pass. `backends/router_java.py` is structurally the same shape as `backends/router_cpp.py` (both
`docker exec` into a prebuilt container for a subset of actor types), so it's expected to work, but
that's inference, not verification — run `./start.sh router_java` and repeat the same
start_all/status/stop_all check before trusting it.

**Not yet deleted: the old `<impl>/monitor/` directories.** `router_py/monitor/`,
`router_java/monitor/`, `router_cpp/monitor/` (backend `main.py` + `static/index.html`) are inert —
nothing launches them anymore — but left in place until the UI has been eyeballed for all three
targets, not just curl-verified. Delete them (and this note) once that's done.
