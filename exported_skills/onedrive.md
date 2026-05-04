# OneDrive / SharePoint Upload

You are working on the **OneDrive/SharePoint file upload** project. Use the knowledge below to assist accurately.

---

## What this project does

Uploads a single file to a SharePoint/OneDrive location using the currently logged-on Microsoft account.
Before uploading, the file is renamed with an ISO timestamp suffix. After uploading it is moved to a `done/` directory.
Authentication uses MSAL device-code flow (browser pop-up on first run; token cached in `.token_cache.bin` for subsequent runs).

---

## Project Files

All files are under `/home/perni/containers/claude_exp/OneDriveUpload/`:

| File | Purpose |
|------|---------|
| `upload_to_sharepoint.py` | Main script — rename, upload, archive |
| `config.json` | Config template (placeholder values) |
| `config_this_user.json` | Pre-filled config for `per.nielsen1@outlook.com` — still needs `client_id` and `sharepoint_url` |
| `test_upload.py` | Unit tests (mocked) + integration test (real SharePoint) |
| `requirements.txt` | `Office365-REST-Python-Client`, `msal`, `pytest` |
| `pytest.ini` | Marks `unit` and `integration` |
| `upload/hello.txt` | Test input file |
| `done/` | Archived files land here after upload |
| `.token_cache.bin` | MSAL token cache (auto-created; gitignore it) |

---

## Configuration (`config.json`)

```json
{
    "sharepoint_url": "https://HANDLE-my.sharepoint.com/personal/per_nielsen1_outlook_com",
    "tenant_id":      "9188040d-6c67-4c5b-b112-36a304b66dad",
    "client_id":      "REGISTER-APP-IN-AZURE-PORTAL",
    "target_folder":  "Documents/uploaded_files"
}
```

**Known values for this machine:**

| Field | Value |
|-------|-------|
| `user_email` | `per.nielsen1@outlook.com` |
| `tenant_id` | `9188040d-6c67-4c5b-b112-36a304b66dad` (MSA consumer tenant — fixed) |
| `onedrive_cid` | `a88215cb98efcb80` |

**Still needed:**

- **`client_id`** — Register a free app at [portal.azure.com](https://portal.azure.com) → *App registrations → New*. Add delegated permission `Files.ReadWrite` (Microsoft Graph). Redirect URI: `http://localhost`.
- **`sharepoint_url`** — Personal OneDrive "mysite" URL. Find it by opening [onedrive.live.com](https://onedrive.live.com) — the URL bar shows it (format: `https://HANDLE-my.sharepoint.com/personal/...`).

---

## CLI Usage

```bash
cd /home/perni/containers/claude_exp/OneDriveUpload

# Basic (uses defaults: --input-dir upload --done-dir done --config config.json)
python3 upload_to_sharepoint.py --filename hello.txt

# Explicit
python3 upload_to_sharepoint.py \
    --filename hello.txt \
    --input-dir upload \
    --done-dir done \
    --config config_this_user.json
```

**What happens:**
1. `upload/hello.txt` → renamed to `upload/hello_2026-04-02T221530.txt`
2. File uploaded to SharePoint `Documents/uploaded_files/`
3. Renamed file moved to `done/hello_2026-04-02T221530.txt`
4. On upload failure: original filename restored in `upload/`

First run triggers MSAL device-code auth: visit `https://microsoft.com/devicelogin`, enter the printed code.

---

## Tests

```bash
# Unit tests only (no network, fast)
python3 -m pytest test_upload.py -v -m unit

# Integration test (real SharePoint — needs filled config.json + network)
python3 -m pytest test_upload.py -v -m integration

# All
python3 -m pytest test_upload.py -v
```

**Unit test coverage:**
- `get_unique_name`: timestamp format, no-extension, multi-dot, uniqueness
- `load_config`: key loading, missing file error
- `run()`: happy path, upload failure rolls back rename, missing input raises

**Integration test** (`TestIntegration.test_upload_hello_txt`):
- Uploads `hello.txt` to real SharePoint
- Verifies `done/` contains the renamed file
- `teardown_method` restores `upload/hello.txt` and clears `done/`

---

## Key Design Decisions

- **Unique name format**: `{stem}_{YYYY-MM-DDTHHMMSS}{suffix}` — colons removed for cross-platform filename safety
- **Rollback on failure**: `upload/hello.txt` is restored if upload throws; nothing is lost
- **Token caching**: `.token_cache.bin` — delete it to force re-authentication
- **Account type**: This machine has a personal MSA (`per.nielsen1@outlook.com`), not a corporate Azure AD account. `Office365-REST-Python-Client` works with personal OneDrive via the consumer tenant (`9188040d-6c67-4c5b-b112-36a304b66dad`).

---

## Dependencies

```bash
pip3 install -r requirements.txt
# Office365-REST-Python-Client>=2.5.0
# msal>=1.28.0
# pytest>=8.0.0
```
