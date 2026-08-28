# auto correct
there is a mechanism built into the setup that ensures traffic is always there the (0800/0810) messages.
now what will happen is that actors fall out - and then come back - it is important that the router can cope with this.
We need a test suite for resilience - we will start in python - i.e. the test suite is orchestrated in pythan and if we find errors then we will correct them in router_py first - which is by far the fastest turnaround loop
## two upstreams
since it will also be interesting to have more than one upstream active we will have both upstream_1 and upstream_2 as active as the starting point for resilience tests - the test_resilience.sh script should contain all the test cases and report status on console but also in a test_resilience.csv file.
column A should be time, column b is actor and column c - what happened.
it is important to log when actors go down, when they come up again and when the first transaction have been sent/received

## test cases upstream fails
upstream_1 goes down - expect that ping traffic will continue on upstream_2
upstream_2 goes down - expect no traffic - which in the end probably will make downstream go down ? 
upstream_1 comes up again - expect that ping traffic should work again and for the sake of the argument send in the test.csv 
upstream_2 compes up againg - expect that ping traffic should work again and send in the test.csv 
## downstream fails.
what happens ? 

## crypto_host fails
send in a test.csv what happens. 

## Round 1 results (2026-08-02)

Implemented as `router_py/test_resilience.py` (orchestrated in Python, per above) with a thin
`router_py/test_resilience.sh` wrapper, logging to `router_py/test_resilience.csv`
(timestamp;actor;event). Reuses `monitor/main.py`'s existing actor lifecycle helpers
(`launch_actor`/`stop_actor`/`is_running`/`wait_for_ready`) to do real kill+restart of actor
processes - not an in-process fake. Pause/resume (SIGSTOP/SIGCONT, simulating a silent hang
instead of a clean disconnect) is a deferred follow-up variant, not implemented yet.

Observed against a live run:
- **upstream fails**: confirmed as expected - upstream_1 down leaves upstream_2's ping traffic
  advancing; both down leaves downstream_host's counters simply idle (no crash); both coming back
  up reconnect and round-trip test.csv cleanly.
- **downstream fails**: both routers' `connections.downstream` flips to `false` while
  `connections.upstream` stays `true` - no crash or cascade. Router auto-reconnects within its
  `reestablish_seconds` window once downstream_host is back, and test.csv round-trips normally
  again.
- **crypto_host fails**: `CryptoClient`'s circuit breaker opens after 5 consecutive failures (as
  designed) and closes again after `breaker_cooldown_seconds`. **Open question / needs review**:
  while the breaker is open, the PAN that needs a real crypto ARPC response
  (`9999999999999999`) comes back with `resp_47.response_code` degraded to `"01"` instead of the
  expected `"14"` - i.e. a transaction that should indicate "crypto unavailable" instead reads as
  a different, valid-looking response code. Not yet decided whether this degraded value is
  acceptable fallback behavior or a bug to fix in `router_py` before this pattern is ported
  anywhere else.

## Round 2 (2026-08-07) - stuck-transaction / session-teardown scenario

Added `scenario_stuck_pending_on_downstream_teardown` to `router_py/test_resilience.py`, found
while building the live-diagnosis tooling in `briefs/old/debug_trace_master.md`. Not the SIGSTOP
pause/resume variant Round 1 flagged as deferred (that one simulates a silent hang and turned out
racy to script deterministically - the router's own reconnect/liveness logic races with it in ways
that are hard to pin down from outside). This is a plainer, deterministic case: hold a raw upstream
client connection open, send one transaction, confirm it's genuinely stuck in `router_1`'s pending
map (`GET /pending`), then kill `downstream_host` outright with the transaction still in flight.

**Bug found + fixed**: `Dispatcher.drain_and_stop()` (called on every session teardown - upstream
disconnect, downstream disconnect, reconnect) never touched `_pending` at all - any transactions
in flight at the moment of teardown were silently abandoned, no log line, nothing - unlike
`purge()`, which explicitly reports `dropped_pending`. Not a correctness bug (there's no valid
recipient left for a decline once the client - or, in this scenario, downstream - is gone), but a
pure observability gap: someone diagnosing "where did transaction X go" would have found nothing
explaining it vanished at session teardown. Fixed to log one WARNING per abandoned STAN plus a
summary count, and clear `_pending`. Covered by both a unit test
(`test_drain_and_stop_logs_and_clears_abandoned_pending` in `test_dispatcher_resilience.py`) and
this live scenario.

**TODO when porting resilience testing to `router_java`/`router_cpp`**: check whether their
equivalent session-teardown path has the same silent-drop gap (near-certain, since they're
separate hand-ported copies of the same architecture) and add the same fix + scenario there.

## Round 3 (2026-08-22) - resilience_v2.md: SSL cert-desync ERROR logging, chaos-monkey script

