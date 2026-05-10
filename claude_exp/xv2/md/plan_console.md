# Plan: Monitor Console — Log Level Control & Log Viewer

## Overview

Two features added to the monitor UI, backed by new endpoints on every actor:

1. **Log level control** — change an actor's log level at runtime (DEBUG/INFO/WARNING/ERROR) via a dropdown on each card.
2. **Log viewer** — a modal window showing the actor's recent log output, with auto-refresh, scroll-to-bottom, and export-to-file.

---

## Phase 1 — `shared/log_buffer.py` (new file)

A `logging.Handler` subclass that keeps the last N formatted log lines in a `collections.deque`.

```python
class LogBuffer(logging.Handler):
    def __init__(self, maxlen=2000):
        super().__init__()
        self._lines = collections.deque(maxlen=maxlen)

    def emit(self, record):
        self._lines.append(self.format(record))

    def get_lines(self) -> list[str]:
        return list(self._lines)
```

Installed on the root logger with the same formatter as the existing `basicConfig` call (`"%(asctime)s [%(threadName)s] %(levelname)s %(message)s"`).

---

## Phase 2 — `shared/command_server.py`

`CommandServer.__init__` installs `LogBuffer` on the root logger and adds two built-in endpoints. All actors get these automatically — no changes to any `run()` function.

### `GET /log_level`
Returns current root-logger level:
```json
{"level": "DEBUG"}
```

### `POST /log_level`
Body: `{"level": "INFO"}` — sets root-logger level, returns updated level.
Valid values: `DEBUG`, `INFO`, `WARNING`, `ERROR`. Returns 400 on unknown level.

### `GET /logs`
Returns recent log lines as JSON array (newest last):
```json
["2026-05-06 ... INFO router: session started", "…"]
```
Query param `?format=text` returns plain text (newline-separated) for export download.

---

## Phase 3 — `monitor/main.py`

Add three proxy routes (same pattern as existing `/stats`, `/stop`):

```python
GET  /api/actor/<name>/log_level   → GET  actor:/log_level
POST /api/actor/<name>/log_level   → POST actor:/log_level  (body passthrough)
GET  /api/actor/<name>/logs        → GET  actor:/logs       (pass ?format=text param)
```

---

## Phase 4 — `monitor/static/index.html`

### 4a — Card footer additions

Each card's `card-foot` gains two new controls:

```
[ DEBUG ▾ ]   [ Logs ]   [ Start ]  [ Stop ]
```

- **Log level `<select>`**: options DEBUG / INFO / WARNING / ERROR. On page load the current level is fetched and pre-selected. On change, POSTs the new level to the actor. Disabled when actor is down.
- **Logs button** (`btn-blue btn-sm`): opens the log viewer modal for that actor.

### 4b — Log viewer modal

A single shared modal overlay (one instance, reused for all actors):

```
┌─────────────────────────────────────────────────────┐
│ Logs — router_1                          [×] Close  │
├─────────────────────────────────────────────────────┤
│ 2026-05-06 20:53:35 [ds-receiver] INFO ...          │
│ 2026-05-06 20:53:35 [worker-0]    DEBUG ...         │
│ …                                                   │
│                                                     │
│ (scrollable, monospace, ~400px tall)                │
├─────────────────────────────────────────────────────┤
│ [⟳ Refresh]  [⏬ Scroll to bottom]  [↓ Export]      │
│              ☐ Auto-refresh (2s)                    │
└─────────────────────────────────────────────────────┘
```

**Behaviour:**
- Opens with last N lines already loaded.
- Auto-refresh polls `/api/actor/<name>/logs` every 2s when ticked (default: on).
- "Scroll to bottom" scrolls the `<pre>` to the end.
- "Export" fetches `?format=text` and triggers a browser download as `<name>_<timestamp>.log`.
- Closing the modal stops the auto-refresh timer.

### 4c — New CSS

- `.modal-overlay` — full-screen backdrop (`rgba(0,0,0,0.6)`), flex-centered.
- `.modal` — dark panel, max-width 860px, border-radius, same colour palette as existing cards.
- `.log-pre` — monospace `<pre>`, fixed height 400px, overflow-y scroll, `#0f1117` background, `#86efac` text (green tint to distinguish from UI), font-size 0.72rem.
- Log level `<select>` on cards uses existing `select` style, width auto.

---

## File change summary

| File | Change |
|------|--------|
| `shared/log_buffer.py` | New — `LogBuffer` handler |
| `shared/command_server.py` | Install `LogBuffer`; add `/log_level` GET/POST and `/logs` GET |
| `monitor/main.py` | Add proxy routes for `log_level` and `logs` |
| `monitor/static/index.html` | Log level dropdown on cards; Logs button; modal viewer |
