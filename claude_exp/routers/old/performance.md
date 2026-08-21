# Performance results and discussion

(File renamed from `performance_result_20260730.md` on 2026-08-01 — this is the running log for
all performance discussion/investigation on this repo, not just the 2026-07-30 sweep it started
from.)

## Performance sweep result — 2026-07-30

Full default sweep (`./stress_test.sh`, tps 50/100/200/400, 30s each), run uninterrupted with no
concurrent activity on the host.

## Results

| Implementation | 50 tps | 100 tps | 200 tps | 400 tps |
|---|---|---|---|---|
| router_py | 23% errors, p50 5983ms | 68% errors, p50 14294ms | 87% errors, p50 14278ms | 92% errors, p50 17092ms |
| router_java | 18% errors, p50 5863ms | 56% errors, p50 11810ms | 77% errors, p50 15689ms | 86% errors, p50 16091ms |
| router_cpp | **failed to start** (downstream_host timeout) | **failed to start** (same) | 0 errors, p50 5.6ms | 0 errors, p50 3.7ms |

Raw rows are in `stress_results.csv` (timestamps 2026-07-30T23:42–23:52).

Notice the pattern: router_cpp didn't just perform better — at 50/100 tps it didn't even manage to
*start* within its 30s readiness window, then ran flawlessly at 200/400 tps. That's not a
performance curve, that's a coin flip on whether the host had enough headroom at that moment to
bring four processes up in time.

## Why this is very likely environment, not implementation code

The two things the crypto_host split actually changed were isolated and tested directly:

- The shared `crypto_host` container handled 100 concurrent requests directly in under 40ms.
- router_py's crypto client (8 threads, 500 calls) handled it in under 120ms max.

Both fine in isolation. What's different in the full sweep is everything running at once on this
specific box: 2.8Gi total RAM, swap sitting at 1.0Gi/1.0Gi (essentially always full) even at rest.
Python and Java are the two memory-hungrier runtimes here (JVM heap, Python's own allocator/GC),
and under real load on a box that's already swapping, this is exactly the signature you'd expect —
latencies in the multi-second range are classic page-fault/swap-I/O territory, not application
logic.

## Takeaway (original, 2026-07-30 — superseded below)

The *relative* ordering (C++ ≫ Java/Python under memory pressure) is directionally believable, but
these absolute numbers shouldn't be trusted as a real implementation comparison — they're
measuring this VM's swap thrashing more than the routers themselves. A host with more headroom
(not swapping at rest) is needed before drawing conclusions about router_py-vs-router_java-vs-router_cpp
performance from this sweep.

## Update — 2026-07-31: isolated re-runs (`--impl` one at a time)

`stress_test.sh` already supports running a single implementation to completion
(`./stress_test.sh --impl router_py`, etc.) — used to re-test each implementation alone, with nothing
else competing on the host, to check whether the contention theory above actually explains the
bad numbers.

**router_cpp** (rows `2026-07-31T00:09:59`–`00:11:53`): clean across the board. 0 errors at every tps,
p50 ~2ms, p99 ~3.5ms, max never above 42ms even at 400 tps. `achieved_tps` plateaus at ~311 for a
400 target — a real throughput ceiling, reached gracefully (no error spike, no latency blowup).
**This matches the original contention theory** — isolating router_cpp turned spiky/inconsistent
results (e.g. row 11: p95 spiking to 10616ms at just 50 tps) into a clean, repeatable line.

**router_java** (rows `00:21:04`–`00:23:16`) and **router_py** (rows `00:27:17`–`00:29:24`): isolation changed
almost nothing.

| tps | router_java contended | router_java isolated | router_py contended | router_py isolated |
|---|---|---|---|---|
| 50  | 18.3% err, p50 5863ms  | 14.5% err, p50 4723ms  | 16.9% err, p50 5202ms  | 17.7% err, p50 5257ms |
| 100 | 56% err, p50 11810ms   | 54% err, p50 11137ms   | 59.9% err, p50 11573ms | 60.6% err, p50 12100ms |
| 200 | 77% err, p50 15689ms   | 76% err, p50 14683ms   | 85.8% err, p50 13239ms | 85.6% err, p50 13360ms |
| 400 | 86% err, p50 16091ms   | 87% err, p50 15599ms   | 90.3% err, p50 15865ms | 90.2% err, p50 16225ms |

**This disproves the contention theory for these two.** Whatever is happening, it happens the same
way whether the implementation has the whole host to itself or not — so the original "it's just a
memory-starved laptop" explanation only actually holds for router_cpp.

The other notable thing: router_py's and router_java's numbers track each other closely at every single tps
level (e.g. 17.7% vs 14.5% errors at 50 tps, 90.2% vs 87% at 400). Two unrelated language-specific
bugs producing near-identical failure curves would be a big coincidence — more likely they're
hitting the same underlying constraint, and router_cpp isn't.

There's also an earlier, unconfirmed observation worth chasing: TCP `TIME-WAIT` sockets were seen
ballooning into the hundreds within seconds of a live router_py run against the shared `crypto_host`.
`crypto_host_main.cpp` never configures cpp-httplib's keep-alive settings, so it runs on library
defaults (`keep_alive_max_count=5`, 5s idle timeout) with a fixed 8-thread server pool. If router_py's
and router_java's HTTP clients end up churning through more rotating connections than that pool can
absorb, while router_cpp's client happens to reuse connections more efficiently, that would explain
this exact pattern — but this is a hypothesis, not yet verified. Chasing it further is next.

## Takeaway (revised)

Don't jump to conclusions from a single day's data. The environment-contention theory turned out
to be only half right: it explains router_cpp's spiky first-day results, but not router_py/router_java's
consistent, isolation-proof degradation. Something specific to those two implementations (or to
how they talk to the shared `crypto_host`) is capping them well below what the container itself
can handle in isolation. That's tomorrow's investigation — not diagnosed yet, just narrowed down.

## Update — 2026-07-31 continued: root-caused down to a single number, fix not yet found

Deep-dive on router_py specifically (agreed to check Python first). Chased the connection-churn
hypothesis above to its conclusion and it was **wrong** — full elimination trail below, each step
verified before moving to the next, so the surviving finding at the bottom can be trusted:

1. **Bumping `crypto_host`'s keep-alive limits** (`keep_alive_max_count`/`timeout` from library
   defaults 5/5s to 10000/300s) — no improvement, slightly worse (60% → 71% errors at 100 tps/15s).
