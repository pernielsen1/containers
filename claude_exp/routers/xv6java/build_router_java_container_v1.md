# ISO 8583 Router — Java Port + Container (v1)

## Purpose

A Java port of the ISO 8583 payment router built in `claude_exp/xv2` through `claude_exp/xv5`
(all Python), running in a Docker container, developed via VSCode against files on the host.
This tests whether the spec's *architecture* — not just its Python implementation — survives a
language change. The router core stays portable to C++ for the performance-critical path,
exactly like the Python version's own stated design principle (see
`claude_exp/xv2/build_router_v2.md`'s "Design principles").

Scope for this v1: router + simulators (crypto_host, downstream_host, upstream_host), single
instance of each — no router_1.01/router_2/partner_b multi-instance scenario yet. The web
dashboard was *not* reimplemented in Java; instead, xv5's Python monitor was reused as-is against
the Java backend (see "Frontend" below) — this turned out to be a better idea than originally
briefed, since the monitor only ever speaks plain HTTP to each actor.

---

## Repository layout

```
xv6java/
├── briefs/
│   ├── java_container_router.md      # original brief + confirmed decisions
│   └── build_router_input_v2.md
├── Dockerfile                        # Java 21 + Maven + Node/Claude Code CLI
├── start.sh / stop.sh                # container lifecycle (bind-mount + docker exec workflow)
├── dockerstart.sh                    # ensures the Docker daemon is running (sudo, with fallback)
├── terminal.sh                       # interactive shell into the running container
├── monitor_start.sh / monitor_stop.sh # dashboard lifecycle (runs on the HOST, not in-container)
├── run_test.sh                       # end-to-end CLI driver (host-side, docker exec -d)
├── pom.xml                           # single Maven module, shaded jar
├── config/
│   ├── test_spec.xml                 # j8583 packager config
│   ├── pans_defined.json / f47.json
│   ├── router_1.json / crypto_host.json / downstream_host.json / upstream_1.json
│   └── upstream_1_input/             # gitignored; test_cases.csv lives here at runtime
├── test_csv_files/test.csv
├── monitor/                          # ported from xv5, adapted (see "Frontend")
│   ├── main.py
│   └── static/index.html
└── src/
    ├── main/java/com/xv6/
    │   ├── shared/      # Framing, ImsConnect, IsoUtils, Stats, CommandServer, CryptoUtils, ...
    │   ├── router/      # RouterConfig, Upstream, DownstreamConnection, CryptoClient,
    │   │                # Dispatcher, RouterSession, RouterMain
    │   └── simulators/{cryptohost,downstreamhost,upstreamhost}/*Main.java
    └── test/java/com/xv6/   # JUnit 5, mirrors xv5's tests/
```

One Maven module, one shaded jar (`target/xv6java.jar`) — every actor is just a different `Main`
class launched as `java -cp target/xv6java.jar com.xv6.router.RouterMain --config
config/router_1.json`, mirroring how the Python build launched one script per actor.

---

## Key technical decisions

