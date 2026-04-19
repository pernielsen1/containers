# Scanner Daemon Skill

Provide context and assistance for the file scanner daemon project located at `/home/perni/containers/claude_exp/scanner/`.

## What was built

A Python file-scanner daemon that monitors configured directories, detects new files, and processes them through pluggable action scripts.

## Architecture

### Core files
| File | Purpose |
|---|---|
| `scanner.py` | Daemon: discovery loop, file stability check, locking, processing pipeline |
| `config.json` | Scan interval, base dir, mirror dir names, list of watched dirs + actions |
| `upper.py` | Example action: converts file content to uppercase |

### Admin scripts
| Script | Purpose |
|---|---|
| `start_scanner.sh` | Start daemon in background (no install); process appears as `pn_scanner` in `ps aux` |
| `stop_scanner.sh` | Graceful stop via SIGTERM (waits for current file to finish) |
| `reload_scanner.sh` | Send SIGHUP — daemon reloads config at next scan cycle |
| `status_scanner.sh` | Show running daemon via `ps aux | grep pn_scanner` |
| `install_scanner.sh` | Install as systemd user service (Linux/WSL) or nohup fallback; Windows-aware |
| `test.sh` | Drop `hello.txt` into `to_upper/`; fails if file already exists |

## Processing pipeline

1. **Discovery** — file appears in a watched inbound directory
2. **Stability check** — file size must be unchanged between two consecutive scans (guards against partially-written large files)
3. **Lock check** — exclusive `flock` must succeed
4. **Rename** — assigned a unique name: `YYYYMMDD_HHMMSS_NNNN_originalname`
5. **Move to `pending/`**
6. **Invoke action script** — `python3 <action> <filepath>`
7. **Route result** — exit 0 → `log/`; non-zero → `failed/`

## Mirror directory structure

For each inbound dir the daemon maintains three mirrors:
```
pending/<rel_path>/   ← file being processed
log/<rel_path>/       ← completed successfully
failed/<rel_path>/    ← action returned non-zero exit code
```

Orphaned files in `pending/` are left for **manual inspection** — they indicate a broken action script or bad input and must not be auto-recovered.

## Action configuration

Each action script gets a directory under `actions/<name>/` with a `config.json`:
```
actions/
  upper/
    config.json   ← {"name": "upper", ...}  (created automatically on first run)
```
On daemon startup, missing action dirs are created with a minimal default config.

## Key resilience decisions made

- **Orphaned pending files**: manual intervention only — not auto-recovered
- **Reload latency** (SIGHUP): acceptable delay up to `scan_interval_seconds` — not worth fixing
- **Graceful shutdown**: SIGTERM sets flag; daemon finishes current file then exits cleanly within `shutdown_timeout_seconds` (default 30)
- **Duplicate log entries**: fixed — `StreamHandler` only added when stdout is a tty; suppressed when daemonized via nohup

## config.json reference

```json
{
    "scan_interval_seconds": 5,
    "shutdown_timeout_seconds": 30,
    "base_dir": "/path/to/scanner",
    "pending_dir": "pending",
    "log_dir": "log",
    "failed_dir": "failed",
    "directories": [
        {
            "path": "/path/to/inbound_dir",
            "action": "my_action.py"
        }
    ]
}
```

Inbound directory paths must not exceed 128 characters.

## Adding a new action

1. Write `my_action.py` — takes filepath as first argument, exits 0 on success
2. Add an entry to `config.json` under `directories`
3. Run `reload_scanner.sh` — daemon creates `actions/my_action/config.json` automatically
