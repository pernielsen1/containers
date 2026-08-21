# Soak results

Running log of soak/stress findings across sessions, newest section at the bottom.

## 2026-08-19

Ran `run_soak.sh` with nothing else competing on the host: two back-to-back
clean runs, 100 TPS target / 120s each, at 20:39–20:45 and 20:50–20:57.
Results were reproducible across both runs.

| impl | p50 | p90 | p99 | max | achieved TPS |
|---|---|---|---|---|---|
| router_cpp | ~6.6ms | ~7.0ms | ~7.5–7.7ms | 17–22ms | ~92 |
| router_py | ~10.4–10.6ms | ~11.0ms | ~12.0–12.5ms | 19–20ms | ~92 |
| router_java | ~11.4–11.6ms | ~12.0–12.2ms | ~12.7–12.9ms | 42ms | ~93 |

### Takeaways

- **cpp** is fastest and tightest (p99 within ~1ms of p50).
- **python and java are close**, with python edging out java on p50
  (10.5ms vs 11.5ms), though java's max is worse (42ms vs 20ms).
- All three implementations cap at ~92-93 achieved TPS against a 100 TPS
  target — consistent across implementations, so the load generator itself
  looks like the bottleneck there, not any individual router.
- `slow_responds.csv` still shows scattered outliers up to ~100ms in these
  clean runs, but they stay within the p99 band — normal jitter, not a
  contention signal.

### Root-cause note: earlier "python is slow" anomaly

Earlier same-day runs (19:46–20:32) showed router_py p50 at 68–178ms and
p90 at 204–365ms, a 7-15x blowup vs java/cpp. Originally suspected to be
SSL-related (SSL config was recently added to the stack — commit "ssl 2.0").

Comparing against these clean, isolated runs shows the anomaly disappears
entirely once nothing else is competing for CPU on the host. This points to
**host CPU contention, not SSL config or a python code regression**, as the
cause — router_py's perf appears far more sensitive to CPU contention on
this machine than java/cpp are (GIL contention under host-level CPU
pressure is the leading guess, not yet confirmed).

**Implication:** any future soak/stress comparison should be run with
nothing else on the machine, or the python numbers in particular can't be
trusted.

### 5-minute soak (2026-08-19, 21:06–21:20)

Follow-on run at 300s duration / 100 TPS target, same clean host state,
run right after the two 120s clean runs above.

| impl | sent/recv | errors | achieved TPS | p50 | p90 | p99 | max |
|---|---|---|---|---|---|---|---|
| router_cpp | 27623 | 0 | 92.1 | 6.64ms | 6.98ms | 7.44ms | 48.15ms |
| router_py | 27556 | 0 | 91.9 | 10.72ms | 12.12ms | 12.32ms | 53.24ms |
| router_java | 27667 | 0 | 92.2 | 11.53ms | 12.22ms | 12.32ms | 53.33ms |

Consistent with the 120s clean runs: same ordering, zero errors, achieved
TPS still capped ~92 across all three implementations regardless of
language (load generator is the bottleneck there, not the routers).

**New observation — outlier clustering at ~235s into each run:** each
implementation's two worst outliers land at nearly the same *relative
offset into its own run*, despite the three runs starting at different
wall-clock times (py 21:06:33, java 21:07:33, cpp 21:20:14):

- py: offset 235.454s → 53.24ms, offset 235.465s → 52.68ms
- java: offset 234.531s → 53.33ms, offset 234.542s → 50.81ms
- cpp: offset 235.524s → 48.15ms

Because the three runs don't overlap in wall-clock time, this isn't a
shared external event (e.g. a cron tick) — it points to something
intrinsic to the run itself, tied to elapsed time or cumulative request
count rather than implementation. Candidates: a periodic connection-pool
refresh, TLS session ticket rotation, or a GC/allocation cycle triggered
at a similar request count each run. Worth checking against the recent
SSL work (commit "ssl 2.0") given the timing lines up with ~23,500
requests in at 100 TPS. Not yet root-caused.

## 2026-08-20