- **ISO 8583**: [j8583](https://j8583.sourceforge.net/) — Maven coordinate `net.sf.j8583:j8583`
  (note: the groupId differs from the library's own Java package, `com.solab.iso8583`).
  Structural difference from pyiso8583: j8583 treats the **MTI** as
  `IsoMessage.getType()/setType(int)`, not a numbered field, and computes the **bitmap**
  automatically — neither is a settable "field" the way the Python spec's dict used `"t"`/`"p"`/
  `"1"` keys. `config/test_spec.xml` defines only the real data fields (2, 3, 4, 11, 14, 24, 37,
  38, 39, 41, 42, 47, 52, 55).
- **JSON**: Jackson (`com.fasterxml.jackson.databind` 2.17.1). Config records use
  `@JsonIgnoreProperties(ignoreUnknown = true)`, which makes the entire "exclusion set" bug class
  from Python's `RouterConfig.from_file()` (build_router_v2.md's #1 documented pitfall)
  disappear by construction — unknown JSON keys (`type`, `is_active`) are silently ignored rather
  than requiring a hand-maintained exclusion list.
- **HTTP** (stats/stop/log_level/logs, and crypto_host's REST validate endpoints):
  `com.sun.net.httpserver.HttpServer` — built into the JDK, zero extra dependency.
- **Crypto**: standard JCE (`javax.crypto`), no BouncyCastle. Triple-DES, single-DES, and
  HMAC-SHA1 are all in the default `SunJCE` provider on JDK ≥ 8u162 (this container uses 21).
  `SecretKeySpec` accepts 16-byte keys for `DESede` directly (two-key triple-DES, K1‖K2‖K1) —
  no policy jars needed.
- **Concurrency**: `java.net.Socket`/`ServerSocket` + one blocking `Thread` per connection,
  `ArrayBlockingQueue` for the dispatcher's bounded queue, `ConcurrentHashMap` + `ReentrantLock`
  for the pending-STAN map — direct `java.util.concurrent` analogs of the Python design, keeping
  the router core's C++ portability intact.
- **Build**: Maven, single module, `maven-shade-plugin` → one fat jar.

---

## Container

`Dockerfile`: `mcr.microsoft.com/devcontainers/base:ubuntu` + `openjdk-21-jdk` + `maven` +
Node.js/`npm install -g @anthropic-ai/claude-code` (matches this repo's existing container
convention, e.g. `AnaCredit_c/.devcontainer`, `claude_exp/duns_connect`).

`start.sh` / `stop.sh`: bind-mount + `docker exec` workflow (no `devcontainer.json`) — edit on
the host via VSCode as normal; build/run Java via `docker exec xv6java ...`. Runs with
`--network host` so the container shares the host's ports directly (important: this means
xv6java's actor ports, 8080-8083, are the *same* ports xv5's Python actors use — the two can't
run simultaneously). `dockerstart.sh` ensures the Docker daemon itself is running first
(`sudo service docker start`, falling back to a direct `dockerd` if that fails) — starting the
daemon needs root and will prompt for a password when run interactively; there's no way around
that from an automated/non-interactive session.

---

## Testing

`mvn test` — 24 JUnit tests, all passing: `FramingTest` (7), `StatsTest` (3), `CryptoUtilsTest`
(6), `IsoUtilsRoundTripTest` (2), `RouterConfigTest` (1), `DispatcherResilienceTest` (4),
`RouterFullStackTest` (1, full-stack integration — crypto/downstream/router/upstream wired
in-process, CSV-equivalent rows in, field 39 asserted on the results).

`run_test.sh <csv_file>` — end-to-end CLI driver, run on the **host** (not inside the
container): launches all four actors via `docker exec -d xv6java java -cp target/xv6java.jar
<MainClass> --config ...`, waits for readiness, uploads the CSV, calls `/start`, polls
`/results`, prints a report. Follows the same safety checklist documented in
`build_router_v2.md` (fail-fast `curl -f`, `trap cleanup EXIT`, guarded assignments under
`set -e`) — including one adaptation specific to this setup: teardown goes through each actor's
own `/stop` HTTP route rather than a host-side PID kill, since `docker exec` doesn't forward
signals from a host-side kill into the container's PID namespace.

Verified for real (not just JUnit): a full `run_test.sh` run against actual `docker exec`
subprocesses completed with correct results and clean teardown — no orphaned `java` processes,
no ports left bound.

---

## Frontend: xv5's Python monitor, reused as-is against the Java backend

The monitor dashboard was *not* rebuilt in Java. Insight from testing: the monitor only ever
talks to an actor's `CommandServer` over plain HTTP (`/stats`, `/stop`, `/log_level`, `/logs`,
plus upstream's `/start`/`/results`/`/upload`) — it has no idea, and no reason to care, whether
the process behind that port is a JVM or a Python interpreter. Since the Java `CommandServer`
(built on `com.sun.net.httpserver.HttpServer`) mirrors that exact route shape and JSON contract,
xv5's monitor works against xv6java's actors with only the launch/liveness-tracking layer
adapted — the frontend HTML/JS is untouched.

**Runs on the host**, not inside the xv6java container — it's a thin dashboard process, not part
of the Java build.

Adaptations in `monitor/main.py` (ported from `xv5/monitor/main.py`):
- `MAIN_CLASS_BY_TYPE` (fully-qualified Java class names) replaces `SCRIPTS_BY_TYPE`.
- `launch_actor()` runs `docker exec -d xv6java java -cp target/xv6java.jar <MainClass>
  --config <path>` instead of a host `subprocess.Popen`.
- `is_running()` checks live `/stats` instead of polling a `Popen` handle — `docker exec -d`'s
  client process exits the instant the detached command starts, so there's no process to poll;
  liveness is defined as "the actor's own `/stats` endpoint answers."
- `_terminate_all()` (the monitor's own atexit/SIGTERM safety net) now POSTs `/stop` to every
  running actor instead of calling `proc.terminate()` — same intent (killing the monitor
  shouldn't strand actors), implemented over HTTP since there's no process handle to hold. If an
  actor ignores `/stop`, the container itself (`./stop.sh`) is the hard backstop, same as
  `run_test.sh`.
- `/api/csv_files` reads each upstream actor's own `input_dir` field from its config instead of
  assuming a fixed `"input"` subfolder name (xv6java's upstream configs name it e.g.
  `upstream_1_input`).

`monitor_start.sh` / `monitor_stop.sh` (new, at the project root): pidfile-based lifecycle,
mirroring xv5's `run/monitor.sh` / `kill_monitor.sh` — deliberately *not* `pgrep -f
"monitor/main.py"`, since that exact pattern already left a zombie xv5 monitor alive on port 8090
for several hours earlier in this project (matched an unrelated process by command-line
substring).

**Verified end-to-end, live**: dashboard "Start All" launched all 4 Java actors and showed them
connected; CSV upload + `/start` + results through the dashboard's proxy produced correct
response codes matching `expected_39`; "Stop All" cleanly stopped all 4 actors (no leftover
`java` processes, no bound ports); `monitor_stop.sh` freed port 8090 and removed its pidfile.

Usage: `./start.sh` (container) → `./monitor_start.sh` (dashboard on `http://localhost:8090`) →
work in the dashboard → `./monitor_stop.sh` → `./stop.sh`.

---

## Known issues (not fixed in this v1, noted for later)

- **Frontend: log level can't actually be changed from the dashboard.** `renderCard()` rebuilds
  each card's entire HTML — including the log-level `<select>` — on every 2-second poll tick,
  and always hardcodes `<option value="INFO" selected>` rather than reflecting the actor's real
  current level. The `change` handler does fire and does POST `/log_level` correctly, but the
  dropdown visually snaps back to "INFO" within ~2 seconds regardless of what was chosen, making
  it look like the control does nothing. Fix needs both: read back and reflect the actor's actual
  level when rendering, and stop clobbering the control on every poll tick (e.g. skip
  re-rendering the select while it has focus/differs from cache, rather than a full innerHTML
  replace).

## Container console visibility — resolved: copy-to-clipboard commands, not an embedded shell

A first design explored embedding a full interactive terminal in the dashboard: xterm.js in the
browser bridged over a WebSocket to a PTY running `docker exec -it xv6java bash` on the monitor
host. Rejected before implementation — the monitor already binds `0.0.0.0:8090` (LAN-reachable,
not just localhost), and shipping a real, unauthenticated shell into the container over HTTP was
judged a security opening not worth taking for a dev tool, even a local one.

What shipped instead: the dashboard hands the operator the *exact* command to run in their own
terminal, rather than becoming a terminal itself. No new dependency, no long-lived connection, no
new attack surface — just three plain JSON routes and a couple of buttons.

- **Header "Attach Shell" button** — `GET /api/commands` returns `{"shell": "docker exec -it
  xv6java bash"}` (the same thing `terminal.sh` runs); the button copies it to the clipboard.
- **Per-actor "Commands" button** (next to "Logs") opens a modal with two commands, each with its
  own copy button, sourced from `GET /api/actor/<name>/commands`:
  - **Force-kill** — an escape hatch for when the graceful `/stop` HTTP call doesn't respond.
    Presented as a small multi-line script rather than a single `bash -c '...'` one-liner, so an
    operator can actually read it before pasting: `PATTERN="<main class> --config <rel_config>"`,
    look up the PID via `docker exec xv6java jps -lm | grep -F "$PATTERN" | cut -d" " -f1` (only
    `jps` itself needs `docker exec`; `grep`/`cut` run in the operator's own shell, which is what
    keeps this free of the nested-quoting a one-liner would need), then `docker exec xv6java kill
    -9 "$PID"` — with an explicit "no matching process" message and non-zero exit if nothing was
    found. Matching on the full class+config string (not just the class name) is what makes this
    safe when multiple instances share a main class, e.g. two router instances under
    `/api/routers_by_partner`; matching on class name alone could target the wrong one. Verified
    live by simulating two same-class router instances side by side and confirming the generated
    script for one killed only that instance.
  - **Tail live console** — `docker exec xv6java tail -F logs/<name>.console.log`. Needed a small
    change to `launch_actor()`: actors were launched via bare `docker exec -d ... java ...` with
    stdout/stderr going nowhere (the detached client exits immediately, so there was nothing to
    capture); the java invocation is now wrapped in `bash -c 'mkdir -p logs && java ... >
    logs/<name>.console.log 2>&1'`, truncating on every (re)launch so the tail always reflects
    the current run. Deliberately separate from the existing "Logs" modal, which reads the
    actor's own structured, buffered `/logs` HTTP endpoint — raw stdout (JVM startup banners,
    uncaught stack traces) isn't necessarily routed through that logger.

---

## Environment notes

- This WSL environment has ~2.8GB RAM and no `.wslconfig` found under `/mnt/c/Users` — the first
  `docker build` was slow (image export/unpack took minutes) under memory pressure, not because
  anything was broken.
- Starting the Docker daemon requires `sudo` (root is needed for `dockerd`'s network
  namespace/cgroup management; being in the `docker` group only lets the *client* talk to an
  already-running daemon). `dockerstart.sh` handles this but still needs an interactive password
  when the daemon isn't already up.
- xv5 (Python) and xv6java (Java) actors use the *same* ports (8080-8083) and the monitor uses
  the same port (8090) — only one variant can be running at a time.
