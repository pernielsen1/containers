# Running the soak sequence manually

This host only has ~2.8GB RAM, and running Claude Code + VS Code (with its Java language
servers) alongside a ~40-minute back-to-back stress test pushed it into real OOM territory during
an earlier attempt (see `performance.md`, "2026-07-31, stress test part 2" — a
logged kernel OOM-kill landed mid-run and corrupted the results). Running it standalone, with the
IDE and this session closed, avoids that.

## What it does

`run_soak.sh [number_of_minutes]` runs three phases, back to back, no supervision
needed. `number_of_minutes` defaults to 10; the cooldown between phases is always
`number_of_minutes / 5`:

1. **router_py (Python) @ 100 tps for `number_of_minutes` minutes.**
2. **Idle cooldown** of `number_of_minutes / 5` minutes (just a sleep, nothing running).
3. **router_java (Java) @ 100 tps for `number_of_minutes` minutes.**
4. **Idle cooldown** of `number_of_minutes / 5` minutes.
5. **router_cpp (C++) @ 100 tps for `number_of_minutes` minutes.**

(All three now run at 100 tps — router_py was bumped up from 80 tps on 2026-08-16 once a
crypto_host TCP_NODELAY fix collapsed its p50 from ~90ms to ~5ms, closing most of the gap that
made 80 tps the safe ceiling before. router_java's 100 tps rate no longer needs a preceding
5-minute validation pass either — confirmed clean, 0 errors, directly at 100 tps/600s.)

`router_java/stress_run.sh` (used by phase 3) used to leave the `router_java` Docker container
running after every soak/stress run, unlike `router_cpp` which always tears its container down —
fixed 2026-08-16 (it now only stops the container if that same run is the one that started it, so
an interactive dev session with the container already up is left alone). Worth knowing if you're
tracking down what's holding memory after a run: `crypto_host` staying up is expected, `router_java`
lingering afterward is not, and now shouldn't happen.

At the default 10 minutes, total runtime is ~32 minutes. Each phase prints a `RESULT: <line>` to
stdout, and every run also appends a row to `csv_results/stress_results.csv`,
`csv_results/slow_responds.csv` (10 slowest round trips per run, with time-since-run-start), and
`csv_results/latency_buckets.csv` (30s-windowed p50/max per run).

The sequence itself also writes two more files in `csv_results/`, both semicolon-separated with a
comma decimal point (utf-8-sig BOM, same convention as every other CSV in this repo):
`soak_results.csv` (one full row per phase: sent/received/errors/achieved_tps/p50/p90/p95/p99/max)
and `soak_summary.csv` (just the p50/p90/p99 columns, for a quick read).

## Steps

1. **Confirm the shared `crypto_host` is up** (it must survive across the whole sequence — it's
   not restarted between phases):
   ```
   curl -sf http://127.0.0.1:8099/stats
   ```
   If that fails:
   ```
   cd ~/containers/claude_exp/routers/crypto_host && ./start.sh
   ```

2. **Close VS Code entirely** — not just the window, make sure the extension host and both Java
   language server processes actually exit — and **end the Claude Code session**. These are the
   actual source of the memory pressure, not the test processes themselves.

3. **Open a plain WSL terminal** (Windows Terminal → your WSL distro), not VS Code's integrated
   terminal, so nothing re-spawns extension-host children.

4. **Optional sanity check** — give memory a few seconds to settle after closing everything, then
   confirm it actually recovered:
   ```
   free -h
   ```
   Swap usage should be dropping, not still pinned near full.

5. **Run the sequence:**
   ```
   cd ~/containers/claude_exp/routers
   ./run_soak.sh        # default: 10-minute phases, 2-minute cooldowns
   ./run_soak.sh 20     # 20-minute phases, 4-minute cooldowns
   ```

6. Let it run undisturbed (roughly `3 * number_of_minutes * 1.2` minutes, including cooldowns).

## After it finishes

Results are already saved in `csv_results/stress_results.csv` / `csv_results/slow_responds.csv` /
`csv_results/latency_buckets.csv` / `csv_results/soak_results.csv` / `csv_results/soak_summary.csv`.
Start a fresh session (or share the terminal output) and the findings can be written up from those
files directly.