Two deliverables from `briefs/resilience_v2.md`: certs going out of sync between two sides of a
connection can't self-heal by retrying and must log as ERROR (done, see below); and a
Netflix-chaos-monkey-style destructive script that randomly kills actors against live traffic and
verifies the router gets itself back on track (excluding the cert case, which needs a human).

**Cert-desync ERROR logging - done.** `router_py/router/downstream.py`'s
`DownstreamConnection.connect()` and both `UpstreamClient.connect()`/`UpstreamServer.accept()` in
`router_py/router/upstream.py` now catch `ssl.SSLError` specifically and log ERROR ("certificates
may be out of sync... needs manual intervention") instead of falling into the generic
WARNING-and-retry path used for ordinary connectivity flapping - previously `UpstreamClient.connect()`
didn't even log at all on a handshake failure. Covered by 3 new tests (`tests/test_downstream.py`,
new `tests/test_upstream.py`) doing a real TLS handshake with a deliberately mismatched CA, not
mocked.

**TODO - cert-desync attack for the chaos-monkey script, deferred pending design.** The unit tests
above validate the exception-handling path is correct, but the mismatched-CA setup used to trigger
it isn't necessarily how a *real* desync would happen: each leg (upstream/downstream/crypto) already
uses its own independent self-signed cert/CA pair by design (confirmed in `router_1/config_perf.json`
- `upstream_router_1_*`, `downstream_*`, `crypto_host_*` are three unrelated pairs, never meant to
match each other). So "give the downstream leg crypto_host's CA" (what the unit tests do) isn't a
realistic simulation of a production desync - a real one would be *within* one leg, e.g.
downstream_host's cert gets regenerated but the router's `downstream.cafile` still points at the old
one. Confirmed while thinking through this: `shared/ssl_utils.py`'s `wrap_client_socket`/
`wrap_server_socket` build a fresh `SSLContext` (fresh `load_cert_chain`/`load_verify_locations` off
disk) on *every* connection attempt - no caching - so a chaos-monkey attack that swaps a leg's own
cert file on disk would be picked up on the very next reconnect attempt with no actor restart
needed. Design not yet finalized - resume before adding a cert-desync attack type to
`chaos_monkey.py`. The other attack types (killing crypto_host/downstream_host/router/upstream at
random) don't have this problem and are being built first.

## Round 4 (2026-08-22) - chaos-monkey's first real run: two teardown races found + fixed

First actual `chaos_monkey.py` run (10 rounds, random kill/restart of crypto_host/downstream_host/
router_1/upstream_1) surfaced real bugs, not just validated the script: 8/10 recovered.
`downstream_host` failed its one attack outright (0/3 rows); `crypto_host` failed 1 of 4
intermittently with `[SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC]` on the router's downstream *and*
upstream sockets simultaneously - suspicious, since crypto_host is a third, unrelated connection.

Root-caused by reproducing both in isolation with per-actor stdout captured to files and
`router_1`'s `log_level` temporarily bumped to `DEBUG` (reverted after - not left permanent, unlike
the two `logger.debug()` lines below). Two distinct, compounding bugs, both in the router-to-
upstream_1 leg's teardown/reconnect path:

**Bug 1 - `router_py/router/session.py`'s `RouterSession._teardown()`.** When `downstream_host`
dies, the router tears down the whole session, including its connection to `upstream_1`. That
teardown did a bare `conn.close()` - unlike `DownstreamConnection.close()` (Round-1-era fix, see
that class's own comment), which already does `shutdown(SHUT_RDWR)` first specifically because a
bare `close()` from one thread doesn't reliably interrupt another thread blocked in a `recv()` on
that same socket. The up-server thread is exactly that other thread here (blocked in
`read_upstream()` inside `_handle_upstream`). Confirmed directly: with temporary `logger.debug()`
breadcrumbs around `_teardown()`, `up_thread.join(timeout=5)` timed out with the thread still
alive, and `upstream_1` didn't learn its connection was gone for 15-17 seconds - well past the
point where the *next* reconnect attempt needed it torn down. Fixed by adding the same
shutdown-before-close `DownstreamConnection.close()` already uses. The two `logger.debug()` lines
that pinned this down stay in permanently (cheap - lock-free `is_alive()` check, lazy `%s`
formatting, no cost with DEBUG off) for next time.

**Bug 2 - `upstream_host/main.py`'s `_send_loop`/`_keepalive_loop` (shared file - used by
router_java/router_cpp too, not router_py-local).** These capture `conn` once per batch/loop and
keep writing to that same Python socket object with no re-validation. When the connection dies
mid-batch (exactly what Bug 1 was causing) and `_client_connect_loop` reconnects, Linux reuses the
just-freed fd number almost immediately for the new socket - and the old `_send_loop`'s next write
lands on that reused fd. Caught directly with temporary print-tracing:
`OSError stan=000005: [Errno 9] Bad file descriptor` - the exact symptom
`DownstreamConnection.close()`'s comment already named as this bug class's signature, just not
previously found on this leg. Fixed by (a) re-checking `conn is self._get_conn()` inside
`_write_lock` immediately before each write in both `_send_loop` and `_keepalive_loop`, and (b)
moving `_run_connection`'s `shutdown()`+`close()` inside that same `_write_lock`, so a close can
never land mid-write on a socket a send is still using, and a send can never proceed once its
socket has already been superseded.

