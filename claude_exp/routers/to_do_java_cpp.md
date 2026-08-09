# to_do — router_java / router_cpp parity

Tracks fixes made in `router_py` (or the shared Python actors) that still need porting to
`router_java` and/or `router_cpp`.

## Open

- **Live-process resilience scenario suite (`router_py/test_resilience.py`-style) — not ported.**
  Only *unit-level* Dispatcher tests exist for router_java/router_cpp
  (`DispatcherResilienceTest.java`, `router_cpp/test/dispatcher_test.cpp`). router_py's live
  scenario suite — spinning up real actor subprocesses and killing/reconnecting them mid-flight
  (e.g. `scenario_stuck_pending_on_downstream_teardown`) — has no equivalent in either language
  yet. **In progress as of 2026-08-09, resuming 2026-08-10** — see
  `project_routers_monorepo.md` memory for full session recap and the environmental gotcha (both
  languages' non-`upstream_host` actors only launch via `docker exec` into a pre-built container,
  unlike router_py's plain host subprocesses) that the port needs to account for.

- **Pre-existing `RouterFullStackTest` failure in `router_java`** (not caused by the 2026-08-09
  round - confirmed via `git stash` beforehand): `RouterFullStackTest.startStack` fails with
  `IllegalStateException: port 18083 not ready (key=router)` in `@BeforeAll`, so every `@Test` in
  that class errors out before running. Not investigated - noted here so it gets fixed before
  calling router_java's test suite "clean" again.

- **Legacy "xv6" naming cleanup** (cosmetic, not a functional bug, but flagged as a standing
  TODO). Both `router_java` and `router_cpp` were renamed from `xv6java`/`xv7cpp` on 2026-08-01, but
  only the top-level directory changed — internals didn't:
  - `router_java`: Java package still `com.xv6.*`.
  - `router_cpp`: C++ namespace still `xv6::router`/`xv6::shared`; CMake targets still
    `xv6_router`/`xv6_shared`/`xv6_tests`.
  Touches every file in both trees — plan as its own deliberate pass, not a drive-by edit.

## Done

- **INFO-level startup/connection logging** — every actor now logs at least INFO on startup and
  on connection established, even outside debug mode. `router_py` done 2026-08-09 morning;
  `router_java`/`router_cpp` ported same day (added logging to `Upstream.java`/`upstream.cpp`,
  `DownstreamConnection.java`/`downstream_connection.cpp`, `RouterMain.java`/`router_main.cpp`,
  and each language's `CryptoHostMain`/`crypto_host_main.cpp` stub - `downstream_host` already had
  this in both languages).

- **Round 5 debug/tracing initiative (`briefs/debug_trace_master.md`) — all 5 phases now ported to
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
