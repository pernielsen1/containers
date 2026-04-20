#!/usr/bin/env python3
import sys
import urllib.request
import urllib.parse
import json
import base64

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5000"
INPUT = sys.argv[2] if len(sys.argv) > 2 else "hello world"
USERNAME, PASSWORD = "admin", "admin123"


def post(path, body=None, token=None):
    url = BASE_URL + path
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    else:
        creds = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


print("--- Login ---")
auth = post("/sys/v1/session/auth")
token = auth["access_token"]
print(f"Token: {token}")

print("\n--- Invoke upper_case plugin ---")
result = post("/crypto/v1/plugins/upper_case", {"input": INPUT}, token=token)
print(json.dumps(result, indent=2))