2. **Bumping the server's thread pool** (default 8 → 64 threads), keep-alive reverted to default —
   no improvement (58% errors, near-identical to baseline). TIME-WAIT churn returned as expected.
3. **Both together** — still broken (70.6% errors), but now with connections *stable* (18 ESTAB, 0
   TIME-WAIT) — ruled out connection churn and thread-pool starvation entirely.
4. **Control test: router_py against its own local Python stub crypto_host** (not the shared container),
   identical dispatcher/downstream_host/upstream code, identical new Fortanix wire protocol —
   **0 errors, p50=10.84ms.** This is the key result: it exonerates router_py's own code completely and
   confirms the problem is specific to talking to the shared C++ `crypto_host`.
5. **Docker/`network_mode: host` ruled out too** — extracted the built `crypto_host` binary from the
   image and ran it bare-metal (no container at all): identical failure (72.5% errors).
6. **Full pipeline instrumentation** (temporary — see note below): timestamped every stage —
   `crypto_client.py` call latency, dispatcher queue/dequeue, `downstream_host`'s own request
   processing and its from-conn writer, the router's downstream-receiver loop iteration time,
   `iso8583.decode()`. Every single stage measured **fast** (crypto calls <155ms max, usually single
   digit ms; `downstream_host` processing <1.5ms; its writer <1ms with zero backlog; decode
   <0.3ms). Yet the e2e gap between "router sent to downstream" and "router got the reply back",
   correlated by STAN, showed **p50=7s**, climbing to ~12s by the end of a 10s test — a classic
   "falling behind" queueing signature, with no single slow component to blame.
7. **The actual mechanism**: `router_py/router/dispatcher.py`'s 0100 leg is parallelized across
   `worker_threads` (8) dispatcher workers, but the **0110 leg's crypto call happens inline, one at
   a time, on the single `_downstream_receiver` thread** (`session.py`) — no parallelism at all for
   that leg. Measuring `validate_0110` latency specifically (not mixed with the parallel 0100
   calls): **p50=44ms against the shared C++ crypto_host vs p50=6ms against router_py's own local Python
   stub** — a ~7x difference. On an unparallelized path, sustainable throughput is `1/latency`: 6ms
   → ~166 msg/s (comfortably above the 100 tps target, matches 0 errors); 44ms → ~22 msg/s (far
   below target, matches the queueing collapse). This is architecturally a **pre-existing
   single-threaded bottleneck in router_py's dispatcher** that was never exposed before because whatever
   crypto_host was previously used was fast enough (sub-10ms) to stay under it.

**What's still unresolved: *why* is the shared C++ server's per-call latency ~44ms specifically for
requests *after* the first one on a given process, when plain sequential `curl` calls against the
same server are 10-20ms flat, every time?**
   - Sequential `curl` (not parallel): 10-20ms flat, no anomaly. Ruled out: the server or network
     generally being slow.
   - Bare Python `requests.post()`, same session, sequential: **first call 8.7ms, every call after
     that ~44ms** — reproduces with zero dependency on router_py's own code.
   - Raw `http.client` (bypassing `requests`/urllib3 entirely) with `TCP_NODELAY` **explicitly
     confirmed set** via `getsockopt` before any request: identical pattern (first call 2.5ms, rest
     ~44ms). Rules out client-side Nagle/urllib3-specific behavior.
   - Traced `set_tcp_nodelay(true)` on the C++ server into cpp-httplib's source: it only reaches
     `Server::create_server_socket` (the *listening* socket) — `process_and_close_socket()`, which
     receives each *accepted* connection's socket, never applies it, and TCP_NODELAY does not
     inherit from listener to accepted socket. Attempted a subclass overriding
     `process_and_close_socket` to set it directly on the accepted socket — **hit a real
     dead end**: that method is `private` in `httplib::Server`, so while it can be overridden, the
     override cannot call the base implementation, making this approach a dead end without
     reimplementing internal library logic.
   - Tried forcing every request onto a fresh connection instead (`set_keep_alive_max_count(1)`,
     sidestepping the "only broken on reuse" pattern rather than fixing it) — **no effect**, still
     flat ~44ms.

So: root cause is narrowed to a specific, reproducible number (steady-state per-call latency to
this specific C++ server, ~44ms, appearing only after the first request) and its architectural
consequence (router_py's single-threaded 0110 path can't keep up at that latency) — but the actual
mechanism behind the 44ms itself is still open. Next things worth trying: packet capture
(`tcpdump`) during a slow call to see if it's genuinely a network-level stall vs. something in the
server's request-handling path; check whether Java's `crypto_client` shows the same "first call
fast, rest ~44ms" fingerprint against the same server (would confirm this isn't Python-specific
either); consider whether cpp-httplib's regex-based route matching (`"/sys/v1/plugins/([^/]+)"`)
or response-construction path has some per-request fixed cost unrelated to sockets at all.

**Housekeeping note (resolved 2026-07-31)**: the temporary `print(...)`-based timing
instrumentation in `router_py/router/crypto_client.py`, `dispatcher.py`, `session.py`, and
`router_py/simulators/downstream_host/main.py` (`CRYPTO_TIMING`/`TRACE`/`DS_TRACE`/`DS_WRITE_TRACE`) has
been reverted — ahead of the long-soak GC test below, since per-message `print(..., flush=True)`
calls are themselves exactly the kind of overhead that could produce a false slowdown signal in
that test. All 28 router_py tests still pass after removal.

## Update — 2026-07-31 continued further: architectural fix for router_py, tps 50/100 completely resolved

The unsolved question above (why the shared C++ `crypto_host` takes ~44ms per call, after the
first request on a connection) never actually got root-caused. Instead, a design conversation
about the dispatcher's architecture found the more important issue directly:
`router_py/router/dispatcher.py`'s 0100 leg is parallelized across `worker_threads` (8) worker threads
pulling from a queue, but the 0110 leg's `handle_response()` was called **inline, one at a time,
directly on the single `_downstream_receiver` thread** (`session.py`) — never queued, never
pooled. Whatever the per-call latency to `crypto_host` was, that single-threaded leg could never
exceed `1/latency` throughput, and that's what was actually collapsing under load, independent of
whatever the 44ms number's root cause turns out to be.

