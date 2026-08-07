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
while building the live-diagnosis tooling in `briefs/debug_trace_master.md`. Not the SIGSTOP
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

