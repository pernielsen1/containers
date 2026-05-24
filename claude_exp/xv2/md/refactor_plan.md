# Router Refactor Plan

## Goal

Clean up the router for long-term maintainability and to make a future port to C++
straightforward. The simulators (upstream, downstream, crypto) are throwaway test scaffolding —
the router is the production component.

---

## What's wrong now

### 1. Global mutable state
```python
_stan_counter = 0       # module-level counter
_stan_lock = threading.Lock()
```
Module globals break encapsulation and make testing hard. In C++ this would be a private
member of the owning class.

### 2. Implicit data schemas
Pending entries and upstream refs are raw dicts with undocumented keys:
```python
pending[router_stan] = {
    "up_conn": ..., "up_write_lock": ..., "upstream_stan": ...
}
upstream_ref = {"conn": None, "lock": None}   # mutable reference workaround
```
In C++ these would be structs. Even in Python they make the code harder to read
and impossible to validate statically.

### 3. God-function `run()` — 130 lines, does everything
- spawns threads
- manages reconnect loop
- sets up work queue
- tears everything down
- handles both server and client upstream modes

No single responsibility. The entire session lifecycle is inlined.

### 4. Business logic entangled with concurrency mechanics
`_process_request` takes 12 parameters — half are shared-state artefacts
(`pending_lock`, `ds_write_lock`, `reconnect_event`). The actual business
logic (STAN rewrite, crypto call, downstream send) is buried inside threading boilerplate.

### 5. Configuration passed as raw dicts everywhere
Every function receives `crypto_cfg`, `ims_cfg`, `up_framing` etc. as anonymous dicts.
No validation, no defaults, no type hints.

### 6. Two upstream modes (server/client) tangled in same loop
`run()` branches on `up_mode` mid-function. A C++ port would need to unpick
which parts are mode-specific before it can write clean virtual dispatch.

---

## Proposed Python structure

```
router/
├── main.py              # thin entry point: parse args, build config, run session loop
├── config.py            # RouterConfig dataclass — validates and holds all config
├── session.py           # RouterSession — one connected session (upstream + downstream)
├── dispatcher.py        # Dispatcher — worker pool + core routing logic
├── upstream.py          # UpstreamServer / UpstreamClient — one class each
├── downstream.py        # DownstreamConnection — IMS pair (to + from sockets)
└── crypto_client.py     # CryptoClient — HTTP calls to crypto_host
```

---

## Data types to define

Python dataclasses map directly to C++ structs:

```python
@dataclass
class RouterConfig:
    name: str
    command_port: int
    upstream_port: int          # or upstream_host/port in client mode
    upstream_mode: str          # "server" | "client"
    upstream_framing: Framing
    downstream_host: str
    downstream_port: int
    irm_id: bytes               # EBCDIC, 8 bytes
    client_id: bytes            # EBCDIC, 8 bytes
    crypto_host: str
    crypto_port: int
    worker_threads: int
    reestablish_seconds: int
    yellow_threshold_seconds: int

@dataclass
class PendingEntry:
    up_conn: socket.socket
    up_write_lock: threading.Lock
    upstream_stan: str

@dataclass
class RoutedMessage:
    req: dict                   # decoded ISO 8583
    up_conn: socket.socket
    up_write_lock: threading.Lock
    up_addr: tuple
```

**C++ equivalents:**
```cpp
struct PendingEntry {
    int              up_fd;
    std::mutex&      up_write_mutex;
    std::string      upstream_stan;
};

struct RoutedMessage {
    Iso8583Message   req;
    int              up_fd;
    std::mutex*      up_write_mutex;
    std::string      up_addr;
};
```

---

## Module responsibilities

### `config.py` — RouterConfig
- Load and validate `config.json`
- Resolve EBCDIC bytes for irm_id / client_id
- Hold defaults (worker_threads=8, reestablish_seconds=10, etc.)
- **C++ equivalent**: plain struct + factory function `RouterConfig::from_file(path)`;
  use nlohmann/json for parsing

### `crypto_client.py` — CryptoClient
- Single `validate(endpoint, pan, f47) → str`
- Owns the HTTP session (keep-alive)
- Timeout / fallback (return original f47 on failure)
- **C++ equivalent**: class wrapping libcurl or cpp-httplib; one instance shared across workers
  via `std::shared_ptr<CryptoClient>`; mutex-protected if libcurl handle is not thread-safe

### `dispatcher.py` — Dispatcher
- Owns: STAN generator, pending map (`std::unordered_map`), worker thread pool, work queue
- `submit(msg: RoutedMessage)` — enqueue
- `process(msg)` — crypto call → STAN rewrite → downstream write → pending insert
- `handle_response(resp)` — look up pending → crypto validate → upstream write
- Fires `reconnect_event` on downstream write failure
- **C++ equivalent**: class with `std::thread` pool, `std::queue<RoutedMessage>` protected by
  `std::mutex` + `std::condition_variable`; pending map protected by separate mutex