**Fix implemented** (`router_py/router/config.py`, `dispatcher.py`, `session.py`): gave the 0110 leg its
own dedicated worker pool, symmetric to the 0100 leg's but on a separate queue so a 0100 flood
can't head-of-line-block 0110 responses:
- `RouterConfig` gained `response_worker_threads: int = 8`.
- `Dispatcher` gained a second queue (`_response_queue`) and a second pool of worker threads
  (`_response_worker_loop`) that call the existing `handle_response()` — that method's internals
  are unchanged, only *what calls it* changed.
- `Dispatcher.submit_response()` (new) replaces the old direct `dispatcher.handle_response(resp)`
  call in `session.py`'s `_downstream_receiver()` — the receiver thread now just enqueues and goes
  back to reading the socket, instead of blocking on a crypto call itself.
- `drain_and_stop()`/`purge()` updated to cover the new queue/pool too.

All 28 existing tests pass unmodified after the change.

**Result — isolated re-run, router_py only, same shared `crypto_host`, same `--impl router_py` sweep
methodology as the section above:**

| tps | before (errors / p50 / p99) | after (errors / p50 / p99) |
|---|---|---|
| 50  | 17.7% / 5257ms / 10274ms  | **0% / 5.3ms / 9.0ms**   |
| 100 | 60.6% / 12100ms / 23027ms | **0% / 5.1ms / 8.4ms**   |
| 200 | 85.6% / 13360ms / 25695ms | 43.7% / 17245ms / 19570ms |
| 400 | 90.2% / 16225ms / 31785ms | 86.9% / 14496ms / 31111ms |

50 and 100 tps are now completely clean — 0 errors, latency down roughly 1000x, right at the
target loads the router actually needs to sustain. This confirms the single-threaded 0110 path
was the real bottleneck all along, not (or not only) whatever was causing the 44ms/call number.

**200 and 400 tps still collapse**, though less severely than before. New signature seen in the
trace at these rates: individual crypto calls (`crypto0100_done`, `crypto0110_done`) now land at
15-95ms, well above the flat ~2-5ms seen at 50/100 tps — i.e. per-call latency itself is
inflating under higher concurrency, not just queueing on one starved thread. Working hypothesis
(not yet verified): router_py now drives up to 16 concurrent requests at `crypto_host` (8 from the 0100
pool + 8 from the new 0110 pool), against a server whose own cpp-httplib thread pool defaults to
`max(8, hardware_concurrency()-1)` — i.e. the client-side fix may have shifted the bottleneck from
"one starved client thread" to "the server's own thread pool saturating under real concurrency."
Next step: bump `crypto_host`'s thread pool explicitly and re-run the 200/400 tps sweep to check.

**Not yet done**: same fix (separate worker pool for the response leg) has not been ported to
router_java or router_cpp yet — worth checking whether either has an analogous single-threaded response
path before assuming this generalizes.

## Update — 2026-07-31 continued further still: thread-pool bump made it worse, reverted

Tested the "server thread pool saturating under 16 concurrent client requests" hypothesis from
the section above directly: bumped `crypto_host`'s cpp-httplib thread pool from its default
(`max(8, hardware_concurrency()-1)`) to a fixed 32 via `new_task_queue`, rebuilt, and re-ran the
identical `--impl router_py` sweep.

| tps | before bump (errors / p50 / p99) | after bump (errors / p50 / p99) |
|---|---|---|
| 50  | 0% / 5.27ms / 9.02ms      | 0% / **57.32ms** / 115.74ms |
| 100 | 0% / 5.1ms / 8.4ms        | 0% / **5070.04ms** / 8026.89ms |
| 200 | 43.7% / 17245ms / 19570ms | 76.4% / 13437ms / 27760ms |
| 400 | 86.9% / 14496ms / 31111ms | 87.9% / 15486ms / 31182ms |

