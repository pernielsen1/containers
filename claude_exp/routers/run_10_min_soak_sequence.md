# Running the 10-minute soak sequence manually

This host only has ~2.8GB RAM, and running Claude Code + VS Code (with its Java language
servers) alongside a ~40-minute back-to-back stress test pushed it into real OOM territory during
an earlier attempt (see `performance_result_20260730.md`, "2026-07-31, stress test part 2" — a
logged kernel OOM-kill landed mid-run and corrupted the results). Running it standalone, with the
IDE and this session closed, avoids that.

## What it does

`run_10min_soak_sequence.sh` runs three phases, back to back, no supervision needed:

1. **router_py (Python) @ 80 tps for 10 minutes.**
2. **2-minute idle cooldown** (just a sleep, nothing running).
3. **router_java (Java) @ 100 tps for 10 minutes.**
4. **2-minute idle cooldown.**
5. **router_cpp (C++) @ 100 tps for 10 minutes.**

(router_java's 100 tps rate no longer needs a preceding 5-minute validation pass — confirmed
clean, 0 errors, directly at 100 tps/600s.)

Total runtime: ~32 minutes. Each phase prints a `RESULT: <line>` to stdout, and every run also
appends a row to `stress_results.csv`, `slow_responds.csv` (10 slowest round trips per run, with
time-since-run-start), and `latency_buckets.csv` (30s-windowed p50/max per run) in this directory.

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
   ./run_10min_soak_sequence.sh
   ```

6. Let it run undisturbed for ~40 minutes.

## After it finishes

Results are already saved in `stress_results.csv` / `slow_responds.csv` / `latency_buckets.csv`.
Start a fresh session (or share the terminal output) and the findings can be written up from those
files directly.
