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

