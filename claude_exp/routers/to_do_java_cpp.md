# to_do — router_java / router_cpp parity

Tracks fixes made in `router_py` (or the shared Python actors) that still need porting to
`router_java` and/or `router_cpp`.

## Open

- **INFO-level startup/connection logging** (done in `router_py` 2026-08-09). Every actor should
  log at least INFO on startup and on connection established, even outside debug mode. Fixed in
  `router_py`:
  - `upstream_host/main.py` (shared, backs `upstream_2`/`upstream_y_3`) — was fully silent; added
    startup log (listening port or connect target) and connect/disconnect logs.
  - `router_py/simulators/crypto_host/main.py` — was fully silent; added a startup log (no
    persistent connection to log, it's stateless HTTP per request).
  - `router_py/router/main.py` — added a top-level "router starting: ..." log; its
    `downstream.py`/`upstream.py` already logged connect/accept.
  - Not yet checked: whether `router_java`/`router_cpp`'s equivalent upstream/crypto-host
    simulators and router entry points have the same gap. Given they're near-1:1 ports of
    `router_py`, likely yes.

- **Round 5 debug/tracing initiative (`briefs/debug_trace_master.md`) — only partially ported.**
  All 5 phases are done in `router_py` (2026-08-07). On 2026-08-08 only item (1) and part of (2)
  below were ported to `router_java`/`router_cpp`; the rest is still outstanding:
  - Phase 1 (`router_stan` correlation ID) — **done**, ported to both languages 2026-08-08.
  - Session-teardown silent-pending-drop fix (found during Phase 3 verification) — **done**,
    ported to both (`Dispatcher.drainAndStop()` / `dispatcher.cpp`'s `drain_and_stop()`), each with
    a passing test.
  - Phase 2 (structured JSON-lines logging) — **partially done**: the shared C++ `crypto_host`
    container's `log.cpp` already emits `{ts, level, message}`. Not yet done: router_java's and
    router_cpp's *own* in-tree logging (their router/simulator entry points) — still whatever they
    had before, not JSON-lines like `router_py`'s `shared/json_log.py`.
  - Phase 3 (live read-only `/pending` endpoint) — **not ported**. Only the drop-fix's logging
    landed; the `pending_snapshot()` method + `/pending` route + monitor proxy itself is still
    router_py-only.
  - Phase 4 (on-demand `/trace` — `TraceRecorder`, arm-for-N/STAN/PAN, 6-hop capture) — **not
    ported**.
  - Phase 5 (per-hop latency percentiles in `Stats`/`/stats`) — **not ported**.
  - Monitor UI for Phases 3/4 (Pending/Trace panels) — **deliberately deferred**, not a bug: user
    wants to settle on a UI redesign first rather than copy router_py's per-language hand-built
    modal approach. Don't build this until that's resolved.

- **Live-process resilience scenario suite (`router_py/test_resilience.py`-style) — not ported.**
  Only *unit-level* Dispatcher tests exist for router_java/router_cpp
  (`DispatcherResilienceTest.java`, `router_cpp/test/dispatcher_test.cpp`, both built during the
  2026-08-08 port). router_py's live scenario suite — spinning up real actor subprocesses and
  killing/reconnecting them mid-flight (e.g. `scenario_stuck_pending_on_downstream_teardown`) — has
  no equivalent in either language yet. Check whether their session-teardown path has the same kind
  of gaps `router_py` had before assuming the unit tests alone give equivalent coverage.

- **Pre-existing `RouterFullStackTest` failure in `router_java`** (not caused by this round's
  changes - confirmed via `git stash` before any of it started): `RouterFullStackTest.startStack`
  fails with `IllegalStateException: port 18083 not ready (key=router)` in `@BeforeAll`, so every
  `@Test` in that class errors out before running. Surfaced repeatedly while verifying the
  2026-08-09 logging/pending/trace ports (each `mvn test` run shows `Tests run: N, Errors: 1` for
  this reason alone, everything else passing). Not investigated - noted here so it gets fixed
  before calling router_java's test suite "clean" again.

- **Legacy "xv6" naming cleanup** (cosmetic, not a functional bug, but flagged as a standing
  TODO). Both `router_java` and `router_cpp` were renamed from `xv6java`/`xv7cpp` on 2026-08-01, but
  only the top-level directory changed — internals didn't:
  - `router_java`: Java package still `com.xv6.*`.
  - `router_cpp`: C++ namespace still `xv6::router`/`xv6::shared`; CMake targets still
    `xv6_router`/`xv6_shared`/`xv6_tests`.
  Touches every file in both trees — plan as its own deliberate pass, not a drive-by edit.

## Done
