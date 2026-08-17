# to_do — router_java / router_cpp parity

Tracks fixes made in `router_py` (or the shared Python actors) that still need porting to
`router_java` and/or `router_cpp`.

## Open

- **Live-process resilience scenario suite — ported 2026-08-16, not yet live-verified.**
  `router_java/test_resilience.py` and `router_cpp/test_resilience.py` now exist (both use
  `docker exec` into a pre-built container for every actor except `upstream_host`/
  `downstream_host`, unlike router_py's plain host subprocesses). router_java's port is a
  near-direct copy - its monitor.main actor-lifecycle helpers and actor names
  (`router_1`/`upstream_1`/etc.) match router_py's 1:1. router_cpp's needed real adaptation: its
  actor names differ (`router_cpp-router`/`upstream_host`, not `router_1`/`upstream_1`), and its
  `is_running()` takes the actor dict rather than a name string; also added a `stop_actor(actor)`
  helper to `router_cpp/monitor/main.py` (factored out of its `/api/actor/<name>/stop` route),
  which didn't have a reusable one like the other two languages.

  **Note (2026-08-17): this `is_running(actor)` vs. `is_running(name)` drift was one of the two
  concrete examples that motivated consolidating the three `<impl>/monitor/` copies into
  `../monitor_host/` (see its `build_router.md`) — that inconsistency no longer exists architecturally
  going forward (each target's `backends/<target>.py` is its own module now, not a shared
  signature). It's called out here only because these two test suites still import
  `router_java/monitor/main.py` / `router_cpp/monitor/main.py` directly, not `monitor_host/` — both
  old `monitor/` directories are being kept in place (inert for the dashboard itself) until this
  dependency is confirmed still needed or these suites are re-pointed at `monitor_host/backends/`.**

  Both ports compile/import clean
  and got a matching `test_resilience.sh` wrapper, but neither has actually been run live yet -
  deferred because this host was at ~70MB free RAM when the ports were finished (router_java's
  container up, router_cpp's not even built), and a live run kills/restarts real actor processes
  repeatedly for ~4-5 minutes per language. Same OOM risk `run_soak.md` documents for soak runs -
  **run both suites standalone (VS Code + Claude Code session closed) before trusting them.**

## Done

- **Pre-existing `RouterFullStackTest` failure in `router_java`** — fixed as a side effect of the
  `downstream_host` consolidation below: rewriting the test's `@BeforeAll` to launch
  `downstream_host` as a real subprocess (instead of in-process `DownstreamHostMain`) also fixed
  the flaky `port 18083 not ready` failure. `RouterFullStackTest` now passes reliably.

- **Legacy "xv6" naming cleanup** (2026-08-13) — both `router_java` and `router_cpp` were renamed
  from `xv6java`/`xv7cpp` on 2026-08-01, but only the top-level directory changed until now:
  - `router_java`: Java package `com.xv6.*` → `com.router.*` (38 files, plus `pom.xml`'s groupId
    and every hardcoded `-cp` classpath string in scripts/monitor).
  - `router_cpp`: C++ namespace `xv6::router`/`xv6::shared` → `router::`/`shared::`; CMake targets
    `xv6_router`/`xv6_shared`/`xv6_tests` → `router_lib`/`shared_lib`/`router_tests` (47 files).
  Full test suites re-verified green after each rename (router_java: `mvn test`, router_cpp:
  `router_tests` binary + Docker functional smoke test).

- **INFO-level startup/connection logging** — every actor now logs at least INFO on startup and
  on connection established, even outside debug mode. `router_py` done 2026-08-09 morning;
  `router_java`/`router_cpp` ported same day (added logging to `Upstream.java`/`upstream.cpp`,
  `DownstreamConnection.java`/`downstream_connection.cpp`, `RouterMain.java`/`router_main.cpp`,
  and each language's `CryptoHostMain`/`crypto_host_main.cpp` stub - `downstream_host` already had
  this in both languages).

- **Round 5 debug/tracing initiative (`briefs/old/debug_trace_master.md`) — all 5 phases now ported to
  all three languages**, done 2026-08-09:
  - Phase 1 (`router_stan` correlation ID) — done 2026-08-08.
  - Session-teardown silent-pending-drop fix — done 2026-08-08.
  - Phase 2 (JSON-lines logging) — router_java: new `JsonLogFormatter`, wired into `LogBuffer` +
    the JVM's console handler; router_cpp: `log.cpp`/`command_server.cpp` switched to the same
    `{ts, level, message}` shape + real-parsed-JSON `/logs` (matching the shared crypto_host
    container's existing Phase-1 treatment).
  - Phase 3 (`/pending`) — `Dispatcher.pendingSnapshot()`/`pending_snapshot()` + route, both
    languages, each with a passing unit test ported from router_py's reference test.
  - Phase 4 (`/trace`) — new `TraceRecorder.java`/`trace_recorder.h`+`.cpp` (Java: `Map<String,
    Object>`-based entries; C++: `nlohmann::json`-based, since the data is genuinely dynamic-shaped
    per hop), raw wire bytes threaded through `RoutedMessage`/`submit_response` in both languages,
    6-hop capture wired into `process()`/`handle_response()`, `+8`/`+30` new tests respectively
    (Java `TraceRecorderTest`, C++ `trace_recorder_test.cpp` - direct ports of router_py's
    `test_trace.py`).
  - Phase 5 (latency percentiles) — `Stats.recordLatency()`/`record_latency()` + percentile calc
    added to both languages' shared `Stats` class, wired at the same 4 points
    (`queue_wait`/`crypto_rtt`/`downstream_rtt`/`total`), each with 3 new tests ported from
    router_py's `test_stats.py`.
  - Monitor UI for Phases 3/4 — still **deliberately deferred**, not a bug: user wants to settle
    on a UI redesign first. Don't build Pending/Trace panels for router_java/router_cpp until
    that's resolved.

  Final test counts after this round: router_java 30/31 (1 pre-existing unrelated failure, see
  Open above), router_cpp 142/142 assertions across 41 test cases.
