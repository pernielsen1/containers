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


def run_once(framing: str) -> bool:
    print(f"\n{'='*60}", flush=True)
    print(f"  Framing: {framing}", flush=True)
    print(f"{'='*60}", flush=True)

    server = subprocess.Popen(
        [sys.executable, MAIN, "server", "--port", str(PORT), "--framing", framing],
        cwd=BASE,
    )
    time.sleep(0.5)

    client = subprocess.Popen(
        [sys.executable, MAIN, "client", "--port", str(PORT), "--framing", framing],
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
    passed = []
    for framing in FRAMINGS:
        passed.append(run_once(framing))

    print(f"\n{'='*60}", flush=True)
    for framing, ok in zip(FRAMINGS, passed):
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {framing}", flush=True)
    print(f"{'='*60}", flush=True)

    if not all(passed):
        sys.exit(1)


if __name__ == "__main__":
    main()