Full context reset before today's runs: complete Docker rebuild (`--no-cache`), then a full host
reboot, then a settle period before touching anything. Several stress/soak collections were run
before the host had actually settled (20:31–21:35) — discarded entirely, including a broken
`router_cpp` stress row (1 sent, 1 error) that's itself a symptom of a not-yet-stable host. Per
the user's framing, `run_soak.sh 1` (100 TPS, 60s/phase, 21:36:44–21:40:48) is the **reset
marker** — first clean run on the freshly rebuilt+rebooted+settled host — and the following
`run_soak.sh 2` (100 TPS, 120s/phase, 21:43:33–21:50:01) is the **comparable-to-yesterday** run
(same 120s duration as the 2026-08-19 clean runs above). All CSVs (`soak_results`,
`soak_summary`, `stress_results`, `latency_buckets`, `slow_responds`) had every 2026-08-20 row
before 21:36:44 stripped, so only these two runs remain as today's data.

### Reset run (1 min, 100 TPS) — baseline for "host is quiet"

| impl | p50 | p90 | p99 | max | achieved TPS |
|---|---|---|---|---|---|
| router_cpp | 2.20ms | 2.74ms | 2.90ms | 4.34ms | ~96.9 |
| router_py | 2.93ms | 4.36ms | 4.77ms | 6.94ms | ~96.6 |
| router_java | 3.34ms | 4.20ms | 4.76ms | 9.12ms | ~96.8 |

All three within ~1ms of each other at p50 — this is what "nothing competing, everything warm"
looks like for all three implementations, java included. Confirms the reboot+rebuild genuinely
reset host state (achieved TPS also jumped from ~92% to ~97% of target vs. yesterday).

### 2-minute run — comparable to yesterday's 120s clean runs

| impl | p50 | p90 | p99 | max | achieved TPS |
|---|---|---|---|---|---|
| router_cpp | 2.23ms | 2.97ms | 3.34ms | 10.66ms | ~96.7 |
| router_py | 2.89ms | 3.14ms | 3.32ms | 5.68ms | ~97.0 |
| router_java | 10.96ms | 11.29ms | 11.39ms | 41.97ms | ~95.3 |

### The surprise: python now beats java, and java's numbers explain why

Yesterday's ordering was cpp << python ≈ java (python slightly ahead, both roughly 10-12ms p50).
Today's comparable run instead shows cpp ≈ python, both around 2.2-2.9ms, with **java alone**
sitting back up at ~11ms — almost exactly yesterday's steady-state java number. Two things
changed, not one:

- **python got dramatically faster** (10.5ms → 2.9ms p50), landing right next to cpp instead of
  next to java. This is consistent with the 2026-08-19 root-cause note above: python's perf was
  theorized to be unusually sensitive to host CPU contention (GIL-related). A from-scratch
  rebuild + reboot + settle is about as clean a host state as this box gets, so python finally
  gets to show its actual (SSL/asyncio) overhead relative to cpp, which turns out to be small.
