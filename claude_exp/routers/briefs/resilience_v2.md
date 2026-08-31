# we have performance - resilience is king
# on auto 
we had a bit of clash on auto - so ask me permission on any changes in side this directory then they are autoapproved - i.e. what happens in routers stays in routers :-) 
## experiment python only in host
we have the routers in docker containers fine for performance.
we have selected python first 
for the following - let's do the changes in host python files first - then when we are good with results commit them to the container world..
not nessecary to keep seperate versions locally we will trust in git - i have committed all including results of last 10 m soak runs
## resilience - be rude 
remember the overall pattern - a router may loose an upstream or downstream connection but always needs to be able to recover and be ready for new connections.
we have added SSL - if a upstream or downstream have changed certificates and we are not synched then we cannot recover - we are in a situation needs to be logged as ERROR
## BE BAD AND DESTRUCTIVE  - code monkeys
I want you to build a destructive attack script which we can run against the solution.
a bit like the code monkeys introduced in netflix if I remember correctly - I wan't to see a solution which will get it self back on track (excluding the SSL - certificates which needs intervention)

## let's be more destructive build up a queue.. 
so let try the following pattern - upstream host - keeps on sending messages in - the crypto host is Ok on the request before downstrean host (i.e the 0100) but fails on handling the response the (0110) and thus the upstream host doesn't get the reply and will try again
My espectation is we will stop reading upstream at some point but let's see 
store this scenario as part of the resilience tests 

## having build up the queue - let's look at what happens in real world
most likely it will fail on x (being a very low percentage) and what happens is that the upstream host should time out and say (OK we forget this one)
so let's say 10 % (which is a very high number) actually fails - then we still want's to see that the 100 tps is met... 
what is important here is that they synchrounus call to crypto_host is Ok with the pattern fire and forget in a fee milliseconds.. because no one cares about the result anymore...
on this labtop if reply is delayed by more than 200 ms then if's fire and forget.. real life probably in the 50-75 ms range  (the performance of the application right now on this little labtop actually almost covers real life.. so it's close to being real - well when I close all the memory consuming tasks like my vscode editor - ask me to close it when you are ready)
 
# 0120/0130 advice message and 0400/0410 - reversal
The iso8583 protocol is very resilient by the fact that every actor knowns things can go wrong - and in the end we don't wait for synchronous responses - but rather go on and treat the next authorization and see if that goes better. 
## meaning - timeout 0100 triggers reversal 0400 
When an auth (0100) does not get the (0110) the requestor in this case upstream host on timeout will send a 0400 message - basically the layout of the message is similar to the 0100 message - and the purpose is "I know I asked for an authorization - but please just forget it" i.e. even if the downstream host in this case actually has decided to give a 0110 and reserved the money it now knows - no it wasn't for real.
a reversal is acknoledged by the issuer (downstream_host) with a 0410 meaning - I have understood I can forget your 0100 - and even if I have reserved the amount I will now release it.

## STIP processing 
STand In Processing - so a request (0100) times out - but the card holder is waiting for a decision - often issuers will allow for STIP i.e. smaller amounts will be approved by the upstream host  - in this case it is the responsibility of the upstream host to inform (advice) with a 0120 message to the issuer (downstream_host) that hey I have taken a decision on your behalf - as 0120 message is then acknoledged with a 0130 message from the issuer i.e. I have understood your decision.

## no crypto on 0400/0410 and 0120/0130
we will not need to pass the crypto_host for the 0400/0410 & 0120/0130 
basically the reply (0410) and (0130) is just an echo of inbound message (0400 and 0120) where the message type is changed - this acknoledge is done by issuer (downstream_host) but router should understand this and not try to send the message via the crypto_host (which actually was the original culprit in our faked scenario)

# OK let's make resilience_soak.sh scripts
## run_soak_resilience_light.sh
in addition to the run_soak.sh we will have the possibility of adding --fail_percentage (defualt 10 %) which will ensure that fail_percentage.sh of the requests sent in will not generate a response from crypto_host.
## run_soak_resilience_hard.sh 
if addition ro run_soak.sh I can add a parameter --crypto_fail_minutes
which means that the soak test runs and then after 1 minute the crypto_host is killed and will recover after --crypto_fail_minutes
this will trigger a bunch of 0120 and 0420 messages - interesting if we can keep up 
results should be in soak.sh - with numbers before the kill, during the kill and after the kill.. add to name of router in the stage it is in.