### `downstream.py` — DownstreamConnection
- `connect(host, port, ims_cfg) → DownstreamConnection`
- Handles IMS handshake (resume TPIPE, pipe-cleaner ping)
- Exposes `send(frame)` (with internal write mutex) and `recv() → bytes`
- Owns `from_fd` and `to_fd`
- **C++ equivalent**: RAII class; destructor closes both sockets; `send()` acquires
  `std::unique_lock<std::mutex>`

### `upstream.py` — two classes
- `UpstreamServer(port, framing)` — `accept() → UpstreamConn`
- `UpstreamClient(host, port, framing, retry_seconds)` — `connect() → UpstreamConn`
- Both yield objects with `read_message()` / `write_message()` interface
- **C++ equivalent**: abstract `IUpstreamFactory` with `ServerFactory` and `ClientFactory`
  subclasses; clean virtual dispatch

### `session.py` — RouterSession
- Owns one connected (upstream + downstream + dispatcher) triple
- `run_until_disconnect()` — blocks until any component signals reconnect
- Handles graceful teardown: drain queue, close sockets, join threads
- **C++ equivalent**: RAII class; destructor joins threads and closes sockets in correct order;
  `std::atomic<bool> reconnect_flag` shared across components

### `main.py` — entry point only
```python
cfg = RouterConfig.from_file(args.config)
cmd = CommandServer(cfg.command_port, stats, stop_event)
cmd.start()
while not stop_event.is_set():
    try:
        session = RouterSession.connect(cfg, stats, stop_event)
        session.run_until_disconnect()
    except OSError:
        stop_event.wait(timeout=cfg.reestablish_seconds)
```
- **C++ equivalent**: `main()` with identical while-loop; `std::atomic<bool> stop_flag`
  set by SIGTERM handler

---

## Threading model

| Concern               | Current Python                | Clean Python              | C++                               |
|-----------------------|-------------------------------|---------------------------|-----------------------------------|
| Upstream reads        | thread per connection         | same                      | `std::thread` per connection      |
| Downstream reads      | one `ds-receiver` thread      | owned by RouterSession    | `std::thread`, RAII-joined        |
| Request processing    | fixed thread pool + queue     | Dispatcher pool           | `std::thread` pool + `std::queue` |
| Crypto HTTP calls     | blocking inside worker        | CryptoClient (blocking)   | blocking libcurl / cpp-httplib    |
| Reconnect loop        | inline in `run()`             | main.py while loop        | `main()` while loop               |
| Shared stats          | Stats class + threading.Lock  | unchanged                 | `Stats` class + `std::mutex`      |
| Reconnect signal      | `threading.Event`             | same                      | `std::atomic<bool>`               |

**Good news**: the thread-per-connection model with blocking I/O is completely idiomatic C++.
Unlike Rust (which pushes toward async/tokio), C++ is equally happy with blocking threads.
The Python refactor maps almost one-to-one without an async rewrite.

---

## C++ library choices

| Need                  | Library                                      |
|-----------------------|----------------------------------------------|
| JSON config           | nlohmann/json (header-only)                  |
| HTTP client           | cpp-httplib (header-only) or libcurl         |
| ISO 8583              | custom (port `shared/iso_utils.py` + spec)   |
| EBCDIC codec          | custom (port `shared/ims_connect.py`)        |
| Logging               | spdlog (header-only)                         |
| Command server (ops)  | cpp-httplib embedded server                  |
| Build                 | CMake                                        |

All header-only options mean no build complexity for the core router.

---

## What not to refactor (maps cleanly to C++ as-is)

| Python module            | C++ equivalent                             |
|--------------------------|--------------------------------------------|
| `shared/framing.py`      | Free functions on raw socket fd             |
| `shared/ims_connect.py`  | Namespace `ims_connect` with free functions |
| `shared/iso_utils.py`    | Namespace `iso8583` with free functions     |
| `shared/stats.py`        | `Stats` class + `std::mutex`               |
| `shared/command_server.py` | Not needed in C++ (ops tooling only)     |

---

## Suggested order of work

1. **`config.py`** — dataclass + validation, no logic change. Immediate clarity win.
2. **`crypto_client.py`** — extract `_crypto_call` into a class. Easy, isolated.
3. **`dispatcher.py`** — extract `_process_request` + `_worker` + STAN + pending map.
4. **`downstream.py`** — wrap `_connect_downstream_ims` + write lock.
5. **`upstream.py`** — extract server and client loops into two classes.
6. **`session.py`** — assemble the above; clean teardown order.
7. **`main.py`** — reduce to ~15 lines.

Each step is independently testable. No behaviour changes.

---

## Port readiness checklist (after refactor)

- [ ] No module globals — all state owned by a class
- [ ] All function signatures ≤ 4 parameters (pass `self`)
- [ ] All dict schemas replaced with dataclasses
- [ ] Protocol logic (IMS framing, EBCDIC) isolated from routing logic
- [ ] ISO 8583 access wrapped behind an interface (not raw `iso8583` lib calls inline)
- [ ] Threading model documented per component
- [ ] Unit tests for Dispatcher with mocked upstream + downstream
- [ ] Teardown order documented (workers drain → downstream closes → upstream closes)