- **java did not get faster — it degraded partway through its own run.** Bucketing
  `latency_buckets.csv` for the 2-minute java run shows a step change, not steady noise:

  | bucket (elapsed) | p50 | max |
  |---|---|---|
  | 0–30s | 3.78ms | 8.91ms |
  | 30–60s | 4.48ms | 36.97ms |
  | 60–90s | 11.12ms | 13.98ms |
  | 90–120s | 11.12ms | 41.97ms |

  Java starts in the same ~3-4ms band as python/cpp, then roughly **triples and plateaus** around
  the 60s mark and never recovers for the rest of the run. The reset run (which only covers 0-60s)
  never got far enough to see this — it caught java only in its healthy first half.

  Checking yesterday's equivalent buckets (e.g. the 20:39:46 and 20:51:23 router_java 120s runs)
  shows p50 already flat at ~11.2-12ms from the very first 0-30s bucket, every time, all day. That
  now reads less like "java is just slower" and more like **java was never observed in its fast
  state yesterday** — by the time any of yesterday's runs recorded latency, java's process had
  already accumulated enough prior requests (from the multiple stress/soak phases run before it,
  since the actor isn't restarted between phases) to have crossed whatever threshold triggers the
  step. Candidates for the step itself: JIT tier-up/deopt, a GC generation promotion once the heap
  crosses a size threshold, or a connection/thread-pool resize — all plausible causes of a
  one-time, request-count-triggered (not time-triggered) latency-tier change that then persists
  for the rest of the process's life. Not yet root-caused; worth confirming by watching
  `router_java`'s own `/stats` or JVM GC logs live through a run that starts cold and runs past the
  60s mark, and by checking whether the transition point tracks *elapsed time* or *cumulative
  request count* (today's step at ~60s / ~6000 requests vs. yesterday's already-degraded-from-the-
  start runs, which had far more cumulative requests behind them by that point, would both be
  consistent with a request-count trigger; only a live run all the way from a fresh container
  start would rule out a fixed-time trigger instead).

**Implication:** the cpp >> java > python ordering from 2026-08-19 was an artifact of two
separate effects stacking (python depressed by host contention, java's true fast-path never
observed) rather than a real language-performance ranking. On a clean host with a cold
`router_java` process, the real picture so far looks like **cpp ≈ python << java**, with java's
weakness being a mid-run latency-tier transition rather than raw per-request overhead.

### Follow-up: isolating the mid-run step (`fixjava.sh`, then a soak-2 replication)

Rather than the 5-minute rerun originally planned above, ran two more targeted tests the same
day, both against the java mid-run step seen in the comparable run's table above.

**`fixjava.sh`** (22:29:04): stopped and freshly restarted crypto_host, then ran router_java
alone, first thing, standalone from `run_soak.sh` — removing every other implementation's prior
traffic from the picture entirely, to test whether the step is JVM-internal (would still show up,
since `stress_run.sh` already gives java a brand-new JVM per call regardless of ordering) or
caused by crypto_host carrying state across phases (would disappear here). Result: **no step at
all** — buckets flat at 3.77 / 3.26 / 3.12 / 3.11ms, summary p50 3.24 / p90 4.1 / p99 5.45 / max
9.78ms. This ruled out a purely JVM-internal cause and pointed at crypto_host.

**Working theory at the time:** crypto_host's plugin-execution server is cpp-httplib,
thread-per-connection, fixed 24-thread pool (see `crypto_host_main.cpp:106-159`, sized for
java's Dispatcher's own worst case). Theory was that connections left open/pinned from the
python phase (which runs immediately before java in `run_soak.sh`'s py→java→cpp order) were
still held by crypto_host when java's phase started, and java's own connection count growing
into that ~60s in collided with them.

**Test:** wrote `watch_crypto_conns.sh`, a 1-second `ss` poller against crypto_host's plugin port
(5099), logging established/time-wait/close-wait counts to `csv_results/crypto_conns.csv`. Ran it
continuously across a full `run_soak.sh 2` replication (same py→java→cpp order, same shared
crypto_host, no restart in between — i.e. the same conditions as the original comparable run
that showed the step).

**Result: the theory doesn't hold, and neither does the step.** Connections were clean the whole
way — established count sat flat at 32 through python's entire phase, dropped cleanly to 0 at the
phase boundary (one 2-second close-wait blip, nothing lingering), stayed at 0 through the ~32s
cooldown, then ramped cleanly to 32 for java's phase and held flat there for all 120s. No growth
toward a ceiling, no leftover connections carried over. And java's latency this time: flat at
3.75 / 3.26 / 3.14 / 3.16ms across all four buckets, summary p50 3.27 / p90 4.1 / p99 5.37 / max
11.16ms — matching the isolated `fixjava.sh` run, not the original degraded one.

**Where this leaves it:** the mid-run step has now happened exactly once (the original 21:47
comparable run) and failed to reproduce twice in a row, including once under the exact conditions
(same phase order, same non-restarted crypto_host) that produced it originally. That's a weak
basis for any deterministic phase-order or connection-state mechanism. The more likely
explanation now is that the original run hit a one-off, most likely environmental rather than a
java or crypto_host structural issue — the known WSL2 `hv_utils` TimeSync clock-resync stall
(see `big_question.md`) is the leading candidate, though `dmesg` only logs that driver's
boot-time registration, not individual resync events, so this can't be confirmed retroactively
from the logs available.

**Implication:** two of the last three clean java measurements now put it at p50 ~3.2-3.3ms —
close to python's ~2.9-3.5ms and a real but modest step behind cpp's ~2.2-2.3ms, not the 3-4x
outlier the original comparable run suggested. See `big_question.md` for the updated framing.

### 5-minute soak (2026-08-20, 23:07–23:20) — the step recurs, this time in cpp

Same host, same day, run right after everything above (py→java→cpp order, 300s/phase, 100 TPS
target — directly comparable to the 2026-08-19 5-minute soak earlier in this doc).

| impl | sent/recv | errors | achieved TPS | p50 | p90 | p99 | max |
|---|---|---|---|---|---|---|---|
| router_py | 27640 | 0 | 92.1 | 6.91ms | 7.65ms | 8.81ms | 43.96ms |
| router_java | 27508 | 0 | 91.7 | 6.36ms | 7.51ms | 9.08ms | 38.67ms |
| router_cpp | 26992 | 0 | 90.0 | **11.81ms** | 12.62ms | 13.04ms | 42.15ms |

python and java both ran flat and steady the whole 300s (bucketed p50 stays in a tight 6.0–7.3ms
band throughout for both, no step in either). **cpp is the outlier this time** — and unlike
java's earlier one-time step-and-plateau, cpp's pattern oscillates:

| bucket (elapsed) | p50 | max |
|---|---|---|
| 0–30s | 4.71ms | 26.31ms |
| 30–60s | 11.97ms | 17.56ms |
| 60–90s | 11.95ms | 16.08ms |
| 90–120s | 11.98ms | 15.67ms |
| 120–150s | 11.96ms | 13.49ms |
| 150–180s | 11.94ms | 14.31ms |
| 180–210s | 11.91ms | 15.20ms |
| 210–240s | 11.93ms | 42.15ms |
| **240–270s** | **5.33ms** | 9.77ms |
| 270–300s | 11.86ms | 41.87ms |

cpp starts in its usual healthy ~4.7ms band, steps up to ~11.9ms at the 30s mark (almost exactly
java's old step, both in shape and magnitude) and holds there — then, unlike anything seen before,
**drops back down** to 5.33ms for one bucket (240–270s) before stepping back up again for the
final bucket. That's a transition in both directions inside a single run, not a one-way
step-and-plateau.

No `watch_crypto_conns.sh` diagnostic was running during this soak (it was only wired up for the
earlier java investigation), so the connection-pinning theory can't be checked here. `dmesg -T`
shows no `hv_utils` TimeSync event anywhere near this run's window (23:07–23:25) — the only
TimeSync line on the host is the boot-time driver registration at 21:30:54, well before this soak
started — so the known WSL2 clock-resync stall doesn't explain it either, at least not in a way
`dmesg` can confirm.

**Why this matters for `big_question.md`:** the step is no longer something that happened once, to
java specifically. It has now shown up in two different languages, in two different runs, with two
different shapes (one-way plateau for java on 2026-08-20 daytime; up-then-down-then-up for cpp
here). That's much harder to explain as a language-internal mechanism (JIT tier-up, GC promotion,
JVM pool resize — all java-specific theories from the earlier write-up) and easier to explain as
something in the shared environment (host, Docker, or the shared `crypto_host` container) that
occasionally perturbs whichever implementation is running at the time. Doesn't identify a cause,
but it does shift weight further away from "java has a structural weakness" and toward "this host
has an intermittent, implementation-agnostic hiccup" — worth carrying into the multi-host soak plan
rather than treating java's earlier step as closed.

## 2026-08-21

### Local soak, pre-remote (20:46–21:12, LAPTOP-P5P268SM) — the zero point

Two more 120s/100 TPS runs, same dev laptop as every session above, run right before remote soak
testing against `serverhp.home` became possible (`run_soak_remote.sh`, built later the same
session). Marking these as the **zero point** for the multi-host soak plan from `big_question.md`
— the last measurement taken entirely on this laptop, before there's any cross-host run to compare
it against.

| run | impl | p50 | p90 | p99 | max |
|---|---|---|---|---|---|
| A (20:46–20:59) | router_py | 3.98ms | 4.89ms | – | 6.71ms |
| A | router_java | 3.91ms | 5.79ms | – | 12.11ms |
| A | router_cpp | **11.58ms** | 12.37ms | – | 21.89ms |
| B (21:04–21:11) | router_py | 3.15ms | 3.61ms | 3.74ms | 6.22ms |
| B | router_java | **10.98ms** | 11.58ms | 11.92ms | 48.18ms |
| B | router_cpp | 2.72ms | 3.41ms | 3.61ms | 11.48ms |

**The alternating step recurs — twice more, and it swapped implementations again.** Bucketing
each phase:

| run | impl | 0–30s p50 | 30–60s p50 | 60–90s p50 | 90–120s p50 |
|---|---|---|---|---|---|
| A | router_py | 3.79ms | 4.44ms | 4.01ms | 3.48ms |
| A | router_java | 5.06ms | 4.12ms | 3.63ms | 3.65ms |
| A | **router_cpp** | 3.57ms | **11.83ms** | 11.71ms | 11.99ms |
| B | router_py | 3.18ms | 3.11ms | 3.13ms | 3.20ms |
| B | **router_java** | 6.12ms | **11.07ms** | 10.84ms | 11.16ms |
| B | router_cpp | 2.83ms | 2.91ms | 2.90ms | 2.36ms |

Same shape both times — flat and healthy for the first bucket, then a one-way step up to ~11-12ms
at the 30s mark that holds for the rest of the run — but a **different implementation each time**:
cpp stepped in run A while java and python stayed flat; java stepped in run B while cpp and python
stayed flat. Python has now stayed flat and steady in every one of these runs across three days
(2026-08-19/20/21) — it's cpp and java that keep trading off which one hits the step. That's now
four data points (java 2026-08-20 daytime, cpp 2026-08-20 evening 5-minute soak, cpp here, java
here) all sharing the same onset window and magnitude, spread across both non-python
implementations and never python — a strong signal for **something host/Docker/crypto_host-side
that the step-taking implementation just happens to hit**, not a per-language weakness. Still not
root-caused; still worth carrying into the multi-host soak plan to see whether it follows the
implementation, the host, or neither once serverhp.home data exists to compare against.

### Remote soak testing enabled

Built out `deploy.sh`/`server_start.sh`/`run_soak_remote.sh` this session so serverhp.home can run
the router/downstream_host/crypto_host side while this laptop drives `upstream_host` and collects
stats (see `old/divide_and_conquer.md` for the deployment-side detail). Verified live end-to-end for
all three implementations, including a full 3-phase `run_soak_remote.sh` smoke pass (6s/phase, 0
errors across the board) purely to prove the pipeline — too short to be a real data point, not
included in the tables above.

**Next up**: first real remote soak (`run_soak_remote.sh 2`, matching this doc's existing
"2-minute run" comparable format) against serverhp.home, to start weighing the zero point above
against actual cross-host data.

### First real remote soak (2026-08-21, 23:13–23:19, serverhp.home) — the cross-host reading

`run_soak_remote.sh 2` (120s/phase, 100 TPS, py→java→cpp), run right after the LAPTOP-P5P268SM
22:57–23:09 run above — the closest same-session laptop comparison point available.

| impl | p50 | p90 | p99 | max | achieved TPS |
|---|---|---|---|---|---|
| router_py | 15.75ms | 17.64ms | 26.14ms | 78.23ms | ~95.75 |
| router_java | 15.27ms | 16.89ms | 25.67ms | 83.64ms | ~96.96 |
| router_cpp | 15.38ms | 17.01ms | 23.38ms | 80.58ms | ~96.70 |

Zero errors across all three, achieved TPS still ~96% of target — serverhp.home keeps up with the
100 TPS load fine. Worth spelling out just how old the hardware behind that number is: `hpserver`
is an AMD Athlon II P320, a 2-core/2-thread ~2.1GHz low-power *dual-core* part from around 2010 —
roughly 15+ years old, one core generation before anything with per-core turbo boost, hyperthreading,
or a modern instruction set became standard — running bare metal with ~3.4GB RAM. Sustaining 100
TPS end-to-end with 0 errors on hardware that old, this deep into the "will this still be running
in decades" question, is a genuinely reassuring result, not just a slower number.

The interesting part beyond the raw age is the shape of the numbers: **all three implementations
land within 0.5ms of each other** (15.27–15.38ms p50), a clustering never seen on the laptop,
where cpp/py normally sit close together and java (or occasionally cpp) breaks off with the
still-unexplained step from earlier sections. That clustering is itself informative — it reads as
the Athlon II P320's two cores being slow enough that the CPU itself, not any language runtime, is
now the dominant cost. Once the host itself is the bottleneck, language choice stops showing up in
the numbers.

Versus the laptop's same-session python number (2.90ms p50, the cleanest of the three since it
isn't affected by the step artifact), serverhp.home is **~5.4x slower at p50** and roughly **7x
worse at max** (78–84ms vs 6–11ms). Recorded as a per-host performance factor in the new
`csv_results/hw.csv` (hardware specs + measured factor per host, keyed by the same `env` names
used in `soak_summary.csv`), started this session to give the multi-host soak plan an actual
expectations baseline instead of re-deriving "how much slower is this host" from raw CSVs each
time. Third row reserved for the city laptop — no soak data for it yet, hw.csv row left as a
placeholder until it's benchmarked.

**Implication for the 24/7-for-years goal:** even the weakest host in the current lineup handles
100 TPS with 0 errors — this is a latency/SLA question, not a stability one at this load level.
The real risk visible here is tail latency (p99 up to 26ms, max up to 84ms on serverhp.home) if
the eventual production SLA is tighter than "keep up with the average," combined with the still
open, host/Docker-side intermittent step (see the 2026-08-20/21 sections above) that hasn't been
root-caused on any host yet and would compound with an already-slower box.

### Strategy decision: python-first, python-primary (2026-08-21)

Direct consequence of the serverhp.home reading above: 100 TPS is achievable, with 0 errors, on
the *oldest, weakest* hardware in the lineup — a ~15-year-old 2-core Athlon II P320 — running
python. Combined with python already being the most readable/maintainable of the three
implementations (see `big_question.md`'s maintainability arguments), the decision is:

- **Python is the primary implementation going forward.** It's good enough on hardware this old,
  and it's the easiest of the three to read, change, and reason about. Readability and verified
  performance both point the same direction, so build here first.
- **Java and cpp stay in the repo as contenders, not dead weight.** They're not being dropped —
  they remain the comparison points that make "is python's performance actually fine" a
  measured answer instead of an assumption. This directly revises the "should java be kept"
  framing in `big_question.md`: the point of keeping contenders isn't performance supremacy, it's
  having something to measure against. The java mid-run "step" investigation (2026-08-20 sections
  above) is the concrete example — chasing what looked like a java-specific problem ended up
  surfacing a shared host/Docker-level latency artifact that *also* hit cpp (and, per the
  2026-08-19 root-cause note, had already been shown to affect python under host contention too).
  Without java as a contender, that cross-implementation artifact would likely have been
  misread as "java is just slow" and never investigated further.
- **Revised build pattern:** simplify or add functionality in python first, get it working, and
  measure its performance against python's own established baseline (the existing soak/stress
  numbers in this doc) *before* porting the same change to java and cpp — not after, and not in
  parallel. This is a refinement of the existing "every feature lands in python first" pattern
  (see `project_routers_monorepo` memory), adding an explicit performance-verification gate ahead
  of the port instead of only checking correctness. Java and cpp ports remain required (to keep
  them usable as contenders), just sequenced after python is both working and measured.