**Validation**: pre-fix, an isolated `downstream_host`-only attack loop reproduced 0/10 clean
recoveries (every round: 0/3 rows). Post-fix: 10/10 clean on that same isolated loop, and 10/10 on
a full mixed `chaos_monkey.py` run across all four targets.

**Not fully closed**: one `DECRYPTION_FAILED_OR_BAD_RECORD_MAC` occurrence surfaced once *after*
both fixes, same signature as the original intermittent `crypto_host`-round failure, on a
freshly-established upstream connection that died ~162ms after connecting. Did not reproduce again
over 10 further rounds. Likely the same race family (a stale thread from a superseded connection
generation touching a socket/fd that's since been reused) but not pinned down with the same
certainty as Bugs 1/2 above - worth a closer look if it recurs in a future run.

**TODO when porting resilience testing to `router_java`/`router_cpp`**: `upstream_host/main.py`'s
fix (Bug 2) already covers all three implementations since it's the shared actor. Bug 1's fix does
not - it's in `router_py`'s own `session.py`. Check whether `router_java`/`router_cpp`'s equivalent
session-teardown path closes its upstream connection the same bare way (near-certain, same
hand-ported-copy reasoning as Round 2's TODO) and apply the same shutdown-before-close fix there.

## Round 5 (2026-08-22) - chaos_slow.py (long-outage scenarios) + a false-positive ERROR fix

**New script: `router_py/chaos_slow.py`.** `chaos_monkey.py` only ever holds an actor down for
3-15s (random per round) - too short to say anything about a *long* outage, which behaves
differently in a few ways (e.g. `CryptoClient`'s breaker opening and re-arming multiple times
rather than just once). Two fixed scenarios, reusing `chaos_monkey.py`'s hard-kill/actor-lifecycle
helpers and `test_resilience.py`'s I/O helpers rather than duplicating either: (1)
`downstream_host` - 10s of smooth traffic, then a hard kill held down a full 2 minutes, confirming
the *normal* reconnect loop (no special "long outage" handling exists, nor should it need to)
brings everything back once `downstream_host` is actually back; (2) `crypto_host` - hard-killed and
held down 2 minutes while test traffic keeps flowing through every 10s, confirming transactions
keep round-tripping degraded (unenriched `f47`) once the breaker opens, rather than stalling.
Both scenarios poll `router_1`'s `/stats` every 10s during the outage and log
`connections`/`queue_depth`/`response_queue_depth`/`pending_count`, so the two-minute windows show
up as real data in the console/CSV, not a silent gap. First run: 2/2 scenarios PASS.

**Bug found + fixed - false-positive cert-desync ERROR.** That first `chaos_slow.py` run logged one
`ERROR`: `"TLS handshake failed accepting upstream connection ... certificates may be out of sync
... needs manual intervention"`, but the underlying exception was
`[SSL: UNEXPECTED_EOF_WHILE_READING]` - `upstream_1` reconnecting after `downstream_host`'s outage,
not an actual cert mismatch. Round 3's `except ssl.SSLError` classification (all three sites:
`DownstreamConnection.connect()`, `UpstreamServer.accept()`, `UpstreamClient.connect()`) treated
*every* `ssl.SSLError` as a desync, but that class also covers `SSLEOFError` (peer's TCP connection
dropped mid-handshake - a stray probe, a reconnect race) and `SSLZeroReturnError` (a clean TLS
shutdown), neither of which is a cert problem. Given the explicit goal of zero known errors even
under chaos, this needed fixing rather than living with an occasional false alarm.

Fixed by adding `is_cert_desync_error()` to `shared/ssl_utils.py`: `True` only for
`ssl.SSLCertVerificationError`, or a plain `SSLError` whose `reason` carries an actual
cert-related OpenSSL marker (`CERTIFICATE_VERIFY_FAILED`, `UNKNOWN_CA`, etc.); `False` for
`SSLEOFError`/`SSLZeroReturnError` and any other non-cert alert. All three call sites branch on
this now - a real desync still gets `ERROR`, everything else falls back to the pre-Round-3
`WARNING`-and-retry behavior (or stays silent where the caller already logs once, so the non-cert
case doesn't end up double-logged).

**Validation**: all 4 existing cert-desync unit tests still pass unchanged (a real mismatched-CA
setup still correctly hits `ERROR`) - full suite 48/48. Direct classifier check against real
`SSLEOFError`/`SSLZeroReturnError`/`SSLCertVerificationError`/unknown-CA-alert instances matches
expectations. Reran the exact scenario that produced the false positive: a 10-round isolated
`downstream_host` chaos loop and a 12-round full mixed `chaos_monkey.py` run (all four targets)
both came back with **0 `ERROR` lines** across every actor, alongside 10/10 and 12/12 clean
recoveries respectively.

## Round 6 (2026-08-27) - resilience_v2.md: crypto response no-reply, "build up a queue"

Brief's own framing: crypto_host validates fine on a transaction's request leg (0100) but never
answers on its response leg (0110), so the router's reply to upstream never arrives - "my
expectation is we will stop reading upstream at some point but let's see." Built as PAN-targeted
(user's own steer, mid-session: "ok to make an entry in crypto_host so a specific card number
gives error on 0100 or 0110" / "error like 'no response'"), not a global toggle, so ordinary
traffic on every other PAN is completely unaffected.

**Built**: PAN `8888888888888888` added to `pans_defined.json` (provisioned normally, so
`validate_0100` and downstream_host's own PAN check both pass). New `no_response_pans` map in
`simulators/crypto_host/config.json` (`{"8888888888888888": ["validate_0110"]}`), read by
`simulators/crypto_host/main.py`: a matching `(pan, operation)` request logs a WARNING and then
blocks the handler thread forever (`threading.Event().wait()`, never `.set()`) instead of
returning - a real "no response," not a fast HTTP error, so `CryptoClient`'s own 5s socket
timeout is what actually decides what happens next, twice per call (`_send()`'s single retry-on-
failure also lands on the same hang). **Had to add `threaded=True` to the stub's `app.run()`**
first - Flask's dev server defaults to one request at a time, so without it a single hung request
would have stalled crypto_host for *every* PAN/operation, not just the targeted one; verified via
a direct concurrent-call test that a normal-PAN `validate_0100` alongside a hung chaos-PAN call
stayed fast (0.1s) once threaded. New scenario `scenario_crypto_response_no_reply_queue_buildup`
in `test_resilience.py`: drives 10 TPS of chaos-PAN-only traffic for 180s (a dedicated one-row
`test_csv_files/chaos_no_response.csv` cycled via upstream_1's `/start?rate=&duration=` stress
endpoint - the same mechanism `stress_run.sh` uses) while polling `router_1`/`upstream_1` stats
every 10s, then a plain-`test.csv` recovery check.

**Result: the router never stopped reading upstream.** `queue_depth` (the 0100/upstream-facing
queue) stayed at 0 for the entire 180s and `connections.upstream` never flipped false -
`upstream_1`'s `sent` counter climbed at a steady ~10/s the whole time, un-throttled. Traced why
before trusting the number: `_response_queue` and the 0100-side `_queue` are fully independent
(separate queues, separate thread pools, separate sockets in `session.py`), so backpressure on the
response leg has no path back to the upstream-read loop in this architecture - confirmed live, not
just by reading the code.

**What actually did happen - `_response_queue` backlog self-limited instead of growing to
`queue_maxsize`.** It built fast at first (0 -> ~339 in the first ~50s: arrivals at 10/s vastly
outpacing the ~8-worker capacity), then plateaued around 300-340 for the rest of the run and never
came close to the 1000 ceiling. Root cause, confirmed directly against the live logs: the
existing `pending_ttl_seconds=30` reaper doesn't know or care *why* a transaction is slow - once
`_response_queue` backlog means an item waits >30s just to reach a free worker, the reaper expires
its `_pending` entry and fires a synthetic local decline (`"39": "91"`) straight to upstream before
a response worker ever gets to it. When that worker finally dequeues the (now-orphaned) real 0110,
`handle_response()`'s `_pending.pop()` finds nothing, logs `no pending entry for router_stan X`,
and returns immediately - no crypto call, no ~10s hang. This run: exactly 1212 "expired ... sending
local decline" lines paired 1:1 with 1212 "no pending entry" lines (confirmed matching counts),
against only 284 requests that actually reached crypto_host and paid the full ~10.05s hang (timed
directly, both an isolated single call and an 8-concurrent-call reproduction independent of the
live run land on the identical ~10.05s). Net effect: of `upstream_1`'s 1478 received responses,
**82% (1212) were timeout-declines, not real answers** - but upstream got *a* reply to every send
either way, which is exactly why its read loop, and the router's, never had reason to stall.
Post-attack recovery: ordinary `test.csv` round-tripped 3/3 immediately.

**Read on this**: not a bug to fix - the 30s pending TTL doing its job (bounding upstream-visible
latency under a stuck backend) is arguably *why* nothing worse happened, and matches how a real
payment network timeout convention would behave. The brief's expectation ("stop reading upstream")
doesn't hold for this architecture specifically because the two legs' queues/threads/sockets are
already fully decoupled - a design property, not an accident, confirmed live rather than assumed.
**Known caveat, not fixed**: the chaos hook's `threading.Event().wait()` never returns, so
crypto_host itself leaks one permanently-blocked Werkzeug thread per genuinely-hung call (284 in
this one run) - harmless for a single scenario run since the whole process gets torn down after,
but would need a bound (or an explicit `.set()` at actor shutdown) if this hook is ever reused for
a longer or repeated run.

## Round 7 (2026-08-27) - resilience_v2.md: crypto response leg, fire-and-forget under real TPS

**TL;DR**: `validate_0110` (response leg) now uses its own short-timeout `CryptoClient`
(`crypto_response_timeout_seconds`, 0.2s here / ~50-75ms real-world) instead of sharing the request
leg's 5s one - a stuck card now fails in ~0.4s, not ~10s. Which cards are bad lives as plain test
data in `upstream_host` (`tps_10pct_bad_card.csv`), not as logic inside `crypto_host` - keeps
`crypto_host` a dumb PAN lookup, portable to its eventual C++ port. Verified live at 100 TPS with a
realistic 10%-bad-card mix: send rate holds (~96 TPS), any backlog that builds is transient (a
462-item backlog drained in 5s; the full-run backlog drained in 8.1s) - not a stall. Along the way,
found and fixed a real bug in the *test scenario itself* (a misleading PASS from checking send-rate
alone) before trusting any of the above. `router_py` only - not yet ported to `router_java`/
`router_cpp` or the real shared `crypto_host`, see the open question at the end of this round.

Follow-up to Round 6's "let's look at what happens in the real world": most transactions won't hit
a stuck crypto response, but a realistic slice will (brief's own stress figure: 10%, "which is a
very high number") - and the router should still sustain its target TPS rather than let a slow
backend throttle upstream traffic. The brief's key insight: once downstream has already answered,
crypto enrichment on the response leg (`validate_0110`) isn't gating anything any more - "no one
cares about the result anymore" - so it should be fire-and-forget with a short timeout, unlike the
request leg (`validate_0100`), which still genuinely gates whether to forward a transaction at all
and has to stay a real blocking call.

**Design change, `router_py`:** `CryptoClient` (`router/crypto_client.py`) now takes a
`timeout_seconds` param instead of a hardcoded 5s. `router/session.py` builds **two** instances per
session - the request leg keeps the old 5s default; the response leg gets a new
`crypto_response_timeout_seconds` (`router/config.py`, default **0.2s** on this laptop, brief's own
real-world estimate is 50-75ms) - and `Dispatcher` (new optional `crypto_response` param, defaults
to the single `crypto` client when omitted so every existing test/caller is unaffected) routes
`validate_0110` through it. Verified in isolation before touching the live topology: a response-leg
call against a permanently-stuck card now fails in ~0.42s (one attempt + `crypto_client.py`'s
existing single retry-on-failure), down from the old ~10s.

**Redesigned mid-session per user steer - chaos stays PAN-based, not probabilistic, and moves out
of `crypto_host`.** First pass armed a live `no_response_probability` toggle *inside* the
`crypto_host` stub (`{operation: probability}`, live-armed via a new `/chaos` route) to simulate "a
random 10% of all traffic." User's correction: "I don't want the failure probability in the
crypto_host - just let it sit in the upstream_host which is the simulator... the crypto_host we
will later implement in cpp - and it basically just needs to know this F002 (pan - card number)
should not work and the others should." Real-world crypto_host is deterministic per card, not a
dice roll - which cards are bad, and how many, is a property of the *traffic*, not the validation
service, and needs to stay trivially portable to the eventual C++ port (a dumb PAN lookup, nothing
else). Reverted the probability/`​/chaos` additions entirely; kept Round 6's existing PAN-keyed
`no_response_pans` mechanism unchanged. The 10% now lives as plain test data:
`test_csv_files/tps_10pct_bad_card.csv` cycles 9 good-card rows against 1 row of the existing
Round-6 chaos PAN (`8888888888888888`) - no new upstream_host code needed, "sits in upstream_host"
literally as the traffic mix it drives.

**New scenario**, `scenario_crypto_response_fire_and_forget_sustains_tps` in `test_resilience.py`:
sustained `TPS_TARGET` (100) TPS on that 9-good/1-bad mix for 60s, polling `router_1`/`upstream_1`
every 10s.

**Bug found in the scenario itself, before trusting any result: a misleading PASS.** The first
live run reported `achieved_tps=95.58` and a green verdict, while `response_queue_depth` and
`pending_count` had both climbed past 1000 during the run and the post-attack recovery check
(upload+send `test.csv`, 15s poll) came back **0/3**. Root cause: `achieved_tps` only measures
upstream's own *send* rate, which never blocks on replies by design (see `upstream_host/main.py`'s
`_send_loop`) - a healthy send rate proves nothing about whether responses keep pace. Fixed the
verdict logic to check both independently: send-side `achieved_tps` (proves sending wasn't
throttled) and a proper drain-poll of `queue_depth`/`response_queue_depth`/`pending_count` after
the attack (up to `TPS_DRAIN_TIMEOUT_S`=60s) before attempting the recovery `test.csv`, instead of
one fixed-timeout send that races an unrelated backlog it has to queue behind.

**Then had to work out whether the backlog itself was a stall or just slow, before trusting *that*
either.** Two live 60s runs (one with the chaos hook's server-side bound at the original 10s, one
after shortening it to 2s - see below) both built a real backlog (`response_queue_depth`/
`pending_count` past 1000-1700) that the old 20s-total recovery check couldn't see through - looked
identical to a genuine stall from the outside. Isolated the real cause with a battery of direct
`CryptoClient`-only throughput tests against the live `crypto_host` stub (bypassing the router
entirely): a clean 0%-bad-PAN run sustains **~194/s**; a 10%-bad-PAN mix, *measured with threads
properly joined instead of killed mid-flight*, sustains **~133/s** - both comfortably above the
~96-100 TPS needed. An earlier, sloppier version of the same test (killing `crypto_host` while
daemon threads were still mid-call) had shown spurious `Connection refused`/`reset` errors and a
much lower ~81-91/s, which sent the investigation down a wrong path for a while ("the stub can't
sustain the connection churn") before rerunning it cleanly disproved that theory. Real cause of the
backlog: the response leg's `CryptoClient` circuit breaker (shared `breaker_threshold=5`/
`breaker_cooldown_seconds=30`, same defaults as ever) trips and un-trips under a bad-card mix -
consecutive-failure counting isn't diluted here the way Round 6's mixed 0100/0110 traffic diluted
it, since *only* `validate_0110` calls land on this client - making throughput genuinely bursty
(a burst of 8-worker-thread-wide fast short-circuited calls once open, versus the normal ~0.4s-per-
bad-call cost once closed) rather than smooth, which is enough on its own to build a real backlog
during a sustained run without any resource exhaustion involved.

**Confirmed the backlog drains rather than stalls with a dedicated test**, isolated from the
scenario's own recovery-check logic: a shorter 30s burst built a 462-item `response_queue_depth`/
`pending_count` backlog, then **drained to 0 within 5 seconds** of traffic stopping. This is what
actually explains the earlier "0/3 FAIL" runs - both queues are FIFO, so `test.csv`'s 3 new rows
had to wait behind whatever backlog (up to ~1700 items) the full 60s run had built, and 20s total
wasn't long enough to see that queue drain - not evidence the router got stuck.

**Final clean run, corrected scenario code, quiet host** (see below): send-side `achieved_tps=96.06`
(PASS, >=95% of target); `response_queue_depth`/`pending_count` sat at 0-1 for the first ~35s of
the run (`errors`, upstream's sent-received gap, stayed at 7-8 - essentially real-time round-
tripping) with one bursty build-up late in the run (breaker-timing dependent, as diagnosed above) -
backlog drained in 8.1s once the attack ended, and `test.csv` round-tripped 3/3 immediately after.
Both the send-side and drain/recovery verdicts genuinely PASS this time, not just on paper.

**Host-load confound, worth naming explicitly.** The very first end-to-end run (with the
since-reverted probability mechanism) showed `queue_depth` - the 0100/*upstream*-facing queue,
which every other run in this round left completely untouched at 0 - pinned at 1000 the entire run,
which would have been the brief's own predicted "stop reading upstream" outcome. That run coincided
with this laptop sitting at ~2.3/2.8GB RAM used (VSCode's Java language server + NetBeans running);
after the user closed those (1.7GB free confirmed via `free -h` before the re-run), `queue_depth`
never became a factor again in any subsequent run in this round. Not chased further/re-tested in
isolation given the redesign superseded that run anyway, but flagged rather than silently dropped -
if `queue_depth` (not just `response_queue_depth`) pins under load in a future run, check host
memory pressure before assuming it's the response-leg fix's fault.

**Shortened the chaos hook's server-side bound, 10s -> 2s** (`simulators/crypto_host/main.py`):
didn't turn out to be the actual fix for the backlog (that was the breaker dynamics above), but a
real, independent improvement - at real traffic volume the original Round-6-era 10s bound let far
more concurrently-stuck threads/sockets accumulate on `crypto_host` than a single-test-PAN run ever
would, and 2s is still 5x the response leg's own worst-case ~0.4s client timeout, so it changes
nothing from the caller's perspective.

**Validation**: full suite 50/50 (48 existing + 2 new - `test_response_leg_uses_crypto_response_client_when_given`
and `test_dispatcher_defaults_crypto_response_to_crypto_when_omitted` in
`test_dispatcher_resilience.py`, covering the dual-client wiring and its backward-compatible
default). `test_csv_files/tps_normal_traffic.csv` (an intermediate, now-superseded file from the
reverted probability design) removed; `test_csv_files/tps_10pct_bad_card.csv` is the file the final
scenario actually uses.

## Round 8 (2026-08-28) - resilience_v2.md: 0120/0130 advice and 0400/0410 reversal

**TL;DR**: real ISO 8583 doesn't wait forever for an authorization reply - a timed-out 0100 gets
both a 0420 (reversal, "forget it") and a 0120 (STIP advice, "here's the decision I made for the
cardholder") independently, each store-and-forward retried (geometric backoff, x15, up to 5 times)
until acknowledged or logged as failed. Turned out to be entirely `upstream_host`-side work -
`router`/`downstream_host` already had the plumbing for this, unused, from earlier scaffolding.
Built and verified against a new permanent test fixture (`tests/stub_router.py`) that drives
`UpstreamHostSim` in full isolation with real `iso8583` wire encoding, not a mock.

**Discovery before writing anything**: checking the brief's requirements against the existing code
found most of the round-trip already wired and simply never exercised. `session.py`'s upstream-read
loop already dispatches `"0100", "0120", "0420"` into the same request path, and `dispatcher.py`'s
`_RESPONSE_MTIS = ("0110", "0130", "0430")` already treats 0130/0430 as response-type messages
routed straight back upstream. `_process()` only calls `crypto.validate("validate_0100", ...)` when
`mti == "0100"`, and `handle_response()` only calls `validate_0110` when `mti == "0110"` - so
0120/0420 and 0130/0430 already skip `crypto_host` entirely, exactly as the brief requires ("no
crypto on 0400/0410 and 0120/0130... this was actually the original culprit in our faked
scenario"). `downstream_host/main.py`'s `_route_frame()` already handles `0120→0130` and
`0420→0430` as a plain echo with the MTI (and, implicitly, field 39) changed. None of this needed
touching.

**0400 vs 0420, resolved without adding anything new.** The brief asked for 0400/0410
specifically, but the code already had 0420/0430 wired the same way. User's clarification: the
real-world difference is 0420 is store-and-forward (upstream keeps resending until acknowledged)
while 0400 is a one-shot request - "for this exercise we can treat 0400 and 0420 as the same...
not all actors in the real world actually implement both." Decision: use the existing 0420/0430
wiring as-is, build the store-and-forward retry behavior into it, and never introduce 0400/0410 at
all - avoids duplicating two functionally-identical MTI pairs for this simulator's purposes.

**Design, settled over several rounds of back-and-forth before writing code:**
- On a 0100 with no 0110 within `advice_timeout_seconds`, upstream_host fires **both** a 0420 and
  a 0120, independently - not one or the other based on any decision criterion. 0420 means
  "forget my 0100, no decision was made." 0120 means "I took this decision (yes or no) on your
  behalf, so you know if the cardholder calls you" - always carries an outcome, whereas 0420 never
  does.
- Both are store-and-forward: resent until acknowledged (0430/0130 respectively) or
  `advice_max_retries` (5) is exhausted, at which point logged to `error_0120_0420.csv` and
  dropped.
- Retry backoff is **geometric, multiplier 15**, not the doubling first proposed: `1, 15, 225,
  3375, 50625` seconds. First interval (1.0s, "close to real life" per the user) is
  `advice_timeout_seconds` itself - the delay before the *first* 0420/0120 is even sent, once
  upstream gives up on the 0110. Every interval after that is 15x the previous one. Full
  exhaustion (5 retries) spans roughly 14 hours real-time at the production default - accurate to
  a real store-and-forward queue, but obviously not something to run end-to-end live in this
  session; `advice_backoff_multiplier` is a config value specifically so tests can override it
  ("play with smaller amplifiers in your testing... then I can run with the 15 on my
  soak_resilience_runs").
- STIP's own decision logic (`_stip_decision()`) always approves - this is a resilience-test
  simulator, not a real risk engine, and no approve/decline criteria were specified. Kept as its
  own one-line method so a future scenario can override it without touching the timeout/retry
  machinery around it.

**Implementation, `upstream_host/main.py` only** - no router or downstream_host changes needed,
confirmed by the discovery above. New state: `advice_pending` (STAN-keyed, separate from the
existing `pending` dict - these carry no crypto/latency/results semantics of their own, just "did
this get acknowledged"), each entry a fresh STAN from the same counter `pending` uses (not the
original 0100's STAN - it's a genuinely new message needing its own request/response pairing).
Two new background loops per connection (matching the existing `_keepalive_loop` pattern):
`_advice_timeout_loop` watches `pending`/`send_times` for entries older than
`advice_timeout_seconds` and fires `_start_advice()` twice (0420, then 0120 with the STIP
decision in field 39) for each one; `_advice_retry_loop` resends anything past its
`next_retry_at`, or logs+drops it once `advice_max_retries` is exhausted.
`_receive_loop` now falls back to checking `advice_pending` before logging "no pending request
for STAN" when a STAN isn't found in the ordinary `pending` dict - that's how 0430/0130 acks get
matched and cleared. Small DRY refactor along the way: `_send_loop`'s and `_keepalive_loop`'s
near-identical "check conn is still current, write under `_write_lock`, handle `OSError`" blocks
became one shared `_write_frame()`, which the new advice loops reuse too instead of a third copy.

**New permanent test fixture, `tests/stub_router.py`** - the user's own call mid-session ("maybe
stub router is a thing to keep in the permanent toolkit for python") after an ad-hoc version of it
proved out the design faster and more deterministically than orchestrating the real
crypto_host/downstream_host/router stack would have. `StubRouter` is a minimal, fully
test-controlled stand-in speaking the same wire protocol (real `iso8583` encode/decode, not a
mock) with a per-MTI `reply_policy` a test can flip to black-hole specific message types on
demand. `tests/test_advice_reversal.py` (3 new tests, small amplifiers - 0.3s timeout, x2 backoff,
not the 1.0s/x15 production default, so a full exhaustion cycle takes ~7s instead of ~14 hours):
healthy 0100/0110 never triggers any advice traffic (no false positives); a timed-out 0100 fires
both 0420 and 0120, both correctly acknowledged; an unacknowledged pair exhausts its retries and
lands in `error_0120_0420.csv` with the expected columns. One real bug caught building the last of
these three - not in the implementation, in the test itself: the poll loop checked "is
`advice_pending` empty" starting at t=0, before the messages had even been sent, so it broke out
immediately (trivially true) instead of waiting for the full cycle - fixed to first wait for
`advice_pending` to become non-empty, confirming the cycle actually started, before waiting for it
to empty again.

**Live-verified against the real stack with a genuine timeout, not just healthy traffic - user's
own steer on how.** First instinct (kill `downstream_host`) was wrong: that tears down the
*entire* session, upstream leg included (same finding as Round 2 - `RouterSession`'s teardown is
all-or-nothing), before a 0100 can even be sent through it. User's correction: kill `crypto_host`
instead - "more realistic," since a real STIP trigger *is* exactly "the HSM/crypto service is
unreachable, so the network makes its own call." Not a hard kill either: new PAN
`7777777777777777` (`pans_defined.json`) is configured in `simulators/crypto_host/config.json`'s
`no_response_pans` to hang on `validate_0100` specifically (the *request* leg, not Round 6/7's
response-leg PAN `8888888888888888` - reusing that one would have silently changed what those
rounds' own scenarios exercise). While that call hangs, the router hasn't registered the
transaction in `_pending` or forwarded it downstream yet, so upstream is left in genuine silence -
crypto_host itself stays healthy for every other PAN and every connection stays up throughout, no
teardown involved at all.

New scenario `scenario_crypto_request_leg_outage_triggers_advice` in `test_resilience.py`: send
one 0100 on the new PAN, poll for both 0420 and 0120 to fire and get acknowledged, confirm nothing
landed in `error_0120_0420.csv`, then an ordinary `test.csv` recovery check. **First run reported
FAIL despite the mechanism visibly working correctly in the logs** - `validate_0100` hung exactly
1.0s as configured, both 0420 and 0120 fired, both got acknowledged within *5 milliseconds*
(router/downstream were otherwise healthy - nothing slowed the ack round trip down). The scenario
was polling the `advice_pending_count` gauge every 0.5s; a state that's only non-zero for ~5ms is
essentially guaranteed to be missed by a 500ms-interval poll - the same class of "checking
transient state instead of the actual event" bug as the pytest polling race found earlier in this
round, just against real timing instead of the stub's. Fixed by polling `/logs` instead (matching
`scenario_stuck_pending_on_downstream_teardown`'s own established pattern above) - captures the
actual "advice: sent"/"acknowledged" log lines rather than racing a gauge. Rerun: PASS, both
messages fired and acknowledged, no error CSV entry, recovery `test.csv` round-tripped 3/3.

**Validation**: full suite 53/53 (50 from Round 7 + 3 new). No leftover processes after any live
check (confirmed via `ps aux`).

