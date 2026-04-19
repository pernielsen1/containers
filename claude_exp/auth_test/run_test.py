#!/usr/bin/env bash
"""Test driver: runs the full test suite for each TCP framing scheme."""

import subprocess
import sys
import time
import os

BASE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(BASE, "main.py")
PORT = 1042
FRAMINGS = ["TCP_framing_standard", "TCP_framing_FFFF_nnnn"]


def run_once(framing: str, verbose: bool) -> bool:
    print(f"\n{'='*60}", flush=True)
    print(f"  Framing: {framing}", flush=True)
    print(f"{'='*60}", flush=True)

    verbose_flag = ["--verbose", "--log-level", "DEBUG"] if verbose else ["--no-verbose"]

    server = subprocess.Popen(
        [sys.executable, MAIN, "server", "--port", str(PORT), "--framing", framing] + verbose_flag,
        cwd=BASE,
    )
    time.sleep(0.5)

    client = subprocess.Popen(
        [sys.executable, MAIN, "client", "--port", str(PORT), "--framing", framing] + verbose_flag,
        cwd=BASE,
    )

    try:
        client.wait(timeout=60)
    except subprocess.TimeoutExpired:
        print(f"[{framing}] Client timed out", flush=True)
        client.kill()

    server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()

    results = os.path.join(BASE, "output", "results.csv")
    ok = os.path.exists(results)
    print(f"[{framing}] {'PASS — results.csv written' if ok else 'FAIL — no results.csv'}", flush=True)
    return ok


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run ISO 8583 auth test suite")
    parser.add_argument("--verbose", action="store_true", default=False,
                        help="Pass --verbose to client and server subprocesses")
    args = parser.parse_args()
    passed = []
    for framing in FRAMINGS:
        passed.append(run_once(framing, verbose=args.verbose))

    print(f"\n{'='*60}", flush=True)
    for framing, ok in zip(FRAMINGS, passed):
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {framing}", flush=True)
    print(f"{'='*60}", flush=True)

    if not all(passed):
        sys.exit(1)


if __name__ == "__main__":
    main()