**Every single tps level got worse**, including a previously perfect 100 tps run regressing to a
p50 over 5 seconds. This rules out the "server thread pool too small" hypothesis outright — if
that were the bottleneck, more threads should never hurt at a load (50 tps) that wasn't failing
before. Instead this looks like straightforward CPU oversubscription: this is the same
resource-constrained host flagged in the very first section of this document (2.8Gi RAM, at-rest
swap), and 32 server threads plus router_py's 16 client worker threads plus whatever else is running
(router_java's persistent container, this shell, etc.) is simply more concurrent work than the box has
cores for. More threads made scheduling worse, not throughput better.

**Reverted**: `crypto_host` is back to the cpp-httplib default thread pool. The 200/400 tps
collapse is still unexplained, but the working theory has shifted from "needs more server
threads" to "this host's core count is the real ceiling at higher concurrency" — consistent with
50/100 tps (well within capacity) being completely clean and 200/400 tps (well beyond it) failing
regardless of which knob gets turned.

**Practical takeaway**: the separate-worker-pool fix (previous section) is the validated,
unambiguous win — 0 errors at 50/100 tps, matching realistic target load. The thread-pool
experiment was a dead end specific to this host's resource ceiling, not a design flaw to replicate
elsewhere. Porting to router_java/router_cpp should carry over the *architecture* (separate pool for the
response leg), not this reverted experiment.

## Update — 2026-07-31 continued once more: ported to router_java and router_cpp

Confirmed both other implementations had ported router_py's *pre-fix* architecture faithfully, bug and
all: in each, a single dedicated downstream-receiver thread called the response-handling method
(`Dispatcher.handleResponse()` in Java, `Dispatcher::handle_response()` in C++) directly and
synchronously — same unparallelized 0110 leg, same theoretical `1/latency` throughput cap as router_py
had before its fix.

Applied the identical fix in both, mirroring router_py's shape exactly:
- **router_java**: `RouterConfig`/`RouterConfigJson` gained `responseWorkerThreads` (default 8).
  `Dispatcher` gained a second `BlockingQueue`, a `submitResponse()` method, and a
  `responseWorkerLoop()` pool calling the existing `handleResponse()`. `RouterSession`'s
  `downstreamReceiver()` now calls `dispatcher.submitResponse(resp)` instead of
  `dispatcher.handleResponse(resp)` directly. `drainAndStop()`/`purge()` updated to cover the new
  queue/pool.
- **router_cpp**: `RouterConfig` gained `response_worker_threads` (default 8, parsed in
  `router_config.cpp`). `Dispatcher` gained a second `std::deque`+condvar pair, a
  `submit_response()` method, and a `response_worker_loop()` pool calling the existing
  `handle_response()`. `RouterSession::downstream_receiver()` now calls
  `dispatcher_->submit_response(resp)` instead of `dispatcher_->handle_response(resp)` directly.
  `purge()`/`drain_and_stop()` updated to match.

**Verification**: both full test suites pass after the change (router_java: 18/18 JUnit tests, 2
call-site fixes needed in test files that constructed `RouterConfig` positionally;
router_cpp: 40/40 Catch2 assertions across 20 cases, no test changes needed since the existing tests
don't construct `Dispatcher`/`RouterConfig` with positional args the same way). Both also passed a
full functional `run_test.sh` end-to-end run (3-row CSV, correct RC/auth-code/field-47 per PAN,
matching pre-fix behavior).

## Update — 2026-07-31, final: full sweep confirms the fix for router_java, no-op (as expected) for router_cpp

Ran `--impl router_java,router_cpp` (50/100/200/400 tps, 30s each) against the shared `crypto_host`.

**router_java — same dramatic win as router_py:**

| tps | before (errors / p50 / p99) | after (errors / p50 / p99) |
|---|---|---|
| 50  | 14.5% / 4723ms / 9327ms   | **0% / 61.7ms / 108.5ms** |
| 100 | 54% / 11137ms / 20951ms  | **0% / 52.7ms / 112.8ms** |
| 200 | 76% / 14683ms / 27251ms  | 8.5% / 3841ms / 7456ms |
| 400 | 87% / 15599ms / 30351ms  | 43.9% / 8908ms / 17783ms |

50/100 tps completely resolved (0 errors), exactly matching router_py's outcome. 200/400 tps are still
not clean, but improved substantially even there — roughly half the error rate and half the
latency of before, not just noise. Consistent with the same "this host doesn't have the cores for
200+ tps of real concurrent work regardless of the app-level architecture" ceiling theory from the
router_py section above, rather than a remaining Java-specific bug.

**router_cpp — no observable change, exactly as predicted:**

| tps | before | after |
|---|---|---|
| 50  | 0% / 2.18ms | 0% / 2.29ms |
| 100 | 0% / 2.06ms | 0% / 2.13ms |
| 200 | 0% / 1.96ms | 0% / 2.04ms |
| 400 | 0% / 1.88ms | 0% / 1.80ms |

Numbers are within noise of each other. This confirms the earlier prediction: router_cpp's crypto-call
latency was never slow enough to expose the single-thread cap the bug represents, so removing that
cap changed nothing measurable. The fix is still correct to have made (defense against a slower
crypto backend in the future, and now all three implementations share the same architecture), it
just wasn't hiding an active bug in this implementation's case.

**Overall conclusion for this investigation**: the separate-response-worker-pool fix is validated
across all three implementations at the loads that matter (50/100 tps clean everywhere). The
remaining 200/400 tps degradation on router_py and router_java (not router_cpp) is very likely this specific
host's CPU capacity, not an application bug — a different, lower-priority question from the one
this investigation set out to answer.

## Update — 2026-07-31, curiosity check: is crypto really out of the picture at 200/400 tps?

One more isolation test to confirm the "host capacity, not crypto" theory directly: ran router_py's full
sweep against its **own local Python crypto stub** (default `router_1/config.json`, no shared
container, no network hop — crypto calls are essentially free) instead of the shared `crypto_host`.

| tps | shared `crypto_host` (errors / p50) | local Python stub (errors / p50) |
|---|---|---|
| 50  | 0% / 5.3ms      | 0% / 8.3ms |
| 100 | 0% / 5.1ms      | 0% / 10.7ms |
| 200 | 43.7% / 17245ms | 46.3% / 16872ms |
| 400 | 86.9% / 14496ms | 92.8% / 31683ms |

**Removing crypto from the picture entirely didn't fix 200/400 tps** — if anything it was
marginally worse (within noise). This rules crypto out as the cause of the remaining ceiling as
directly as possible: with an effectively-free crypto backend, router_py still can't sustain more than
roughly 150-190 real msg/s before collapsing. Whatever's capping it at that point is intrinsic to
the router itself under real concurrency (Python's GIL serializing work across the now-16 worker
threads, ISO8583 encode/decode, socket I/O) or this host's core count — not the crypto backend, and
not the architecture this investigation fixed.

## Where this leaves us

The question this investigation actually set out to answer — why does adding a real, shared,
network-hop crypto backend collapse throughput that used to work? — is answered and fixed: a
single-threaded response leg capped throughput at `1/crypto_latency` in all three implementations;
giving it its own worker pool (mirroring the existing 0100-leg pool) fixed it in router_py and router_java,
and was a no-op-but-correct change in router_cpp (which was never actually hitting the cap).

**100 tps clean, with 0 errors and single-digit-ms p50, in Python, talking to a real shared crypto
service over the network** is a solid result on its own terms — that's a real target load handled
by the least performance-oriented of the three implementations, running on a resource-constrained
laptop. 200+ tps is a separate, lower-priority question (host capacity / GIL, not a router bug),
and not one this investigation needs to chase further right now.

## Update — 2026-07-31, stress test part 2: does 100 tps hold up over 5 minutes?

Prompted by `the_routers.md`'s next question: 100 tps was only ever proven over 10-30s bursts —
does it hold for a sustained 5-minute (300s) run, and is there a GC-related slowdown over time in
Python (later: Java)? Before running this, reverted the temporary `CRYPTO_TIMING`/`TRACE`/
`DS_TRACE`/`DS_WRITE_TRACE` debug prints left over from the earlier investigation (see housekeeping
note above) — per-message `print(..., flush=True)` calls are exactly the kind of overhead that
would confound a timing-sensitive test like this one.

Added lightweight permanent instrumentation to `router_py/simulators/upstream_host/main.py`: each
completed 0100→0110 round trip now records `(sent_offset_s, latency_s)` — the time into the run
the request was sent, plus its turnaround time — capped at 200k samples like the existing latency
list. A new `/slow_responses?n=10` route returns the N slowest by latency. `stress_run.sh` now
fetches this after every run and appends to `routers/slow_responds.csv`
(`timestamp;implementation;target_tps;duration_s;rank;sent_offset_s;latency_ms`).

**Result — router_py, 100 tps target, 300s, against the shared `crypto_host`:**

```
router_py;100;300;28345;28257;88;94.48;444.0;1079.0;1366.09;1801.29
```

sent=28345, received=28257, errors=88 (**0.31%**), achieved_tps=94.48, **p50=444ms, p95=1079ms,
p99=1366ms, max=1801ms**.

This is a real regression from the 10-30s runs at the same 100 tps target (which showed 0 errors,
p50≈5-10ms) — over 5 minutes, the overall p50 balloons roughly 50-90x, though the error rate stays
low (0.31%, nothing like the 200/400 tps collapse).

**The `slow_responds.csv` data points at *when*, and it's not random noise:**

| rank | sent_offset_s | latency_ms |
|---|---|---|
| 1 | 296.8 | 1801.3 |
| 2 | 298.6 | 1701.9 |
| 3 | 298.6 | 1699.4 |
| 4 | 296.4 | 1698.7 |
| 5 | 296.9 | 1681.1 |
| 6 | 297.7 | 1677.7 |
| 7 | 298.1 | 1660.4 |
| 8 | 297.4 | 1654.5 |
| 9 | 297.4 | 1622.8 |
| 10 | 297.3 | 1615.8 |

**All 10 slowest round trips happened in the last ~3.5 seconds of a 300-second run** (296-298s),
not scattered throughout. A `urllib3.connectionpool: Connection pool is full, discarding
connection` warning also appeared three times, starting ~160s in (roughly halfway through).

**Reading this carefully, not jumping to conclusions**: this pattern — latency growing toward the
end rather than periodic spikes scattered across the run — is the textbook signature of a queue
whose service rate is a hair below its arrival rate, not a periodic GC-pause fingerprint (which
would show slow outliers scattered evenly through the run, clustered around whenever collections
happen to fire). `achieved_tps=94.48` against a 100 tps target over 300s is consistent with that:
the system is running right at (or just under) its sustainable capacity for this long, so a small,
persistent (arrival rate − service rate) deficit compounds into a growing backlog over the full
5 minutes — a 30s test simply doesn't run long enough for that backlog to become visible. The
connection-pool warning (`requests.Session`'s default urllib3 pool size is 10, shared across all
16 crypto-calling worker threads) is a plausible contributor to a slightly-too-low service rate,
but wasn't confirmed as the specific cause — it could just as easily be cumulative memory growth or
GC pressure that this data can't distinguish from queueing on its own.

**Not yet done, worth trying next**: (1) time-bucketed p50 (not just top-10-slowest) to see
whether the whole run's latency ramps up smoothly or jumps at a specific point — would help tell
queueing-buildup and GC-pressure apart; (2) the same 300s test at a deliberately lower rate (e.g.
80-90 tps) to see if the effect disappears entirely, which would confirm "right at capacity edge"
over "GC/memory growth regardless of rate"; (3) bumping the crypto client's `requests` connection
pool size (`HTTPAdapter(pool_maxsize=...)`) to rule the pool-exhaustion warning in or out directly;
(4) the same test in Java, per the original ask, to compare GC behavior directly.

## Update — 2026-07-31, stress test part 2 continued: time-bucketed p50 + 80 tps control run

Added a `/latency_buckets?bucket_s=30` route to `router_py/simulators/upstream_host/main.py`, grouping
the same `(sent_offset_s, latency_s)` records `/slow_responses` already collects into fixed 30s
windows and reporting count/p50/max per window — this can tell a smooth queueing ramp apart from
scattered GC-pause spikes, which a top-10-slowest list alone can't. `stress_run.sh` now appends
this to `routers/latency_buckets.csv` after every run, alongside `slow_responds.csv`.

Then ran the same 300s soak test at a deliberately lower rate — **80 tps instead of 100** — as a
control, to test the "right at capacity edge" theory directly: if it's queueing buildup specific to
being at/above sustainable throughput, dropping the rate should make it disappear; if it were
GC/memory growth from processing a similar volume of messages over the same wall-clock time, it
should still show up, just perhaps delayed.

**Result — router_py, 80 tps target, 300s, same shared `crypto_host`:**

```
router_py;80;300;22820;22820;0;76.06;66.7;116.21;134.97;224.96
```

0 errors, p50=66.7ms, max=224.96ms — no collapse at all.

**Time-bucketed p50 (30s windows across the full run):**

| bucket start (s) | count | p50 (ms) | max (ms) |
|---|---|---|---|
| 0   | 2282 | 67.36 | 199.57 |
| 30  | 2282 | 66.47 | 159.43 |
| 60  | 2282 | 65.95 | 159.24 |
| 90  | 2284 | 66.42 | 144.96 |
| 120 | 2280 | 67.41 | 178.81 |
| 150 | 2285 | 71.17 | 224.96 |
| 180 | 2280 | 66.24 | 146.40 |
| 210 | 2283 | 69.36 | 187.10 |
| 240 | 2281 | 66.73 | 172.30 |
| 270 | 2281 | 62.76 | 144.67 |

**Completely flat across all ten buckets** — no ramp, no drift, p50 sits in a tight 63-71ms band
for the entire 5 minutes. The 10 slowest individual responses are scattered across the whole run
too (offsets at 0.6s, 2.5s, 5.5s, and a cluster around 153-158s — not concentrated at the tail like
the 100 tps run's were).

**This confirms the theory from the section above**: at 100 tps the system was running right at
(or just over) its sustainable capacity, so a persistent small deficit between arrival and service
rate compounded into a growing backlog that only became visible given enough wall-clock time. At
80 tps — comfortably under that same capacity — there's no compounding at all, flat latency for
the full 5 minutes, processing a similar total volume of messages (22,820 vs 28,345) over the same
duration. If this were GC/memory-growth-driven rather than a capacity-edge queueing effect, it
should still have shown up here, just perhaps later or milder — it didn't show up at all. That
rules GC out as the primary driver for router_py at these rates, at least at this timescale.

**Practical takeaway**: for router_py on this host, 80 tps is a genuinely comfortable, stable sustained
rate (flat p50 over 5 minutes); 100 tps is right at the edge and degrades badly given enough time,
even though the same rate looked perfectly clean over a 30s window. The actual sustainable ceiling
for a long-running router_py process on this host is somewhere between 80 and 100 tps, not simply "100
tps works" as the earlier short-burst testing suggested.

## Update — 2026-07-31, stress test part 2, Java: same measurements, same 80 tps control run

Ported the same instrumentation to `router_java`: `UpstreamHostMain` gained a `latencyRecords` list
(`{sentOffsetSeconds, latencyMs}` per completed round trip, mirroring router_py's `latency_records`) and
two new routes, `/slow_responses?n=10` and `/latency_buckets?bucket_s=30`, with identical JSON
shapes to the Python versions. `stress_run.sh` fetches both after every run and appends to the
same shared `routers/slow_responds.csv` / `routers/latency_buckets.csv` (implementation=`router_java`).
All 18 existing JUnit tests still pass.

**Result — router_java, 80 tps target, 300s, same shared `crypto_host`:**

```
router_java;80;300;22495;22495;0;74.98;53.49;94.38;106.61;1143.46
```

0 errors, p50=53.49ms — comparable to router_py's 66.7ms at the same target rate (Java's lower p50 here
is consistent with everything measured so far: no crypto/architecture bottleneck at this load, just
whichever runtime is faster at the actual work). The `max_ms=1143.46` initially looks alarming, but:

**Time-bucketed p50 (30s windows):**

| bucket start (s) | count | p50 (ms) | max (ms) |
|---|---|---|---|
| 0   | 2221 | 54.58 | **1143.46** |
| 30  | 2242 | 53.81 | 121.19 |
| 60  | 2250 | 53.53 | 120.04 |
| 90  | 2253 | 53.44 | 119.92 |
| 120 | 2253 | 53.39 | 133.16 |
| 150 | 2253 | 53.47 | 121.55 |
| 180 | 2255 | 53.37 | 119.58 |
| 210 | 2255 | 53.40 | 122.51 |
| 240 | 2256 | 53.40 | 127.55 |
| 270 | 2256 | 53.34 | 127.75 |

**Flat across all ten buckets**, p50 sitting in a tight 53.3-54.6ms band for the entire 5 minutes —
same conclusion as router_py at 80 tps: no ramp, no drift, no capacity-edge queueing.

The one outlier (1143ms) shows up in the slow-responses list too, and it's telling:

| rank | sent_offset_s | latency_ms |
|---|---|---|
| 1 | 0.020 | 1143.46 |
| 2 | 0.005 | 262.38 |
| 3 | 0.034 | 245.66 |
| 4 | 0.063 | 197.25 |
| 5-10 | 0.048-0.164 | 159.8-188.4 |

**All 10 slowest round trips happened in the first ~0.16 seconds of the run** — the opposite
pattern from router_py's 100 tps collapse (clustered at the *end*). This is a classic JVM warm-up
signature (JIT compilation/class-loading/first-connection overhead on the very first few
requests), not a GC pause and not a queueing ramp — a transient at the very start, then immediately
flat for the remaining ~300 seconds. Consistent with "no GC-driven degradation at this rate" for
Java too, just a different (and much shorter-lived) startup cost than Python's clean-from-sample-1
profile.

**Conclusion so far**: both router_py and router_java are comfortably stable at 80 tps over a 5-minute
sustained run, with no evidence of GC-driven degradation in either. router_py's problem was specific to
being right at its ~90-100 tps capacity edge; router_java hasn't been tested there yet (100 tps sweep
for Java over 5 minutes is a natural next step, to see whether it shows the same edge-of-capacity
signature router_py did, or holds up better/worse).

## Update — 2026-07-31, stress test part 2, C++: same measurements, 80 tps AND 100 tps

Ported the same instrumentation to `router_cpp`: `upstream_host_main.cpp`'s `SessionState` gained a
`latency_records` vector (`{sent_offset_s, latency_ms}` pairs, same shape as router_py/router_java) and two
new routes, `/slow_responses?n=10` and `/latency_buckets?bucket_s=30`. `stress_run.sh` fetches both
after every run into the same shared CSVs (implementation=`router_cpp`). 40/40 Catch2 assertions and
the functional `run_test.sh` end-to-end check both still pass after the change.

**80 tps, 300s:**

```
router_cpp;80;300;22651;22651;0;75.5;2.15;3.2;3.61;8.76
```

0 errors, p50=2.15ms. Time-bucketed p50 across all ten 30s windows: **2.11-2.26ms, dead flat**, max
never above 8.76ms in any window. The 10 slowest round trips are scattered essentially randomly
across the whole 300s (offsets at 5.7s, 211s, 69s, 119s, 223s, 161s, 6s, 30s, ...) — no clustering
at either end, unlike router_py's tail-clustering or router_java's head-clustering. This is the cleanest of
the three by a wide margin: no capacity edge, no warm-up transient, nothing to explain.

**100 tps, 300s** (run because C++ was already known from the original sweep to have real headroom
well above this rate — confirming that belief directly over a full 5-minute window rather than
just the 30s bursts tested earlier):

```
router_cpp;100;300;29285;29285;0;97.62;2.14;3.12;3.51;24.28
```

Still 0 errors, achieved_tps=97.62 (right at target), p50=2.14ms. Time-bucketed p50: **2.11-2.16ms
across all ten windows**, just as flat as the 80 tps run. One small, mild cluster in the
slow-responses list — 6 of the 10 slowest landed within a tenth of a second of each other around
the 73.6-73.9s mark (values 6.8-24.3ms) — but in absolute terms that's noise: even the worst case
(24.28ms) is barely above the ~2ms floor, nothing resembling the multi-second stalls router_py hit at its
own capacity edge. Confirms the belief directly: **router_cpp has real, comfortable headroom at 100
tps sustained for 5 minutes**, consistent with the original sweep's clean results up to 400 tps.

**Summary across all three implementations at 80 tps / 5 minutes**: no GC-driven or allocator-driven
degradation in any of them. router_py and router_java both show a startup/warm-up-scale transient (router_java's
literally is JVM warm-up; router_py didn't show one at 80 tps at all) but flat, stable steady-state
latency for the rest of the run. router_cpp shows no transient of any kind at either 80 or 100 tps —
the fastest and least eventful of the three, matching everything else measured in this
investigation.

## Update — 2026-07-31, stress test part 2: 10-minute passes attempted, invalidated by a real host OOM

Attempted a ~40-minute back-to-back sequence: router_java @ 100 tps/5min validation, then three
10-minute passes (router_py @ 80 tps, router_java @ 100-or-80 tps depending on the validation result, router_cpp
@ 100 tps) with a 2-minute idle cooldown between each pass. Goal: establish 100 tps as Java's
benchmark rate (pending the validation) and get real 10-minute steady-state numbers for all three.

**Validation (router_java @ 100 tps/5min) was clean**: `router_java;100;300;29011;29011;0;96.7;51.78;94.44;104.86;589.46`
— 0 errors, so 100 tps was selected as Java's 10-minute rate per the pre-agreed rule.

**All three subsequent 10-minute passes showed anomalies, of increasing severity as the sequence
went on:**

| phase | result line | anomaly |
|---|---|---|
| router_py @ 80 tps | `router_py;80;600;23963;23963;0;11.64;51.73;99.5;107.02;1751367.3` | buckets 0-270 (0-300s) completely clean (p50≈51.7ms); bucket 300 shows only 562 samples (vs ~2340 baseline) and **max=1,751,367 ms (~29 minutes)** |
| router_java @ 100 tps | `router_java;100;600;57371;57371;0;95.62;52.33;97.84;245.46;1639.79` | clean through bucket 420; bucket 450 (offset 450-480s) shows p50 jumping to 88.62ms, max=1639.79ms, then a 1-2 bucket recovery back to baseline by bucket 540 |
| router_cpp @ 100 tps | `router_cpp;100;600;58316;58316;0;93.06;10.43;10.74;10.87;168.9` | clean through bucket 210 (p50≈2.15ms); bucket 240 onward **permanently steps up to p50≈10.5ms** for the remaining 6 minutes of the run — a sustained regime change, not a transient |

**Root cause, found and confirmed, not host-swap-thrashing-in-general but a specific logged
event**: `dmesg -T` showed an actual kernel OOM kill:

```
[Fri Jul 31 16:01:24 2026] jcmd invoked oom-killer: ...
[Fri Jul 31 16:01:24 2026] Out of memory: Killed process 623 (MainThread) total-vm:19757908kB, anon-rss:317336kB, ...
```

16:01:24 falls inside router_java's 10-minute pass window, within seconds of its bucket-450 anomaly
(≈16:00:54-16:01:34) — a near-exact timing match. `free -h` at the time showed 96Mi free out of
2.8Gi and 834Mi of 1Gi swap in use. `ps aux --sort=-%mem` identified the actual memory hogs as
**IDE/tooling processes running alongside the test, not the router test scripts**: VS Code's
extension host (623MB), two separate Java language servers (257MB and 183MB, one with `-Xmx1G`),
several Claude Code session processes (336MB, 286MB, others), and dockerd — collectively consuming
most of the host's 2.8GB before any test load is added. `jcmd` (a JDK diagnostic utility, likely
invoked periodically by one of the VS Code Java extensions) triggered the failed allocation; the
kernel's OOM victim-selection killed an unrelated process based on footprint, not necessarily one
of the test scripts themselves.

**Conclusion: none of the three 10-minute-pass results above should be trusted.** They're not
findings about router_py/router_java/router_cpp — they're artifacts of this specific shared host running out of
memory mid-sequence, on top of an already-tight baseline dominated by IDE/editor tooling rather
than the test processes. The earlier 5-minute/80-tps results earlier in this document (all
measured in isolation, without this ~40-minute continuous-load context) are unaffected and remain
valid.

**Next step, handed off for manual execution**: `routers/run_soak.sh` (the same four-phase
sequence, self-contained; named `run_10min_soak_sequence.sh` at the time) and `routers/run_soak.md`
(the runbook; named `run_10_min_soak_sequence.md` at the time) were written so the user can run
this standalone from a plain WSL terminal, with the IDE and this session closed first to free the
memory the tooling was consuming. Once that run completes, its `csv_results/stress_results.csv` /
`csv_results/slow_responds.csv` / `csv_results/latency_buckets.csv` rows should be used in place of
this section's invalidated numbers.

## Update — 2026-08-01: soak sequence parametrized, p90 added, and a 1-minute sanity check

`run_soak.sh` (renamed from `run_10min_soak_sequence.sh` later the same day — see the renames/
cleanup section below) gained a `number_of_minutes` argument (default 10, cooldown between phases
is always `number_of_minutes / 5`) and now writes two additional outputs of its own,
`soak_results.csv` (full per-phase row) and `soak_summary.csv` (just p50/p90/p99), both
semicolon-separated with a comma decimal point. Getting p90 required adding it to
`upstream_host`'s `/stress_stats` endpoint and to each implementation's `stress_run.sh` result
row (inserted between p50 and p95) — `stress_test.sh`'s `stress_results.csv` header was updated
to match, so rows written before this change have one fewer column than rows written after.

A 1-minute (`./run_soak.sh 1`) sanity check of the new pipeline produced:

| impl | p50 | p90 | p99 | max |
|---|---|---|---|---|
| router_py | 51,59 | 92,44 | 107,01 | 124,46 |
| router_java | 52,26 | 93,63 | 105,18 | 276,27 |
| router_cpp | 2,39 | 2,96 | 3,66 | 10,37 |

**Confirms crypto_host is not a significant contributor to router_py/router_java's latency.**
crypto_host is the one component genuinely shared across all three (same container, same
OpenSSL-backed EMV validation call, phase-by-phase exclusivity so no cross-language contention).
If it were costing tens of ms per call, that cost would show up identically in the C++ round trip
too — but C++'s worst case across the whole minute is 10,37ms and its p99 is only 3,66ms, tightly
bounding what crypto_host (plus network plus C++'s own processing) can possibly cost. The ~90ms
gap between C++ and Python/Java, present all the way from p50 to p90, is therefore essentially
entirely inside the Python/Java router implementations themselves (interpreter/GC overhead,
threading model, dev-server framework), not the shared crypto path.

Caveat: single 1-minute sample per implementation, not repeated — Java's max (276,27ms) vs its own
p99 (105,18ms) hints at at least one outlier (GC pause, or the WSL2 clock-resync quirk noted
elsewhere in this repo's memory), so treat this as a strong directional read, not a final number.

## Update — 2026-08-01, housekeeping: renames and CSV output moved to `csv_results/`

Two administrative changes, no behavior change beyond output paths:

- `run_10min_soak_sequence.sh` → `run_soak.sh`, `run_10_min_soak_sequence.md` → `run_soak.md` (via
  `git mv`, history preserved). All in-repo references updated (this file, `divide_and_conquer_v2.md`,
  the three `build_router.md` specs, `the_routers.md`'s "Done" note).
- All output CSVs (`stress_results.csv`, `slow_responds.csv`, `latency_buckets.csv`,
  `soak_results.csv`, `soak_summary.csv`) moved from the repo root into `routers/csv_results/`, to
  keep the root clean. `stress_test.sh`, each implementation's `stress_run.sh`, and `run_soak.sh`
  all now `mkdir -p csv_results` before writing, so a fresh checkout doesn't need the directory
  pre-created.

## Update — 2026-08-01: router_cpp full-rebuild trap fixed, and a 2-minute soak confirms the earlier reading

Editing `router_cpp/stress_run.sh` for the `csv_results/` move (previous section) re-triggered the
full ~4-5 minute rebuild documented above ("router_cpp full-rebuild-on-any-edit trap"). Rather than
just re-noting it, fixed it: added `router_cpp/.dockerignore` allow-listing only what `make -j2`'s
default target actually needs to build (`CMakeLists.txt`, `src/`, `test/` — `test/` because the
default `make` target also builds the `xv6_tests` Catch2 binary). Everything else in `router_cpp/`
(docs, `stress_run.sh` itself, `monitor/`, `test_csv_files/`, `config/` — the last is
volume-mounted at runtime, not needed at build time) is now excluded from the build context.
**Verified**: edited `stress_run.sh` again, rebuilt — full cache hit, ~1.4s instead of ~250s.

Two other options were considered but not done (lower priority now that the immediate pain is
fixed): splitting the `cmake` configure/`FetchContent` step from the `make` compile step into
separate layers (so a genuine `src/` change wouldn't re-clone httplib/json/catch2 from GitHub), and
switching `router_cpp` to a persistent-container + `docker exec cmake --build` incremental-build
model, matching how `router_java`'s `stress_run.sh` already builds inside its long-lived container
via `docker exec ... mvn package` instead of a fresh image build every run.

Also ran a 2-minute (`./run_soak.sh 2`) soak, as a repeat of the 1-minute sanity check above:

| impl | p50 | p90 | p95 | p99 | max |
|---|---|---|---|---|---|
| router_py | 51,68 | 92,49 | 97,15 | 104,97 | 128,62 |
| router_java | 52,03 | 93,43 | 94,18 | 104,01 | 315,47 |
| router_cpp | 2,34 | 3,13 | 3,33 | 3,80 | 14,59 |

**Same conclusion holds, more solidly**: every percentile for all three implementations is within
noise of the 1-minute run (router_cpp's p50 2,34 vs 2,39; router_py's p90 92,49 vs 92,44; etc.),
so this isn't a single-minute fluke — crypto_host still isn't a meaningful contributor to
router_py/router_java's latency at 2x the sample size. router_cpp remains the standout: much more
implementation complexity (manual EBCDIC/ISO8583 codecs, explicit memory/thread management) buys a
genuinely large, consistent efficiency win — roughly 20-40x lower p50 than the other two, with a
worst case (14,59ms) still under router_py/router_java's *best* case (p50 ~52ms).

Also ran a 5-minute (`./run_soak.sh 5`) pass: same 0-error, 0-collapse picture for all three. C++
and Java both stayed flat against their 1/2-minute numbers (Java's p50 52,26→52,03→52,05, p90
93,63→93,43→93,45 — its elevated max was already present at 1 minute, a warm-up transient, not a
growth trend). Python drifted modestly: p50 51,59→51,68→52,79, p99 107,01→104,97→112,92, max
124,46→128,62→249,91 — small but consistent across every percentile, worth watching on a future
longer run rather than dismissing as pure noise, though nowhere near the multi-second collapse
seen at 100 tps in the original investigation.

## Update — 2026-08-01, housekeeping part 4: `test_csv_files/` consolidated to one master

Each implementation had its own `test_csv_files/test.csv` (byte-identical by luck/manual effort,
not by any enforced mechanism), and `stress_test.sh`'s default input CSV was `router_py`'s copy
specifically — an arbitrary choice with no reason to privilege Python's copy for a
all-three-implementations sweep. Consolidated: `routers/test_csv_files/test.csv` is now the single
master, `stress_test.sh` and `run_soak.sh` both read from it directly (`run_soak.sh`'s old
`CSV_REL` was a path relative to whichever implementation directory a phase had `cd`'d into,
resolving to *that* implementation's local copy — replaced with an absolute `CSV_FILE` pointing at
the root master, so all three phases now provably use the identical input regardless of copies
drifting). Each implementation's own local `test_csv_files/` still exists, unchanged, for that
implementation's own `run_test.sh` and its monitor UI's CSV dropdown (`GET /api/csv_files`, which
only ever reads that implementation's own directory) — new `routers/sync_test_csv.sh` mirrors the
master into all three on demand, so future CSV additions/edits have one place to make them and one
command to propagate them, instead of three copies to remember to keep in sync by hand.

## Update — 2026-08-01, housekeeping part 5: router_java's orphaned deploy scripts removed, monitor renamed

Auditing `router_java/`'s `.sh` files against what's actually referenced elsewhere turned up two
genuinely orphaned scripts: `start_deploy.sh`/`stop_deploy.sh` (+ `router_java/docker-compose.yml`)
built a separate `router_java-deploy` container that `build_router.md` still described as *"exists
specifically for... stress testing"* — but that's stale. `stress_run.sh` was checked directly and
confirmed to build/launch via `docker exec` into the plain dev container (`router_java`), not this
deploy container; no `router_java-deploy` container existed (`docker ps -a` confirmed), and nothing
else referenced these three files. Deleted all three, and removed the now-false "Deploy-style
container" section from `build_router.md`.

Also renamed `monitor_start.sh` → `monitor.sh`, matching `router_cpp`'s single-`monitor.sh` naming
(`monitor_stop.sh` kept its name and its pidfile-based-not-`pgrep`-based stop logic — that's a
deliberate, still-relevant safety fix, not something router_cpp's simpler Ctrl+C-to-stop model
needs to be matched to). Updated root `monitor.sh`'s dispatch and every doc reference
(`build_router.md`'s layout tree, monitor section, and glue-script safety checklist;
`monitor_stop.sh`'s own comment) accordingly. `router_java/build_router_java_container_v1.md` was
deliberately left alone — it's a frozen "(v1)" historical spec snapshot, same treatment as
`divide_and_conquer.md`'s chronological log elsewhere in this repo.

`router_java/` now has 8 scripts, all load-bearing: `start.sh`/`stop.sh` (dev-container lifecycle),
`dockerstart.sh` (used by both `router_java/start.sh` and root `start_docker.sh`),
`monitor.sh`/`monitor_stop.sh`, `run_test.sh`, `stress_run.sh`, and `terminal.sh` (manual
`docker exec -it` convenience, not referenced elsewhere but still a working, non-misleading tool).