# have been evaluating the scenario
the behaviour we have seen is not how it would be in real life - which I think clutters the results.
now 0120/0420 will be have lower priority at upstream host than 0100 messages - this combined with the fact that the simulator will just fire 0100 to reach it's tps - 
lets assume we have a advice_reversal percentage figure in the config.json meaning that 0120 & 0420 would only be allowed to use a percentage of the capacity - it will take longer time to have cleared the 0120/0420 queues at upstream host - but the normal traffic 0100 will flow.. 
let's make the following example - the advice_reversal figure is 10 % - the tps target is 80
the upstream_host should then send one 0120 or 0420 for each time it has sent 9 0100 messages there should be room for both 80 0110 and 8 0120/0420 since that is 88 and we know we can handle 100 tps.  (and then the overhead for the 0120 and 0420 is actually smaller due to no call out to crypto_host)

# resilience_hard soak findings (2026-08-29/30)

## crypto_host's own capacity ceiling, not host load
Isolated benchmark (direct `CryptoClient` calls against `crypto_host`, no router/upstream_host in
the loop, idle host): throughput caps at ~140 req/s regardless of concurrency (1/4/8/16 threads:
45/141/142/132 req/s), p50 climbing 22ms->113ms as concurrency rises. Root cause: crypto_host's
own dev-mode Flask server (this soak's lightweight host-python stub, not the shared C++ container)
just doesn't scale past that - it's a stub server limit, not a router/dispatcher problem, not host
contention (load average, memory, swap all checked clean at the time).

Each transaction needs 2 crypto calls (0100 request leg + 0110 response leg), so a TPS target needs
roughly double that in req/s from crypto_host. TPS_TARGET was dropped from 100 to **60** (~120
req/s, ~86% of the ceiling) - verified clean and stable at 60 (0 errors, tight latency bands) across
repeated runs on 2026-08-30.

**Tried raising it to 80 anyway (2026-08-30) - confirmed the ceiling is real, not overly
conservative.** 80 TPS needs ~160 req/s, over the ~140 req/s ceiling. Result: `crypto_rtt` p50 shot
up to ~110-113ms (from ~2-4ms at 60 TPS) even in `before_kill`, with **no kill involved at all** -
46% of `before_kill` transactions errored out (631/1377) just from ordinary steady-state load
exceeding what crypto_host can keep up with. `after_kill` was worse: queue_depth grew unboundedly
(77 -> 138 -> 191 -> 297 -> 354 -> 383 over the 60s window) and errors hit 86% (3937/4558) by the
end - a genuine, sustained backpressure collapse, not a one-off blip. The advice/reversal pipeline
itself held up fine throughout (0120/0420 sent == acked at every sample) - it's absorbing the
overload correctly, it just can't hide that crypto_host physically can't take the traffic. **80 TPS
does not work against this stub as-is; 60 TPS is the real ceiling until crypto_host's dev-mode
Flask server is swapped for a production WSGI server** (not yet done).

## crypto breaker recovery was on a blind clock, not tied to when crypto_host actually came back
`CryptoClient`'s circuit breaker (`router/crypto_client.py`) re-arms its own cooldown every time a
post-cooldown probe still fails - so while crypto_host is dead it self-renews on a fixed
`crypto_breaker_cooldown_seconds` (30s) cadence with no way to learn the service is back except by
waiting out that same clock again. Effect: crypto_host restarts partway through the breaker's
current 30s window, but the breaker doesn't re-probe until that window naturally expires - so the
first ~10s (observed) of `after_kill` kept getting real transactions hard-dropped
(`dispatcher.py`'s "genuine crypto failure on the response leg -> drop the 0110, let it fall back to
0420/0120" behavior) even though crypto_host was already healthy again.

**Fix: event-driven reset.** `CryptoClient.reset_breaker()` closes the breaker immediately (clears
failure count, `_open_until`, bumps `_generation` so cached connections get rebuilt fresh) instead
of waiting on its own clock. Exposed via a new router command-server route,
`POST /crypto/reset_breaker` (`router/main.py`), which resets both the request-leg and
response-leg `CryptoClient` instances on the active session's dispatcher. `soak_resilience_hard.py`
calls it right after `start_actor("crypto_host")` confirms the restarted service's port is actually
open (`reset_crypto_breaker()`) - that confirmation is the "event" driving the reset. Verified: in
the run right after this landed, `crypto_rtt` in the very first `after_kill` poll (10s in) was
already ~110ms (i.e. real calls happening, breaker already closed) instead of staying near 0 for
another 20-30s as it did before the fix. Best-effort by design - if the reset call itself fails
(router down, request hiccup), the breaker just falls back to its own cooldown clock, same as
before this existed.

## the ~140 req/s ceiling is the stub, not a real limit - confirmed by running against the real crypto_host
80 TPS was retried against the real, shared C++ `crypto_host` container (routers/crypto_host, the
OpenSSL-backed one `run_soak.sh`/`stress_run.sh` already use, promoted out of router_cpp precisely so
it wouldn't bottleneck the perf comparisons) instead of router_py's own Flask-stub. Same traffic
pattern, same TPS target, night-and-day result: `crypto_rtt` p50 ~1.6-2ms (max ~62ms) the whole
`before_kill` window, 0 errors by the end (1366/1366 sent==received, achieved_tps 75.86 against an 80
target) - vs. ~110-113ms and 46% errors against the stub at the same TPS. Confirms the ceiling
documented above is purely the test harness's own lightweight stub server, not a statement about
crypto validation performance in general - the real container was built not to have this problem, and
doesn't.

`soak_resilience_hard.py` now takes a `--real-crypto` flag (`run_soak_resilience_hard.sh` passes it
through) to run this scenario against that real container instead of the stub: points router_1 at it
via the already-verified `router/router_1/config_perf.json` (same config `stress_run.sh`'s perf phase
uses - reused rather than authoring a new one), and swaps the stub's process-kill/relaunch for
`docker kill`/`docker start` against the container. Results land under a distinct
`router_py_real_crypto_...` CSV label so the two capacity profiles never get averaged together by
accident. Requires the container already running (`crypto_host/start.sh`) - this flag only
kills/restarts it, never builds or first-starts it. Verified end to end through `before_kill` (clean,
numbers above) on this dev sandbox; the `docker kill`/`docker start` steps themselves could not be
exercised here (no docker daemon available in this sandbox) - first real run of `--real-crypto`
should confirm those specifically.

## real crypto_host, full before/during/after kill cycle at 100 TPS (2026-08-30)
First run of `--real-crypto` with the `docker kill`/`docker start` steps actually exercised (closing
the follow-up directly above), and at 100 TPS - above the 80 already verified for `before_kill` only.
Clean end to end: `before_kill` 1738/1738 sent==received (0 errors, achieved 96.5 TPS), `crypto_rtt`
p50 3.08ms / p99 4.63ms / max 7.44ms. `during_kill` correctly dropped all 4005 in-flight 0110s to
advice/reversal with none left over (331 0120 sent==acked, 331 0420 sent==acked - queue fully
cleared inside the window, not just draining). `after_kill` 5761/5761 sent==received (0 errors,
achieved 96.01 TPS); p50 rose to 10.78ms (breaker-reset/reconnect overhead) but max stayed 44.34ms -
nothing like the stub's 700ms+ p50 / 46-86% error collapse at the same target documented above.
Confirms the real container has headroom past 80 TPS and that the event-driven breaker reset +
advice-throttle machinery both hold up cleanly through a full real kill/recovery cycle, not just the
`before_kill` window.

## C++ crypto_host patched with the same PAN-keyed chaos hook the stub already had
`test_resilience.py`'s scenarios (queue-buildup, request-leg vs. response-leg hangs) rely on
router_py's stub-only `no_response_pans` config (`simulators/crypto_host/config.json`: a `{pan:
[operation, ...]}` map - a matching request gets no real response, only a bounded 2s stall then an
error, so the caller's own timeout always decides the outcome first). The real C++ `crypto_host` had
no equivalent at all - patched in now (`crypto_host/src/router/router_config.h`/`.cpp`,
`crypto_host/src/simulators/crypto_host/crypto_host_main.cpp`), same semantics, same 2s bound, and the
same two magic test PANs (`7777777777777777` / `8888888888888888`, never used by any real stress-test
CSV) added to `crypto_host/config/crypto_host.json` by default - same "always configured, never hit by
ordinary traffic" pattern the stub already relies on. Verified directly against a local build: chaos
PAN+matching operation -> ~2.06s then 504 "chaos: no response"; same PAN with the *other* operation, or
any ordinary PAN -> normal fast 200. Existing `crypto_host_tests` (17 assertions) still pass. Only the
capability was added here - `test_resilience.py` itself is not yet wired to target the real container
(still stub-only), same follow-up as `soak_resilience_hard.py` was before this session.

## crypto idle-timeout fix, then a full 10-minute hard soak surfaces a *different*, unfixed staleness bug (2026-08-30)
`crypto_host` (cpp-httplib) closes a keep-alive connection after its own ~5s idle timeout, regardless
of the breaker - reproduced directly: after any ~5s+ traffic lull (e.g. this soak's own tail-settle
sleep between stress windows), reusing a thread-local cached connection failed with `SSLEOFError` -
silent/fails-open on the request leg, but drops the response entirely on the response leg (same drop
behavior as the already-known `validate_0110` case). Fixed in `crypto_client.py`'s `_get_connection()`:
track per-thread `last_used` (monotonic), proactively discard+rebuild a connection idle past
`idle_timeout_seconds` (default 4.0s, under crypto_host's ~5s) - anticipate staleness, don't discover
it by failing first, same principle as the 2026-08-29 generation check. 2 new tests in
`test_crypto_breaker.py`, 8/8 passing.

Ran the full 10-minute `--real-crypto` hard soak (90s/210s/300s before/during/after @ 100 TPS) right
after to confirm the fix didn't disturb anything. `during_kill` (19418 sent, 0 received, 100% errors,
~92 achieved TPS) and `after_kill` (27878/27878, 0 errors, p50 11.5ms / p99 12.9ms / max 107.6ms) both
match the known-clean 100 TPS pattern above exactly - no new failures, `during_kill`'s 100%-error is
the already-documented `validate_0110`-drops-on-crypto-failure behavior, not a regression.

But `before_kill` came back 0 sent / 0 received / 0.0 achieved TPS - the entire first stage produced
zero traffic, which fails `soak_resilience_hard.py`'s own pass/fail gate (needs `before_kill`/
`after_kill` >=95 TPS). **Root cause, from reading the code (not yet confirmed live)**:
`upstream_host/main.py`'s `_send_loop` aborts the whole stress window permanently on its very first
failed write - no retry, no reconnect attempt within that run. Reconnection of the
upstream_1<->router_1 link is only ever triggered by a *read*-side `ConnectionError`
(`_receive_loop` sets `disc_evt`); a write failure alone (`_write_frame` catches `OSError`, returns
`False`) never sets it, so a connection that died from the write side first is never noticed or
reconnected on its own - `wait_for_ready()`'s upstream check just trusts a `connections.router` flag
this same broken loop can leave stuck "true". If the connection had gone stale during the idle gap
between back-to-back soak invocations, the very first `/start` of a fresh run could grab that dead
cached connection, fail its first write, and give up for the rest of the stage - while the read side
detects the same break moments later and `_client_connect_loop` reconnects in time for the *next*
stage's fresh `/start` (explaining why `during_kill`/`after_kill` worked fine in the same run). Same
*class* of bug as the crypto-idle-timeout fix above (a cached connection goes stale, nothing
proactively validates it before use), just on a different connection, and **not yet fixed** - only
diagnosed by reading `upstream_host/main.py`, not reproduced live. Next step: either have `_send_loop`
retry-and-reconnect once on its first write failure instead of exiting silently, or have
`wait_for_ready`'s upstream check actually validate the connection is live rather than trusting the
flag.
