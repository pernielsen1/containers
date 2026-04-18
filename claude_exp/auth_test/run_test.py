#!/usr/bin/env python3
"""Test driver: starts server and client, waits for completion."""

import subprocess
import sys
import time
import os

BASE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(BASE, "main.py")
PORT = 1042


def main():
    server = subprocess.Popen(
        [sys.executable, MAIN, "server", "--port", str(PORT)],
        cwd=BASE,
    )
    # Give server a moment to bind
    time.sleep(0.5)

    client = subprocess.Popen(
        [sys.executable, MAIN, "client", "--port", str(PORT)],
        cwd=BASE,
    )

    try:
        client.wait(timeout=60)
    except subprocess.TimeoutExpired:
        print("Client timed out", flush=True)
        client.kill()

    server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()

    results = os.path.join(BASE, "results.csv")
    if os.path.exists(results):
        print(f"Results written to {results}")
    else:
        print("No results file found")


if __name__ == "__main__":
    main()
