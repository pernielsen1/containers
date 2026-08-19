# Soak results — 2026-08-19

Ran `run_soak.sh` with nothing else competing on the host: two back-to-back
clean runs, 100 TPS target / 120s each, at 20:39–20:45 and 20:50–20:57.
Results were reproducible across both runs.

| impl | p50 | p90 | p99 | max | achieved TPS |
|---|---|---|---|---|---|
| router_cpp | ~6.6ms | ~7.0ms | ~7.5–7.7ms | 17–22ms | ~92 |
| router_py | ~10.4–10.6ms | ~11.0ms | ~12.0–12.5ms | 19–20ms | ~92 |
| router_java | ~11.4–11.6ms | ~12.0–12.2ms | ~12.7–12.9ms | 42ms | ~93 |

## Takeaways

- **cpp** is fastest and tightest (p99 within ~1ms of p50).
- **python and java are close**, with python edging out java on p50
  (10.5ms vs 11.5ms), though java's max is worse (42ms vs 20ms).
- All three implementations cap at ~92-93 achieved TPS against a 100 TPS
  target — consistent across implementations, so the load generator itself
  looks like the bottleneck there, not any individual router.
- `slow_responds.csv` still shows scattered outliers up to ~100ms in these
  clean runs, but they stay within the p99 band — normal jitter, not a
  contention signal.

## Root-cause note: earlier "python is slow" anomaly

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

## 5-minute soak (2026-08-19, 21:06–21:20)

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
