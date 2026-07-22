# Brief: Java port of the ISO 8583 router, running in a Docker container

## Task

Port the ISO 8583 payment router built in `claude_exp/xv2` through `claude_exp/xv5` (all Python)
to Java, as a new challenge to test whether the spec's *architecture* — not just its Python
implementation — survives a language change. The router core must remain portable to C++ for
the performance-critical path, exactly like the Python version's own stated design principle
(see `claude_exp/xv2/build_router_v2.md`'s "Design principles (non-negotiable)" section).

Development happens via VSCode against files on the host, with the actual build/run/test cycle
executed inside a Docker container (bind-mount + `docker exec`, no `devcontainer.json`).

## Confirmed decisions

- **Scope**: port the router + simulators (crypto_host, downstream_host, upstream_host) — not
  the monitor dashboard yet. Single instance of each actor (no router_1.01/router_2/partner_b
  multi-instance scenario yet). Both are deferred to a later iteration once this slice is
  proven, mirroring how the Python lineage (xv2→xv5) itself grew incrementally.
- **ISO 8583 library**: [j8583](https://j8583.sourceforge.net/) (`net.sf.j8583:j8583` on Maven
  Central — note the Maven groupId differs from the library's own Java package name,
  `com.solab.iso8583`).
- **Crypto**: standard JCE (`javax.crypto`), no BouncyCastle — everything `crypto_utils.py` needs
  (triple-DES, single-DES, HMAC-SHA1) is in the default `SunJCE` provider on JDK ≥ 8u162.
- **Build tool**: Maven, single module, one shaded/fat jar.
- **Dev workflow**: bind-mount the project directory into a running container, edit on the host,
  build/run via `docker exec`. No `devcontainer.json`.
- **Container**: Dockerfile installs Java 21, Maven, and Node.js + `@anthropic-ai/claude-code`
  (matching this repo's existing container convention, e.g. `AnaCredit_c/.devcontainer/Dockerfile`,
  `claude_exp/duns_connect/Dockerfile`, so Claude Code can run from inside the container too).

## Concurrency model (C++ portability notes, mirroring `build_router_v2.md`)

Directly mirrors the Python design so the future C++ port needs no conceptual rewrite:

| Concept | Python (xv2-xv5) | Java (xv6java) | Future C++ |
|---|---|---|---|
| Per-connection I/O | thread-per-connection, blocking `socket` | one blocking daemon `Thread` per connection, `java.net.Socket`/`ServerSocket` | `std::thread` + blocking `recv`/`send` |
| Dispatcher queue | `queue.Queue(maxsize=N)` | `ArrayBlockingQueue` | `std::deque` + `std::mutex` + `std::condition_variable` |
| Worker pool | `threading.Thread` × `worker_threads` | fixed-size `ExecutorService` (or manual `Thread[]`) | thread pool |
| Pending-STAN map | `dict` + `threading.Lock` | `ConcurrentHashMap` (or `HashMap` + explicit lock) | `std::unordered_map` + mutex |
| Per-upstream write lock | `threading.Lock` | `ReentrantLock` | `std::mutex` |

`asyncio`/reactive frameworks are deliberately avoided in both ports for the same reason stated
in `build_router_v2.md`: blocking threads map 1:1 to a future C++ port; an event-loop model would
need a full conceptual rewrite.

## Reference implementation

`claude_exp/xv5/` is the reference Python implementation to port field-for-field: `router/*.py`,
`shared/*.py`, `simulators/*/main.py`, `test_spec.json`, `pans_defined.json`, `f47.json`,
`run_test.sh`, and `tests/*.py` are all direct behavioral references. Structural differences
introduced by the language/library switch (j8583's MTI-as-`setType()` instead of a `"t"` dict
key, automatic bitmap computation, per-MTI `<parse>` XML config instead of one flat field list,
Jackson's `@JsonIgnoreProperties(ignoreUnknown = true)` replacing the hand-maintained config
"exclusion set") are documented inline in the Java equivalents of the relevant modules.
