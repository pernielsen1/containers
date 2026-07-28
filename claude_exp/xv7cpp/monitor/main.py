#!/usr/bin/env python3

import os
import sys
import json
import time
import requests
from pathlib import Path

def load_config(cfg_path):
    with open(cfg_path, 'r') as f:
        return json.load(f)

def get_stats(port, auth_token=None):
    try:
        headers = {}
        if auth_token:
            headers['X-Router-Auth'] = auth_token
        resp = requests.get(f"http://localhost:{port}/stats", headers=headers, timeout=2)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        return {"error": str(e)}

def get_logs(port):
    try:
        resp = requests.get(f"http://localhost:{port}/logs?format=text", timeout=2)
        return resp.text if resp.status_code == 200 else ""
    except Exception as e:
        return f"Error: {e}\n"

def main():
    if len(sys.argv) < 2:
        print("Usage: main.py <config.json>")
        sys.exit(1)

    cfg_path = sys.argv[1]
    if not os.path.exists(cfg_path):
        print(f"Config file not found: {cfg_path}")
        sys.exit(1)

    cfg = load_config(cfg_path)

    router_port = cfg.get("command_port", 8080)
    crypto_port = cfg.get("crypto", {}).get("port", 8081)
    auth_token = cfg.get("command_auth_token")

    print("=== xv7cpp Router Monitor ===\n")

    try:
        while True:
            print(f"[{time.strftime('%H:%M:%S')}] Stats:\n")

            router_stats = get_stats(router_port, auth_token)
            if router_stats:
                print("Router:")
                print(f"  sent: {router_stats.get('sent_total', 0)}")
                print(f"  recv: {router_stats.get('recv_total', 0)}")
                if "connections" in router_stats:
                    print("  connections: " + str(router_stats["connections"]))
                print()

            time.sleep(5)
            os.system("clear" if os.name == "posix" else "cls")

    except KeyboardInterrupt:
        print("\nMonitor stopped.")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
