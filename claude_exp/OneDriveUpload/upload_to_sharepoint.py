"""
Upload a file to SharePoint using MSAL device-code authentication.

Usage:
    python3 upload_to_sharepoint.py --filename hello.txt
    python3 upload_to_sharepoint.py --filename hello.txt --input-dir upload --done-dir done --config config.json
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import msal
from office365.sharepoint.client_context import ClientContext


TOKEN_CACHE_FILE = ".token_cache.bin"


def load_config(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def get_unique_name(filename: str) -> str:
    """Return <stem>_<ISO-timestamp><suffix>, e.g. hello_2026-04-02T221530.txt"""
    p = Path(filename)
    timestamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    return f"{p.stem}_{timestamp}{p.suffix}"


def _build_msal_app(tenant_id: str, client_id: str) -> msal.PublicClientApplication:
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_FILE):
        cache.deserialize(open(TOKEN_CACHE_FILE).read())

    app = msal.PublicClientApplication(client_id, authority=authority, token_cache=cache)
    return app, cache


def acquire_token(tenant_id: str, client_id: str, sharepoint_url: str) -> str:
    """Return a valid access token, using cache or device-code flow."""
    host = urlparse(sharepoint_url).netloc          # e.g. company.sharepoint.com
    scopes = [f"https://{host}/AllSites.Write"]

    app, cache = _build_msal_app(tenant_id, client_id)

    # Try silent (cached) first
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(scopes, account=accounts[0])
        if result and "access_token" in result:
            _persist_cache(cache)
            return result["access_token"]

    # Device-code flow
    flow = app.initiate_device_flow(scopes=scopes)
    if "message" not in flow:
        raise RuntimeError(f"Device flow initiation failed: {flow}")
    print(f"\n{flow['message']}\n", flush=True)

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(f"Authentication failed: {result.get('error_description', result)}")

    _persist_cache(cache)
    return result["access_token"]


def _persist_cache(cache: msal.SerializableTokenCache):
    if cache.has_state_changed:
        with open(TOKEN_CACHE_FILE, "w") as f:
            f.write(cache.serialize())


def upload_file_to_sharepoint(config: dict, local_path: Path) -> None:
    """Upload local_path to the SharePoint target_folder defined in config."""
    sharepoint_url = config["sharepoint_url"]
    tenant_id = config["tenant_id"]
    client_id = config["client_id"]
    target_folder = config["target_folder"]   # e.g. "Documents/uploaded_files"

    token = acquire_token(tenant_id, client_id, sharepoint_url)

    def token_provider():
        return {"access_token": token, "token_type": "Bearer"}

    ctx = ClientContext(sharepoint_url).with_access_token(token_provider)

    with open(local_path, "rb") as fh:
        content = fh.read()

    folder = ctx.web.get_folder_by_server_relative_url(target_folder)
    folder.upload_file(local_path.name, content).execute_query()

    print(f"Uploaded '{local_path.name}' -> {sharepoint_url}/{target_folder}")


def run(input_dir: str, done_dir: str, filename: str, config_path: str) -> None:
    config = load_config(config_path)

    input_path = Path(input_dir) / filename
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    unique_name = get_unique_name(filename)
    renamed_path = input_path.parent / unique_name

    # Step 1 — rename with timestamp
    input_path.rename(renamed_path)
    print(f"Renamed: {filename} -> {unique_name}")

    try:
        # Step 2 — upload
        upload_file_to_sharepoint(config, renamed_path)
    except Exception:
        # Roll back rename so we don't lose the file
        renamed_path.rename(input_path)
        print("Upload failed; restored original filename.", file=sys.stderr)
        raise

    # Step 3 — move to done
    done_path = Path(done_dir)
    done_path.mkdir(parents=True, exist_ok=True)
    shutil.move(str(renamed_path), done_path / unique_name)
    print(f"Moved to '{done_dir}': {unique_name}")


def main():
    parser = argparse.ArgumentParser(description="Upload a file to SharePoint")
    parser.add_argument("--filename", required=True, help="Name of the file to upload")
    parser.add_argument("--input-dir", default="upload", help="Source directory (default: upload)")
    parser.add_argument("--done-dir", default="done", help="Archive directory (default: done)")
    parser.add_argument("--config", default="config.json", help="JSON config file (default: config.json)")
    args = parser.parse_args()

    run(args.input_dir, args.done_dir, args.filename, args.config)


if __name__ == "__main__":
    main()
