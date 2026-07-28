# ISO 8583 Router — Build Specification: C++ core in a container + Python monitor on the host

## Purpose

Build a router that routes ISO 8583 payment messages between one or more upstream clients (card
networks/acquirers) and a downstream IMS Connect host (authorization system), with a crypto host
handling EMV cryptographic validation and a web dashboard managing/observing all components. The
router, and the three simulators standing in for real systems (crypto host, downstream host,
upstream host), are **C++**, built and run inside a Docker container. The web dashboard is
**Python**, running on the host, talking to every actor over plain HTTP.

This is a from-scratch C++ port of a working Java implementation of the same system
(`build_router_target.md`, in this same directory). That document remains the reference for
*behavior* — wire formats, message flows, config semantics, and the non-negotiable design
principles below are unchanged. This document is self-contained for *building* the C++ version:
library choices, module layout, and every place the C++ toolchain forces a different concrete
mechanism than the JVM are specified below. No access to the Java project's source is required to
build this one, though the Java doc's "C++ portability notes" section was the starting point for
every concurrency decision here.

**Deliberate deltas from the Java version** (decided up front, not discovered mid-build):
- No `j8583` equivalent exists in C++, and none is used — see "ISO 8583 codec" below: a hand-rolled
  bitmap-driven encoder/decoder replaces both `j8583` and `config/test_spec.xml` entirely.
- No JDK-builtin HTTP server/EBCDIC charset/JCE equivalent exists — `cpp-httplib`, a hand-written
  CP500 table, and OpenSSL fill those roles respectively (see "Libraries" below).
- This is a **direct 1:1 port** of the Java concurrency model (thread-per-connection, one mutex per
  shared structure, linear-scan reaper, polled stop signal) — the sharded pending-map, min-heap
  reaper, and edge-triggered wake described as *future* work in the Java doc's portability notes
  are intentionally **not** built here. Get this version correct and tested first.
- Same port assignments and `--network host` container model as the Java version — this project
  (container name `xv7cpp`) is a drop-in replacement, not a side-by-side variant. It cannot run at
  the same time as a live `xv6java` container.

### Design principles (non-negotiable — unchanged from the Java doc)

- **No process exits without releasing its sockets.** A malfunctioning actor must never retain a
  lock on a TCP port — all socket close paths run even on error/exception exit.
- **The router must not stall on crypto calls.** Each upstream connection accepts the next message
  as soon as the current one is handed to a worker — it does not block waiting for that worker's
  crypto-host round-trip to finish. `Dispatcher` is a bounded worker pool with a configurable
  worker-thread count, not a thread-per-message design.
- **Bounded resources, not unbounded growth.** The dispatcher queue and the in-flight pending map
  must have a ceiling. When overloaded, `submit()` blocks rather than growing without limit.
- **Command APIs default to localhost, and mutating routes are gate-able behind a shared secret.**
  `/stop`, `/log_level`, and `/dispatcher/purge` must not be reachable by default from anything
  other than the monitor on the same host.
- **Daemon threads that are the sole reader of a connection must never die silently.** Any
  exception inside the downstream-receiver or an upstream read thread that is not caught and
  logged will leave the session in a broken state with no diagnostic output.
- **`shutdown()` before `close()`.** Unlike the JVM, C++ gives no safety net around closing a socket
  another thread is blocked reading from — see "Teardown" under Shared modules.

---

## Repository layout

```
project/
├── CMakeLists.txt                 # single CMake project, four actor executables + shared libs
├── Dockerfile                     # Ubuntu + g++/clang (C++20) + CMake + OpenSSL dev + Node/Claude Code CLI
├── start.sh / stop.sh             # container lifecycle (bind-mount + docker exec, no devcontainer.json)
├── dockerstart.sh                 # ensures the Docker daemon itself is running
├── terminal.sh                    # interactive shell into the running container
├── run_test.sh                    # end-to-end CLI driver, run on the HOST
├── monitor_start.sh / monitor_stop.sh   # dashboard lifecycle, run on the HOST
├── config/
│   ├── pans_defined.json          # card + key data for simulators and crypto host
│   ├── f47.json                   # documents the field-47 JSON schema (reference only)
│   ├── router_1.json
│   ├── crypto_host.json
│   ├── downstream_host.json
│   ├── upstream_1.json
│   └── upstream_1_input/          # gitignored; test_cases.csv lives here at runtime
├── test_csv_files/
│   └── test.csv
├── monitor/                       # Python, runs on the HOST — unchanged from the Java project
│   ├── main.py
│   └── static/index.html
├── src/
│   ├── shared/         framing.{h,cpp}, ebcdic.{h,cpp}, ims_connect.{h,cpp}, iso_codec.{h,cpp},
│   │                   stats.{h,cpp}, stop_event.h, log.{h,cpp}, command_server.{h,cpp},
│   │                   crypto_utils.{h,cpp}
│   ├── router/         router_config.{h,cpp}, upstream.{h,cpp}, downstream_connection.{h,cpp},
│   │                   crypto_client.{h,cpp}, dispatcher.{h,cpp}, router_session.{h,cpp},
│   │                   router_main.cpp
│   └── simulators/{crypto_host,downstream_host,upstream_host}/*.cpp
├── test/               Catch2 unit + integration tests
├── third_party/        FetchContent cache dir for vendored headers (gitignored)
└── logs/               gitignored; per-actor console logs written at runtime
```

Every actor is its own executable, all linking a common static library for shared code (`xv6_shared`)
and the router-specific pieces linking `xv6_router` as well. There is no single "jar with many
main classes" equivalent here — CMake's natural idiom is one executable target per actor:

```
router          <- xv6_router, xv6_shared
crypto_host     <- xv6_shared
downstream_host <- xv6_shared
upstream_host   <- xv6_shared
xv6_tests       <- xv6_router, xv6_shared, Catch2   (built by `ctest`, not shipped as an actor)
```

Scope: router + simulators (crypto_host, downstream_host, upstream_host), single instance of each.
No multi-instance scenario — deferred, same as the Java version.

---

## Libraries

| Purpose | Library | Why |
|---|---|---|
| HTTP server (CommandServer + crypto_host's REST route) and HTTP client (CryptoClient's outbound calls) | [`cpp-httplib`](https://github.com/yhirose/cpp-httplib) | Single header, covers both server and client roles (Java needed `com.sun.net.httpserver` for the server side and `java.net.http.HttpClient` for the client side — one library replaces both here). Built-in multipart/form-data parsing covers the `/upload` route without hand-rolling one. |
| JSON (config files + wire bodies) | [`nlohmann/json`](https://github.com/nlohmann/json) | Single header, ubiquitous, trivial `NLOHMANN_DEFINE_TYPE_*` macros for struct (de)serialization. |
| Crypto (3DES/DES ECB, HMAC-SHA1) | OpenSSL (`libssl`/`libcrypto`, EVP API) | `EVP_des_ede3` covers DESede; `EVP_des_ecb` covers single-DES; `HMAC` with `EVP_sha1()` covers AAV. Present in every mainstream Linux distro's package manager — no vendoring needed. |
| Unit/integration tests | [`Catch2`](https://github.com/catchorg/Catch2) v3 | Header-mostly, BDD-style `SECTION`s read well for the same kind of round-trip/resilience tests the Java doc's JUnit 5 suite specifies, trivial CMake integration via `FetchContent` + `CTest`. |

`cpp-httplib`, `nlohmann/json`, and `Catch2` are pulled via CMake `FetchContent` (pinned to a
specific tagged release each, vendored into `third_party/` at configure time — not a live network
fetch on every build once the FetchContent cache is warm). OpenSSL is a system dependency
(`apt-get install libssl-dev`), located via `find_package(OpenSSL REQUIRED)`.

**Monitor (Python, host-side) dependencies**: unchanged from the Java project — `flask`, `requests`.

---

## `CMakeLists.txt` (shape)

```cmake
cmake_minimum_required(VERSION 3.20)
project(xv7cpp CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(OpenSSL REQUIRED)
find_package(Threads REQUIRED)

include(FetchContent)
FetchContent_Declare(httplib GIT_REPOSITORY https://github.com/yhirose/cpp-httplib.git GIT_TAG v0.15.3)
FetchContent_Declare(json    GIT_REPOSITORY https://github.com/nlohmann/json.git       GIT_TAG v3.11.3)
FetchContent_Declare(catch2  GIT_REPOSITORY https://github.com/catchorg/Catch2.git      GIT_TAG v3.5.4)
FetchContent_MakeAvailable(httplib json catch2)

add_library(xv6_shared STATIC
    src/shared/framing.cpp src/shared/ebcdic.cpp src/shared/ims_connect.cpp
    src/shared/iso_codec.cpp src/shared/stats.cpp src/shared/log.cpp
    src/shared/command_server.cpp src/shared/crypto_utils.cpp)
target_link_libraries(xv6_shared PUBLIC httplib nlohmann_json::nlohmann_json
                                          OpenSSL::SSL OpenSSL::Crypto Threads::Threads)

add_library(xv6_router STATIC
    src/router/router_config.cpp src/router/upstream.cpp src/router/downstream_connection.cpp
    src/router/crypto_client.cpp src/router/dispatcher.cpp src/router/router_session.cpp)
target_link_libraries(xv6_router PUBLIC xv6_shared)

add_executable(router               src/router/router_main.cpp)
add_executable(crypto_host          src/simulators/crypto_host/main.cpp)
add_executable(downstream_host      src/simulators/downstream_host/main.cpp)
add_executable(upstream_host        src/simulators/upstream_host/main.cpp)
target_link_libraries(router          PRIVATE xv6_router)
target_link_libraries(crypto_host     PRIVATE xv6_shared)
target_link_libraries(downstream_host PRIVATE xv6_shared)
target_link_libraries(upstream_host   PRIVATE xv6_shared)

enable_testing()
add_executable(xv6_tests test/*.cpp)
target_link_libraries(xv6_tests PRIVATE xv6_router xv6_shared Catch2::Catch2WithMain)
include(CTest)
include(Catch)
catch_discover_tests(xv6_tests)
```

Build: `cmake -S . -B build && cmake --build build -j` produces `build/router`,
`build/crypto_host`, `build/downstream_host`, `build/upstream_host`, `build/xv6_tests`.

---

## Shared modules (`src/shared/`)

### `framing.h` — length-prefixed TCP framing

Direct port of the Java `Framing` class; same config shape, same semantics.

```cpp
struct FramingConfig {
    std::string header_hex;                    // may be empty
    enum class LengthFieldType { BigEndian, LittleEndian, Ascii, Ebcdic } length_field_type;
    int length_field_bytes;
    int max_message_bytes = 65536;
};

std::vector<uint8_t> read_message(int fd, const FramingConfig& cfg);   // throws FramingError
void write_message(int fd, const std::vector<uint8_t>& data, const FramingConfig& cfg);
```

`read_message` reads the optional fixed header (hex-decoded), reads the length field, decodes it
per `length_field_type`, then reads exactly that many payload bytes via an internal `recv_exact(fd,
n)` that loops on `::recv()` until `n` bytes are collected. `recv_exact` throws immediately if the
decoded length exceeds `max_message_bytes` — fail fast on a corrupt/hostile length field rather
than blocking on bytes that may never arrive. A `0`-byte return from `::recv()` (remote EOF) or a
negative return with `errno != EINTR` throws `FramingError` (a plain exception carrying `errno`
where applicable) — this is the C++ equivalent of Java's "IOException covers both a remote
disconnect and a local socket close racing a blocked read," since POSIX `recv()` on a socket
`shutdown()`/`close()`d by another thread also unblocks with either `0` or an error, which
`recv_exact` maps the same way.

ASCII/EBCDIC length-field encoding is zero-padded decimal text of width `length_field_bytes` (e.g.
4-byte ASCII length field for a 37-byte payload → `"0037"`, encoded via `ebcdic.h` for the EBCDIC
case). BIG_ENDIAN/LITTLE_ENDIAN encode the length as raw bytes of the given width.

```cpp
FramingConfig::LengthFieldType parse_length_field_type(const std::string& name);
    // Exact-match only, case-sensitive: "BIG_ENDIAN", "LITTLE_ENDIAN", "ASCII", "EBCDIC".
    // Throws std::invalid_argument on anything else, including a differently-cased spelling
    // like "Ascii" or "ascii" -- there is no case-insensitive fallback.
```

**Pitfall — this throws from inside `RouterConfig::from_file`, at config-load time, which every one
of the four binaries calls before doing anything else.** A single wrongly-cased
`"length_field_type"` value in the one shared config file (e.g. `"Ascii"` instead of `"ASCII"`) is
therefore not a router-only failure — `router_main`, `crypto_host`, `downstream_host`, and
`upstream_host` all load the *same* file and all fail identically: each logs one line
(`fatal: unknown length_field_type: Ascii`, still visible even though this happens before
`Logger::set_level` runs, since the default level is `Info` and `LOG_ERROR` clears that threshold)
and exits with code 1. From the monitor's perspective this looks the same as "actor hasn't started
listening yet" until someone actually reads the per-actor log file, so it's worth checking logs
first, not last, when every actor's `/stats` poll fails at once right after a config edit. When
writing or editing `router_1.json` by hand, match the casing shown in the config schema example
above exactly.

### `ebcdic.h` — IBM code page 500 (CP500) table

C++ ships no built-in EBCDIC charset — Java's `Cp500` must be replaced with an explicit 256-entry
lookup table in both directions (`ascii_to_ebcdic[256]`, `ebcdic_to_ascii[256]`), using the standard
IBM CP500 mapping (a public, standardized code page — not project-specific data). Only two
functions are exposed; everything else in the project goes through them:

```cpp
std::vector<uint8_t> to_ebcdic(const std::string& s, size_t length);
    // EBCDIC-encode; left-pad with EBCDIC space (0x40) or right-truncate (keeping the tail) to
    // exactly `length` bytes — same padding/truncation rule as the Java version's toEbcdic.
std::string from_ebcdic(const std::vector<uint8_t>& bytes);
```

Only the subset of CP500 actually exercised by this project (digits, uppercase A–Z, space, and the
handful of punctuation characters appearing in `PING0001`/`TRAN`/client-id strings) needs to be
verified correct by the round-trip test in `test/`, but the full 256-entry table is specified for
correctness regardless of what's exercised today.

### `ims_connect.h` — IMS Connect wire protocol

Direct port of the Java `ImsConnect` class — same field layout, same offsets, same defaults.

```cpp
constexpr int IRM_HEADER_LEN = 28;
extern const std::vector<uint8_t> PING_TRANSCODE;   // to_ebcdic("PING0001", 8)

std::vector<uint8_t> build_frame(int irm_f0, const std::vector<uint8_t>& irm_id,
                                  const std::vector<uint8_t>& client_id, const std::string& mti,
                                  const std::vector<uint8_t>& data,
                                  const std::vector<uint8_t>& transcode = {});
    // irm_f0=0x80 -> resume TPIPE (no data). irm_f0=0x00 -> normal request.
    // transcode defaults to to_ebcdic("TRAN" + mti, 8) when data is non-empty and transcode is empty.

void write_response(int fd, const std::vector<uint8_t>& data);   // 4-byte big-endian length + data
std::vector<uint8_t> read_response(int fd);                       // strips the length prefix

struct ImsRequest { int irm_f0; std::vector<uint8_t> client_id, transcode, iso_data; };
ImsRequest read_request(int fd);
```

Wire format of `build_frame`'s output — byte-for-byte identical to the Java version:

```
[4B: payload_len big-endian]           # = 28 (header) + trailer.length
[2B: IRM_HEADER_LEN=28 big-endian]
[1B: 0x04]
[1B: irm_f0]
[8B: irm_id EBCDIC]
[4B: 0x00 0x00 0x00 0x00]              # IRM_NAK_RSNCDE(2) + IRM_RES(2)
[4B: 0x00 0x15 0x10 0x01]              # IRM_F5, IRM_TIMER, IRM_SOCT, IRM_ES
[8B: client_id EBCDIC]
[8B: transcode EBCDIC]                  # only when data present
[N bytes: iso_data]                     # only when data present
```

`read_request` parses `irm_f0` from payload byte offset 3, `client_id` from bytes 20–28 (relative to
the 28-byte header start), and everything past byte 28 as `transcode` (first 8 bytes) + `iso_data`
(rest) when present.

### `iso_codec.h` — hand-rolled ISO 8583 encode/decode

**No `j8583` equivalent is used.** Every decoded/encoded message is a `std::map<std::string,
std::string>` — key `"t"` for the MTI (4-digit string, e.g. `"0100"`), field numbers as string keys
(e.g. `"2"`, `"11"`) — the exact same shape the Java version normalizes down to via `IsoUtils`.

```cpp
enum class IsoType { Alpha, Llvar, Lllvar, Binary, Lllbin };
struct FieldSpec { IsoType type; int length; };   // length is 0 for LLVAR/LLLVAR/LLLBIN (variable)

// compile-time table — the sole source of truth for field shape, mirroring Java's FIELD_SPECS:
constexpr std::array<std::pair<int, FieldSpec>, 12> FIELD_SPECS = {{
    {2,  {IsoType::Llvar, 0}},   {3,  {IsoType::Alpha, 6}},   {4,  {IsoType::Alpha, 12}},
    {11, {IsoType::Alpha, 6}},   {14, {IsoType::Alpha, 4}},   {24, {IsoType::Alpha, 3}},
    {37, {IsoType::Alpha, 12}},  {38, {IsoType::Alpha, 6}},   {39, {IsoType::Alpha, 2}},
    {41, {IsoType::Alpha, 8}},   {42, {IsoType::Alpha, 15}},  {47, {IsoType::Lllvar, 0}},
}};
// Fields 52/55 are intentionally absent — same reasoning as the Java doc: nothing in this
// project ever sets them as top-level ISO fields; all PIN/ICC data travels inside field 47's
// JSON blob (see f47.json below). Because decoding here is bitmap-driven rather than
// XML-declared, there is no separate "declared for schema completeness" step to mirror at all.

std::vector<uint8_t> encode(const std::map<std::string, std::string>& data);
    // 1. type = strtol(data.at("t"), nullptr, 16) -> 2-byte MTI on the wire (binary, e.g. 0x0100).
    // 2. Build the bitmap: for every field in FIELD_SPECS present in `data` (ascending field
    //    number), set that bit. Bit 1 (secondary bitmap present) is set automatically if any
    //    field > 64 is present; this project's field set never exceeds 64, so the primary
    //    bitmap alone always suffices today, but the encoder still emits a correct secondary
    //    bitmap if a future field addition ever needs one.
    // 3. Write: 2-byte MTI, 8-byte (or 16-byte) bitmap, then each present field's value encoded
    //    per its FieldSpec, in ascending field-number order:
    //      ALPHA:  fixed `length` bytes, space-padded/truncated
    //      LLVAR:  2-digit ASCII decimal length prefix + value bytes
    //      LLLVAR: 3-digit ASCII decimal length prefix + value bytes
    //      BINARY: fixed `length` bytes, zero-padded/truncated (unused today; specified for parity)
    //      LLLBIN: 3-digit ASCII decimal length prefix + raw bytes (unused today; specified for parity)

std::map<std::string, std::string> decode(const std::vector<uint8_t>& bytes);
    // 1. Read 2-byte MTI -> data["t"] = 4-hex-digit lowercase string (same "%04x of the raw
    //    16-bit value" convention as the Java version's hex-MTI pitfall — see below).
    // 2. Read the 8-byte primary bitmap; if bit 1 is set, read the 8-byte secondary bitmap too.
    // 3. For each set bit (2..128), look up FIELD_SPECS[bit]; if absent from the table, throw
    //    (an unknown field number appearing on the wire is a hard decode error, not silently
    //    skipped — the Java version can't hit this case since j8583 only ever sets bits for
    //    fields the caller told it about, but a hand-rolled decoder must reject the case
    //    explicitly rather than reading garbage past a field it doesn't understand the length of).
    // 4. Decode that field's value per its type/length (ALPHA/BINARY: fixed width; LLVAR/LLLVAR/
    //    LLLBIN: read the N-digit length prefix, then that many bytes) and insert into the map.

bool is_known_field(const std::string& key);   // true if key parses as an int present in FIELD_SPECS
std::vector<uint8_t> build_0800();                              // {"t":"0800","24":"100"}
std::vector<uint8_t> build_0810(const std::string& f24);        // {"t":"0810","24":f24}
std::string f47_encode(const nlohmann::json& data);              // JSON serialize
nlohmann::json f47_decode(const std::string& value);              // JSON parse; {} on error/blank
```

**Why no per-MTI declaration file (dropping `test_spec.xml`)**: ISO 8583 is self-describing on the
wire — the bitmap says exactly which fields are present, so decoding only ever needs "field N →
(type, length)," which the single `FIELD_SPECS` table above already provides. The Java version's
XML file exists only because `j8583`'s `ConfigParser`/`MessageFactory` API requires a per-MTI
template to construct an `IsoMessage`; encoding in the Java version *never actually consults it*
(`IsoUtils.fromMap` walks `FIELD_SPECS` against the data map's own keys, exactly as `encode` above
does). Since this project has no such library, there is nothing forcing a per-MTI file to exist,
and one is deliberately not built. The tradeoff accepted: a message carrying a field number it
"shouldn't" for its MTI decodes silently rather than being flagged — nothing in `Dispatcher` or
`RouterSession` relies on catching that case, so this is judged not to matter for this project's
scope.

**Critical pitfall — MTI is hex, not decimal (carried over unchanged).** MTI `"0100"` is
represented on the wire as the 16-bit value `0x0100` (256 decimal), and `decode` must format it
back with `snprintf("%04x", ...)`/equivalent — using decimal formatting here silently produces the
wrong MTI string the moment a genuinely different MTI (hex digits ≠ decimal digits, e.g. any MTI
containing an 8/9 in a position where hex and decimal diverge) is round-tripped. `encode` must parse
`data.at("t")` with base 16 to match. This pitfall is *more* dangerous in the hand-rolled C++ codec
than in the Java version, because there is no `j8583` type system silently making "hex vs. decimal"
a fixed part of the `IsoMessage.getType()` contract — a C++ implementer reaching for `std::stoi`
(base 10) instead of `std::stoi(s, nullptr, 16)` will not get a compiler or library error, just
wrong wire bytes on the first non-trivial MTI. The round-trip unit test in `test/` must exercise at
least one MTI where hex and decimal digit strings diverge (any MTI is fine, since all the MTIs used
in this project happen to have the same digit string in hex and decimal — `0100`, `0110`, etc. are
themselves decimal-looking hex too, so the test must use a deliberately chosen non-matching value,
e.g. encode/decode the raw 16-bit value `0x0100` and assert the *string* is `"0100"`, not rely on
using one of this project's real MTIs to catch the bug, since none of them would expose it).

### `f47.json` (field-47 JSON schema — reference documentation, unchanged from the Java doc)

Field 47 carries everything `crypto_host` needs in one JSON blob, round-tripped via
`iso_codec::f47_encode`/`f47_decode`. Schema is identical to the Java version's `f47.json` — see
that file's contents (reproduced here for self-containedness):

```json
{
  "message_type": "string (0100|0110)",
  "f14": "string (expiry date, MMYY)",
  "f52": "string (PIN block encrypted with PEK, base64)",
  "cvv2": "string (3-digit CVV2)",
  "aav": "string (AAV, base64 — HMAC-SHA1)",
  "response_code": "string (00=OK, 55=wrong PIN, 82=bad ARQC, N7=bad CVV2, 14=unknown PAN)",
  "f55": {
    "cryptogram": "ARQC hex (8 bytes)",
    "arpc": "ARPC base64 (8 bytes — present on 0110 response)",
    "cid": "Cryptogram Information Data, 1 byte hex",
    "atc": "Application Transaction Counter, 2 bytes hex",
    "aip": "Application Interchange Profile, 2 bytes hex",
    "iad": "Issuer Application Data, variable hex",
    "amount_auth": "6 bytes BCD hex",
    "amount_other": "6 bytes BCD hex",
    "terminal_country": "2 bytes hex",
    "terminal_verification_results": "5 bytes hex",
    "currency_code": "2 bytes hex",
    "transaction_date": "YYMMDD, 3 bytes BCD hex",
    "transaction_type": "1 byte hex",
    "unpredictable_number": "4 bytes hex"
  }
}
```

Any subset of `f52`/`cvv2`/`aav`/`f55` may be present — `crypto_host` only runs the checks for keys
that exist, and always stamps `response_code` on the way out.

### `stats.h` — thread-safe rolling counters

Direct port of the Java `Stats` class. Windows `{30, 60, 180, 1800}` seconds, backed by one
`std::mutex` and two `std::deque<int64_t>` of send/recv timestamps (milliseconds since epoch),
trimmed to the max window on every record.

```cpp
class Stats {
public:
    explicit Stats(std::optional<int> yellow_threshold_seconds);   // nullopt = no yellow threshold
    void set_connection(const std::string& name, bool connected);   // e.g. "upstream", "downstream"
    void set_gauge(const std::string& name, nlohmann::json value);   // arbitrary named point-in-time value
    void record_sent();
    void record_recv();
    nlohmann::json snapshot() const;
        // keys: sent_total, recv_total, sent_30s/recv_30s ... sent_1800s/recv_1800s,
        // seconds_since_last_recv (double|null, rounded to 0.1), last_recv_datetime (HH:mm:ss|null),
        // yellow_threshold_seconds (only if set), connections (object, only if non-empty),
        // gauges (object, only if non-empty)
private:
    mutable std::mutex mutex_;
    std::deque<int64_t> sent_, recv_;
    std::map<std::string, bool> connections_;
    std::map<std::string, nlohmann::json> gauges_;
    std::optional<int> yellow_threshold_seconds_;
};
```

### `stop_event.h` — write-once stop flag

```cpp
class StopEvent {
public:
    void set();                                             // idempotent; notifies all waiters
    bool is_set() const;
    bool wait_for(std::chrono::milliseconds timeout);        // true if set before timeout elapses
    void await();                                             // blocks forever until set
private:
    mutable std::mutex mutex_;
    std::condition_variable cv_;
    bool flag_ = false;
};
```

Backed by `std::condition_variable` (not a bare `std::atomic<bool>` spin/sleep loop) so `wait_for`
wakes *immediately* on `set()` rather than only at the next poll tick — this matches Java's
`CountDownLatch.await(timeout)` semantics exactly, and is what the pending-reaper's "wake every
second, or immediately on stop" behavior and `CommandServer`'s `/stop` handling both rely on.

**The one place polling is deliberately kept, not condition-variable-based**: `Upstream`'s
accept/connect loops need to wake on *either* of two independent `StopEvent`s (stop-requested OR
reconnect-requested) without either event's class knowing the other exists — exactly the Java
version's `BooleanSupplier shouldStop = () -> stopEvent.isSet() || reconnectEvent.isSet()`. Waiting
on two unrelated condition variables simultaneously needs either a third shared condition variable
both events also notify (extra coupling) or `std::async`/polling. Per the Java doc's own tradeoff
("the 200ms poll here is a deliberate simplicity/latency tradeoff acceptable given this project's
multi-second retry/reestablish intervals"), this port keeps that exact tradeoff: `accept()`/
`connect()` use a 1-second socket-level timeout (`SO_RCVTIMEO` / `poll()` with a 1000ms bound) and
recheck the combined predicate — a lambda `std::function<bool()>` — on every timeout, mirroring the
Java version's `ServerSocket.setSoTimeout(1000)` loop precisely.

### `log.h` — logging + in-memory ring buffer

There is no C++ standard logging framework to wrap (unlike Java's `java.util.logging`, which the
Java doc must remap level *names* for via `LogLevels`). This port defines its own four-level
enum directly, with no remapping layer needed:

```cpp
enum class LogLevel { Debug, Info, Warning, Error };
std::optional<LogLevel> parse_log_level(const std::string& name);   // "DEBUG"/"INFO"/"WARNING"/"ERROR"
std::string to_string(LogLevel level);

class Logger {
public:
    static Logger& instance();               // process-wide singleton
    void set_level(LogLevel level);
    LogLevel level() const;
    void log(LogLevel level, const std::string& msg);   // no-op if level < current threshold
    std::vector<std::string> buffered_lines() const;     // up to max_lines, oldest first
private:
    mutable std::mutex mutex_;
    std::atomic<LogLevel> level_{LogLevel::Info};
    std::deque<std::string> ring_;   // capped at 2000, formatted "HH:MM:SS LEVEL message"
};

#define LOG_DEBUG(msg)   Logger::instance().log(LogLevel::Debug, msg)
#define LOG_INFO(msg)    Logger::instance().log(LogLevel::Info, msg)
#define LOG_WARNING(msg) Logger::instance().log(LogLevel::Warning, msg)
#define LOG_ERROR(msg)   Logger::instance().log(LogLevel::Error, msg)
```

Every actor's `main()` sets the level from config **before** constructing `CommandServer` — same
ordering requirement as the Java doc, for the same reason (messages logged before the level is set
correctly use whatever the default was).

### `command_server.h` — shared HTTP command/stats API

Every actor gets one, backed by `httplib::Server`.

```cpp
class CommandServer {
public:
    CommandServer(int port, Stats& stats, StopEvent& stop_event, const std::string& bind_host,
                  std::optional<std::string> auth_token);
    void register_route(const std::string& path, std::vector<std::string> methods,
                         bool protected_route, httplib::Server::Handler handler);
        // Wraps `handler`: enforces method + (if protected_route) header X-Router-Auth ==
        // auth_token before calling it. The handler writes its own response.
    void start();     // spawns a dedicated thread running server_.listen(bind_host, port)
    void stop();       // server_.stop() — called from the actor's own shutdown path, not by clients
private:
    httplib::Server server_;
    std::thread listen_thread_;
};
```

Built-in routes (identical contract to the Java version — this is the one guarantee the Python
monitor depends on, see "Monitor" below):

| Route | Method | Protected | Behavior |
|---|---|---|---|
| `/stats` | GET | no | `stats.snapshot()` as JSON |
| `/stop` | GET, POST | yes | sets `stop_event`, returns `{"status":"stopping"}` |
| `/log_level` | GET | no | returns `{"level": <current>}` |
| `/log_level` | POST | yes | body `{"level": "..."}`, sets logger level, returns `{"level": <upper>}` |
| `/logs` | GET | no | JSON array of buffered log lines; `?format=text` → newline-joined plain text |

Default `bind_host` is `127.0.0.1`. Auth token defaults to unset (disabled) — set
`command_auth_token` before exposing any command port beyond loopback.

**Process lifetime note**: unlike the JVM, a C++ process with no non-daemon threads left running
exits on its own once `main()` returns — there is no `HttpServer`-internal-dispatcher-thread
problem to work around here, so no explicit `exit(0)` call is required purely to make the process
terminate. Every actor's `main()` still returns a proper exit code (`0` on clean stop, `1` on an
uncaught exception reaching `main`) for shell/monitor-script consistency, but the C++ port does not
need the Java version's "`System.exit()` is mandatory or the JVM hangs" workaround — `main()`
joining `command_server`'s listen thread and every session thread to completion before returning is
sufficient.

### `crypto_utils.h` — MasterCard M/Chip EMV operations

All functions pure (no I/O), using OpenSSL's EVP API: `EVP_des_ede3` (DESede/ECB/NoPadding via
`EVP_CIPHER_CTX` with padding disabled), `EVP_des_ecb` (DES/ECB/NoPadding), `HMAC` with `EVP_sha1()`.

| Function | Purpose |
|---|---|
| `derive_udk(imk_hex, pan, pan_seq) -> std::string` | EMV Option A UDK derivation |
| `derive_session_key(udk_hex, atc_hex) -> std::string` | ATC-based session key (Common Session Key Derivation, Option A) |
| `verify_arqc(pan, pan_seq, imk_hex, f55) -> bool` | Retail MAC ARQC check |
| `calculate_arpc_method1(arqc_hex, arc_hex, sk_hex) -> std::vector<uint8_t>` | ARPC Method 1 |
| `encode_pin_block_format0(pin, pan) -> std::vector<uint8_t>` | Build cleartext ISO 9564-1 Format-0 PIN block (tests) |
| `encrypt_pin_block(plain, pek_hex) -> std::vector<uint8_t>` | 3DES-encrypt a PIN block |
| `verify_pin(pan, f52_base64, pek_hex, reference_pin) -> bool` | Decrypt + verify ISO 9564-1 Format-0 PIN block |
| `compute_cvv2(pan, expiry_mmyy, cvk_hex) -> std::string` | Compute CVV2 (tests) |
| `verify_cvv2(pan, expiry_mmyy, cvv2, cvk_hex) -> bool` | MasterCard CVV2 verification |
| `compute_aav(f47_data, aav_key_hex, pan) -> std::string` | Compute AAV (tests) |
| `verify_aav(f47_data, aav_key_hex, pan) -> bool` | HMAC-SHA1 AAV verification |

**Critical pitfall — DESede key length (carried over unchanged).** A 3DES key must be exactly
**24 bytes** for `EVP_des_ede3`, same as Java's `SecretKeySpec` requirement. Every `imk_ac`/`pek`
value in `pans_defined.json` is a 16-byte (two-key triple-DES, K1‖K2‖K1) key — expand to 24 bytes as
`K1‖K2‖K1` (copy the first 16 bytes, then re-append the first 8) before initializing any 3DES
`EVP_CIPHER_CTX`.

Retail MAC (ISO/IEC 9797-1 Algorithm 3), ARQC MAC input field order, ARPC Method 1, CVV2 derivation,
and AAV computation are all bit-for-bit identical algorithms to the Java doc's `CryptoUtils`
section — reproduced here for self-containedness rather than re-derived:

- **Retail MAC**: split the 16-byte session key into two 8-byte DES keys K1/K2; for each 8-byte
  block of ISO/IEC 9797-2-padded data, XOR with the running hash then DES-encrypt with K1; the
  final MAC is `DES-encrypt(K1, DES-decrypt(K2, h))` on the last hash value. ISO/IEC 9797-2 padding:
  append `0x80`, then zero-pad to the next 8-byte boundary.
- **ARQC MAC input field order** (all hex-decoded and concatenated): `amount_auth`, `amount_other`,
  `terminal_country`, `terminal_verification_results`, `currency_code`, `transaction_date`,
  `transaction_type`, `unpredictable_number`, `aip`, `atc`.
- **ARPC Method 1**: XOR the ARQC (8 bytes) with the zero-padded-to-4-bytes response code (as hex
  text bytes, left side only — only as many bytes as the shorter of the two overlap), then
  3DES-encrypt the result with the session key.
- **CVV2**: split the 16-byte CVK into two 8-byte DES keys CVK-A/CVK-B; build two 8-byte data blocks
  from `PAN + expiry(YYMM, swapped from input MMYY) + service_code` zero-padded/truncated to 32 hex
  digits; `r1 = DES-enc(A, block0)`, `r2 = r1 XOR block1`, `r3 = DES-enc(A, r2)`, `r4 = DES-dec(B,
  r3)`, `r5 = DES-enc(A, r4)`; take digits from `r5`'s hex representation (first the actual decimal
  digits in order, then — only if fewer than 3 were found — hex letters mapped via `(digit-10) %
  10`), first 3 characters.
- **AAV**: `HMAC-SHA1(aav_key, PAN + f14(expiry) + message_type)`, base64-encoded.

`EVP_CIPHER_CTX` setup: `EVP_CIPHER_CTX_new()`, `EVP_CipherInit_ex(ctx, EVP_des_ede3(), nullptr,
key.data(), nullptr /* no IV, ECB */, enc ? 1 : 0)`, `EVP_CIPHER_CTX_set_padding(ctx, 0)`,
`EVP_CipherUpdate`/`EVP_CipherFinal_ex`, `EVP_CIPHER_CTX_free(ctx)` — every call site must free the
context on every exit path (including exceptions) via RAII (a thin `CipherCtx` wrapper class with a
destructor calling `EVP_CIPHER_CTX_free`), not a bare pointer with manual cleanup, given this
project's "every exit path releases its resources" principle.

---

## `config/pans_defined.json`

Unchanged shape from the Java doc. Keys are PAN strings; used by `crypto_host` (all fields) and
`downstream_host` (key presence only, to decide PAN-known vs. unknown):

```json
{
  "4111111111111111": {
    "pin": "1234", "pan_seq": "00",
    "imk_ac": "<32 hex chars, 16-byte key>",
    "cvk":    "<32 hex chars, 16-byte key>",
    "pek":    "<32 hex chars, 16-byte key>",
    "aav_key":"<32 hex chars, 16-byte key>"
  }
}
```

Populate with 4+ distinct PANs across at least two card ranges (two `4...` Visa-shaped, two `5...`
Mastercard-shaped) for test coverage. Every key is a fresh random 16-byte hex string — generate new
values for this project; do not reuse the Java project's `pans_defined.json` verbatim (this project
is self-contained, per the same principle the Java doc states for itself).

**Pitfall — a wrong-shaped `pans_defined.json` fails silently, not loudly.** The loader (a plain
`nlohmann::json` walk into a small `PanRecord{pin, pan_seq, imk_ac, cvk, pek, aav_key}` struct, one
per PAN) reads each field via `.value(key, "")` — a missing key doesn't throw, it just becomes an
empty string. A file with the wrong key names (e.g. carried over from a different project's schema,
or missing `pin`/`pek`/`aav_key` entirely) loads *without error* and every PAN in it is still
"known" as far as the `pans_defined.count(pan)` check goes, but every PIN/ARQC/CVV2/AAV check that
actually uses the empty-string fields then fails for a reason that has nothing to do with the wire
data being tested — `verify_pin` compares against an empty `reference_pin`, `derive_udk` runs on an
empty `imk_hex`, etc. This produces confusing rc `"55"`/`"82"`/`"N7"` declines that look like a
crypto bug in the *router* or *crypto_host* logic when the actual defect is a malformed config file.
When debugging an unexpected decline, check `pans_defined.json`'s shape against the schema above
(all six keys present, non-empty) before suspecting the crypto code itself.

---

## Router (`src/router/`)

### Config schema (`config/router_1.json`)

Identical JSON shape to the Java version:

```json
{
  "name": "router_1",
  "type": "router",
  "is_active": true,
  "partner_id": "partner_a",
  "log_level": "DEBUG",
  "command_port": 8080,
  "upstream": {
    "port": 5000,
    "framing": { "header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4 }
  },
  "downstream": {
    "host": "localhost", "port": 5001,
    "irm_id": "IRM_ID01", "client_id": "CLIENT01"
  },
  "crypto": {
    "host": "localhost", "port": 5002,
    "plugin_id": "a53c0b4e-2f7e-4c1e-9c58-1e6f2b6d7a10",
    "bearer_token": "dev-fortanix-bearer-token"
  },
  "worker_threads": 8,
  "reestablish_seconds": 10,
  "yellow_threshold_seconds": 40
}
```

Note: no `iso_spec` key — there is no per-MTI spec file to point at, since `iso_codec` has no
config surface (see "ISO 8583 codec" above). This is the one structural difference in the config
schema versus the Java version; every other key is unchanged.

Deserialized via `nlohmann::json` into a `RouterConfig` struct using
`NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT` (or equivalent explicit `from_json`), which — like
Jackson's `@JsonIgnoreProperties(ignoreUnknown = true)` — simply never looks at any key it wasn't
told to read, so unrecognized keys (`type`, `is_active`, or future monitor-only metadata) are
naturally ignored with no exclusion-set bookkeeping.

`RouterConfig::from_file(path)` loads the JSON and converts the raw `downstream` block's
`irm_id`/`client_id` strings to 8-byte EBCDIC via `ebcdic::to_ebcdic`.

Defaults (applied when the JSON key is absent): `log_level=INFO`, `worker_threads=8`,
`reestablish_seconds=10`, `yellow_threshold_seconds=40`, `queue_maxsize=1000`,
`pending_ttl_seconds=30`, `crypto_breaker_threshold=5`, `crypto_breaker_cooldown_seconds=30`,
`reconnect_jitter_seconds=2.0`, `command_bind_host="127.0.0.1"`. `partner_id` and
`command_auth_token` default to unset. `upstream.mode` defaults to `"server"`, `upstream.host` to
`"localhost"`, `upstream.retry_seconds` to `5`.

`is_active` controls whether the monitor's "Start All" launches this actor. JSON booleans are
lowercase (`true`/`false`).

### `Upstream` — server/client connection acquisition

Two classes, both returning a plain struct `UpstreamConn { int fd; sockaddr_storage addr; std::shared_ptr<std::mutex> write_lock; }`:

```cpp
class UpstreamServer {
public:
    explicit UpstreamServer(const UpstreamConfig& cfg);   // socket(), SO_REUSEADDR, bind(), listen()
        // Created once outside the session loop — survives reconnects.
    std::optional<UpstreamConn> accept(std::function<bool()> should_stop);
        // Loops on poll()/accept() with a 1s timeout, rechecking should_stop each iteration;
        // returns nullopt on stop or a hard error.
    ~UpstreamServer();   // closes the listen fd
};

class UpstreamClient {
public:
    explicit UpstreamClient(const UpstreamConfig& cfg);
    std::optional<UpstreamConn> connect(std::function<bool()> should_stop);
        // Connects to cfg.host:cfg.port (5s connect timeout via non-blocking connect + select());
        // on failure, waits cfg.retry_seconds (polling should_stop every 200ms) before retrying.
        // Returns nullopt if should_stop becomes true while waiting.
};
```

`should_stop` is the combined stop-OR-reconnect predicate discussed under `stop_event.h` above —
`RouterSession` passes `[&]{ return stop_event.is_set() || reconnect_event.is_set(); }`.

### `DownstreamConnection` — dual-socket IMS session

```cpp
class DownstreamConnection {
public:
    static DownstreamConnection connect(const DownstreamConfig& cfg);
        // 1. Connect to_fd to cfg.host:cfg.port (5s connect timeout), then clear any socket-level
        //    timeout (SO_RCVTIMEO=0) once connected — the connect-timeout must not leak onto
        //    subsequent blocking reads, same requirement as the Java version.
        // 2. Same for from_fd.
        // 3. Send resume TPIPE on from_fd: build_frame(0x80, irm_id, client_id, "", {}, {}).
        // 4. Send pipe-cleaner ping on to_fd: data = to_ebcdic("1234 clean the pipes", 20);
        //    build_frame(0x00, irm_id, client_id, "", data, PING_TRANSCODE).
    void send(const std::vector<uint8_t>& frame);   // acquires write_mutex_, writes to to_fd
    std::vector<uint8_t> recv();                       // blocking read from from_fd via read_response
    void close();                                       // shutdown(SHUT_RDWR) then close, both fds
private:
    int to_fd_, from_fd_;
    std::mutex write_mutex_;
};
```

`close()` follows the "shutdown before close" pattern (see Teardown notes below): each fd gets
`::shutdown(fd, SHUT_RDWR)` before `::close(fd)`, so a thread blocked in `recv()` on `from_fd_`
unblocks via a `0`-byte read (not a use-after-close race on the fd number).

### `CryptoClient` — HTTP client to crypto_host with a circuit breaker

Wire interface mimics Fortanix DSM's plugin-execution API (`POST /sys/v1/plugins/{plugin_id}`,
bearer-token auth, base64 `PluginOutput` response) — unchanged rationale from the Java doc: a later
swap to a real Fortanix DSM tenant is a config/URL change, not a rewrite.

```cpp
class CryptoClient {
public:
    CryptoClient(const CryptoConfig& cfg, int breaker_threshold, int breaker_cooldown_seconds);
        // base_path = "/sys/v1/plugins/" + cfg.plugin_id
        // One httplib::Client per CryptoClient instance, reused across calls (cpp-httplib clients
        // are safe to share across threads for sequential-per-call use; if profiling later shows
        // contention, a thread_local client per dispatcher worker is the documented escape hatch —
        // not built by default here, since "get the mutex version correct first" applies equally
        // to reused-vs-pooled HTTP clients).
        // Breaker state: failure counter + "open until" timestamp, guarded by one mutex.

    std::string validate(const std::string& endpoint, const std::string& pan, const std::string& f47);
        // If now < open_until: skip the HTTP call, return "" immediately — same fallback as any
        //   other error path, so worker threads stay free to drain the queue with declines instead
        //   of each stalling a full 5s timeout against a known-down crypto host.
        // Otherwise: POST {base_path} with JSON {"operation": endpoint, "f2": pan, "f47": f47} and
        //   header Authorization: Bearer {cfg.bearer_token}, 5s timeout.
        //   - HTTP status >= 400 or any exception/connection error: log, increment failure
        //     counter (reset on success); once the counter reaches breaker_threshold, set
        //     open_until = now + breaker_cooldown_seconds and return "".
        //   - success: the 2XX body is a JSON string literal (the PluginOutput envelope, base64,
        //     "format": "byte") — parse the body as a JSON string, base64-decode it, JSON-parse
        //     the decoded bytes to reach {"f47": ...}; reset failure counter to 0; return that
        //     inner object's "f47" field (empty string if null). A failure at either decode layer
        //     is treated the same as an HTTP error above.
};
```

Callers only overwrite their working `f47` when the return value is non-empty — every failure path
leaves the original `f47` unchanged, so a down or misconfigured crypto host degrades to "checks
silently skipped," never a crash. Same "Response envelope — unverified assumption" caveat as the
Java doc applies here unchanged: if a real Fortanix tenant's actual response wraps the base64
differently, only the decode step inside `validate` needs to change.

### `Dispatcher` — worker pool + STAN rewrite + pending map

Routes `0100` upstream → crypto → downstream. Routes `0110`/`0130`/`0430` downstream → upstream (via
STAN lookup). **Direct 1:1 port of the Java concurrency model** — no sharding, no min-heap.

```cpp
struct PendingEntry {
    int up_fd;
    std::shared_ptr<std::mutex> up_write_lock;
    std::string upstream_stan;
    std::chrono::steady_clock::time_point created_at;
};
struct RoutedMessage {
    std::map<std::string, std::string> req;
    int up_fd;
    std::shared_ptr<std::mutex> up_write_lock;
    sockaddr_storage addr;
};

class Dispatcher {
public:
    Dispatcher(const RouterConfig& cfg, DownstreamConnection& downstream, CryptoClient& crypto,
               Stats& stats, StopEvent& reconnect_event);
    void start();          // spawns cfg.worker_threads worker threads + one pending-reaper thread
    void submit(RoutedMessage msg);         // blocking enqueue (backpressure) via cv.wait when full
    void handle_response(const std::map<std::string, std::string>& resp);   // called from ds-receiver thread
    std::map<std::string, int> purge();      // operator drain; returns dropped counts
    void drain_and_stop();                    // poison-pill sentinels + join (session teardown)

private:
    std::deque<std::optional<RoutedMessage>> queue_;   // nullopt = poison pill
    std::mutex queue_mutex_; std::condition_variable queue_cv_;
    std::unordered_map<std::string, PendingEntry> pending_;
    std::mutex pending_mutex_;
    std::atomic<int> stan_counter_{0};
    std::vector<std::thread> workers_; std::thread reaper_;
};
```

**STAN rewriting**: the dispatcher owns its own 6-digit counter (`(counter + 1) % 1'000'000`,
zero-padded, `std::atomic<int>` — a single fetch-and-increment, no lock needed for the counter
itself even though the pending-map insert it feeds into is locked separately). On a `0100`, it
saves a `PendingEntry` keyed by the new `router_stan`, and sends the message downstream with
`router_stan` in field 11. On a matching response, it looks up `router_stan`, restores
`upstream_stan` into field 11, and forwards upstream. If a `router_stan` slot the counter is about
to reuse is still occupied (the counter wrapped while the old entry was still outstanding), log at
error level before overwriting it.

**Worker loop** (one per worker thread): pop from `queue_` under `queue_mutex_`/`queue_cv_`; break on
the poison-pill sentinel (`std::nullopt`), else call `process(msg)` — wrapped in try/catch: an
I/O-related exception from `process` (a failed downstream write) sets `reconnect_event`; any other
exception is logged and swallowed (the worker keeps running).

**`process(msg)`** (runs in a worker thread):
1. Extract `mti`, `pan` (field 2), `upstream_stan` (field 11) from `msg.req`.
2. Generate the next `router_stan`.
3. If `mti == "0100"`: call `crypto.validate("validate_0100", pan, req["47"])`; if non-empty,
   overwrite field 47 in the forwarded copy.
4. Set field 11 to `router_stan` in the forwarded copy; `iso_codec::encode(...)`.
5. Insert the `PendingEntry` into `pending_` keyed by `router_stan` (log+overwrite on collision, as
   above); update the `pending_count` gauge.
6. Build the IMS frame (`ims_connect::build_frame(0x00, irm_id, client_id, fwd["t"], encoded)`) and
   `downstream.send(frame)`; on success, `stats.record_sent()`.

**`handle_response(resp)`** (runs on the ds-receiver thread):
1. If `mti == "0810"`: return immediately — handled separately by the session.
2. If `mti` not in `{"0110", "0130", "0430"}`: log a warning and return.
3. Pop the pending entry by `router_stan` (field 11 of `resp`); if none found, log and return.
4. Restore field 11 to `entry.upstream_stan`.
5. If `mti == "0110"`: call `crypto.validate("validate_0110", pan, resp["47"])`; overwrite field 47
   if non-empty.
6. Encode, acquire `*entry.up_write_lock`, write to `entry.up_fd`, release the lock, then
   `stats.record_sent()` — wrapped in try/catch: this write races session teardown closing the
   upstream socket from a different thread, and that race must not propagate as an uncaught
   exception on the ds-receiver thread.

**Pending reaper** (daemon-equivalent thread started in `start()`, joined in `drain_and_stop()`):
wakes every second (via `stop_event.wait_for(1s)` returning false — reusing the same `StopEvent`
primitive, or a dedicated one scoped to the dispatcher's own lifetime), scans `pending_` under
`pending_mutex_` for entries older than `cfg.pending_ttl_seconds` (measured via
`std::chrono::steady_clock` — a monotonic clock, not wall-clock time), removes each, and for each
expired entry writes a local decline (`t=0110, 11=<upstream_stan>, 39=91`) directly to the upstream
connection, then logs a warning. Updates the `pending_count` gauge after any removals. **This is a
linear scan of the whole map every second by design** (the min-heap optimization is documented
future work, not built here — see "Future optimizations" at the end of this document).

**Queue depth / pending count gauges**: after every `submit()`/dequeue and every pending
insert/pop, call `stats.set_gauge("queue_depth", queue_.size())` and
`stats.set_gauge("pending_count", pending_.size())`.

**Traffic counters**: `stats.record_sent()`/`record_recv()` must be called at every actual wire I/O
point — in the dispatcher (`process()` after the downstream write, `handle_response()` after the
upstream write, the pending reaper after its decline write) *and* in `RouterSession`
(`handle_upstream()` after decoding a frame, `downstream_receiver()` after decoding a frame,
`forward_0800()`/`forward_0810()` after their writes). Skipping any of these fails silently — the
same trap the Java doc calls out: `/stats` still returns 200 with totals stuck at 0, and the monitor
shows the actor as permanently yellow regardless of real traffic.

### `RouterSession` — one live connection session

Owns the ds-receiver thread and the up-server/up-client thread. Direct port of the Java class;
same method names translated to C++ conventions.

**Critical pitfall — `RouterSession` must never be moved or copied, and `connect()` must return a
heap-owned pointer, not a by-value object.** `Dispatcher` stores a raw `DownstreamConnection&`
reference, captured once at construction time, pointing at `RouterSession::downstream_`. If
`RouterSession` is ever relocated after that point — including by `std::optional<T>::emplace(args)`,
which *always* constructs its payload as `T(std::forward<Args>(args)...)` even when `args` is
already a `T&&` — the move constructor relocates `downstream_` to a new address, but `Dispatcher`'s
reference still points at the old, now-moved-from subobject (`to_fd_=-1, from_fd_=-1,
write_mutex_=nullptr` after the move). The first `0100` routed through the dispatcher then
segfaults on `std::lock_guard<std::mutex> lock(*write_mutex_)` with a null mutex pointer — and
since nothing exercises the dispatcher until an actor sends genuine ISO 8583 traffic, this can sit
latent through an entire build-and-unit-test cycle and only surface the first time the full stack
processes a real transaction. The fix: `connect()` returns `std::unique_ptr<RouterSession>`,
constructed exactly once via `new` inside the static factory (not `std::make_unique`, since the
constructor is private and `make_unique` — a free function, not a member or friend — can't reach
it), and the move constructor/assignment are `= delete`, not `= default`. Any class with members
that hold raw references to their *siblings'* subobjects must be non-movable/non-copyable, or
exclusively heap-owned — this is not specific to `RouterSession`, and the same reasoning applies to
any future class built the same way.

```cpp
class RouterSession {
public:
    static std::unique_ptr<RouterSession> connect(const RouterConfig& cfg, Stats& stats, StopEvent& stop_event);
        // 1. DownstreamConnection::connect(cfg.downstream) — throws on failure; caller treats
        //    that as "retry after reestablish_seconds + jitter".
        // 2. stats.set_connection("downstream", true).
        // 3. Build a CryptoClient; create a fresh reconnect_event (StopEvent) and a Dispatcher
        //    wired to it.
        // 4. return std::unique_ptr<RouterSession>(new RouterSession(...)) -- constructor is
        //    private, so this factory (a member function) constructs it directly with `new`
        //    rather than going through std::make_unique.
    void run_until_disconnect(UpstreamServer* srv_sock);
        // 1. dispatcher_.start()
        // 2. Start ds-receiver thread -> downstream_receiver()
        // 3. Start up-server/up-client thread depending on cfg.upstream.mode
        // 4. Block until stop_event OR reconnect_event becomes set (loop on
        //    stop_event.wait_for(1s), also checking reconnect_event.is_set() each iteration)
        // 5. teardown(up_thread)
        // 6. ds_thread joined with a bounded wait (std::thread has no built-in timed join —
        //    signal via the closed downstream socket unblocking recv(), then join() unconditionally;
        //    since close() already guarantees the blocked read returns, an unbounded join() here
        //    is safe and simpler than reimplementing Java's Thread.join(5000) semantics by hand)
    Dispatcher dispatcher_;   // exposed for RouterMain's /dispatcher/purge route
};
```

**`handle_upstream(fd, addr, write_lock)`** (the upstream read loop):
- `stats.set_connection("upstream", true)`; stash `(fd, write_lock)` as the session's live upstream
  reference under its own mutex (read by `forward_0810`).
- Loop: `framing::read_message(fd, cfg.upstream.framing)` → `iso_codec::decode` → `stats.record_recv()`.
  - MTI `0100`/`0120`/`0420` → `dispatcher_.submit({req, fd, write_lock, addr})`.
  - MTI `0800` → `forward_0800(req)`.
  - anything else → log a warning.
  - A read error (covers both a genuine remote disconnect and a local close racing this blocked
    read during teardown) → log, set `reconnect_event`, break the loop.
- On exit: `stats.set_connection("upstream", false)`, clear the stashed upstream reference if it
  still points at this connection.

**`forward_0800(req)`**: re-encode, wrap in an IMS frame, `downstream.send(frame)`,
`stats.record_sent()` — wrapped in try/catch since teardown on another thread can close the
downstream connection out from under this write.

**`forward_0810(resp)`**: reads the stashed upstream reference under its lock; if none, log a
warning and return. Otherwise re-encode, acquire the upstream write lock, write, release,
`stats.record_sent()` — wrapped in try/catch, racing the same teardown.

**`downstream_receiver()`**:
- Loop: `downstream.recv()`.
  - A read error (remote disconnect or local close racing teardown) → log,
    `stats.set_connection("downstream", false)`, set `reconnect_event`, break.
  - Skip any frame whose first 4 bytes exactly equal `to_ebcdic("PING", 4)` — **both** the wire
    marker and the comparison value must be EBCDIC-encoded; comparing against a plain ASCII
    `"PING"` byte sequence never matches.
  - Otherwise decode via `iso_codec::decode`, `stats.record_recv()`, then, wrapped in a catch-all:
    ```cpp
    try {
        if (resp.at("t") == "0810") forward_0810(resp);
        else dispatcher_.handle_response(resp);
    } catch (const std::exception& e) {
        LOG_ERROR("unexpected error dispatching downstream message mti=" + resp.at("t"));
    }
    ```
    Required for the same reason as the Java doc: any exception from encode/decode or internal
    logic inside `forward_0810`/`handle_response`, left unguarded, silently kills this thread — the
    session then keeps accepting upstream messages forever while never again processing a
    downstream response, with no log line indicating why.

**`teardown(up_thread)`**:
1. `dispatcher_.drain_and_stop()`.
2. Clear and close the stashed upstream connection, if any (`shutdown()` then `close()`, swallowing
   any error).
3. `downstream_.close()` — `shutdown(SHUT_RDWR)` then `close()` on both fds; this unblocks any
   thread blocked in `recv()` on the from-socket. The ds-receiver's blocked read returns via a
   `0`-byte read (not an exception, since `shutdown()` delivers a clean EOF rather than an error) —
   its own catch treats this the same as the "downstream lost" path, setting `reconnect_event` and
   exiting. This is the *expected* teardown path, not an error condition to alarm on.
4. `up_thread.join()`.

### `router_main.cpp` — entry point, reconnect loop

```cpp
int main(int argc, char** argv) {
    auto cfg_path = parse_config_arg(argc, argv);   // --config <path>
    RouterConfig cfg = RouterConfig::from_file(cfg_path);
    StopEvent stop_event;
    Stats stats(cfg.yellow_threshold_seconds);

    Logger::instance().set_level(*parse_log_level(cfg.log_level));   // BEFORE constructing CommandServer
    CommandServer cmd(cfg.command_port, stats, stop_event, cfg.command_bind_host, cfg.command_auth_token);

    std::shared_ptr<Dispatcher> active_dispatcher;   // guarded by its own small mutex
    std::mutex active_dispatcher_mutex;
    cmd.register_route("/dispatcher/purge", {"POST"}, /*protected=*/true, [&](const httplib::Request&, httplib::Response& res) {
        std::lock_guard lock(active_dispatcher_mutex);
        if (!active_dispatcher) { send_json(res, 503, {{"error", "no active session"}}); return; }
        send_json(res, 200, active_dispatcher->purge());
    });
    cmd.start();

    std::unique_ptr<UpstreamServer> srv_sock;
    if (cfg.upstream.mode == "server") srv_sock = std::make_unique<UpstreamServer>(cfg.upstream);

    while (!stop_event.is_set()) {
        std::unique_ptr<RouterSession> session;   // NOT std::optional<RouterSession> -- see the
                                                    // "must never be moved" pitfall under RouterSession
        try {
            session = RouterSession::connect(cfg, stats, stop_event);
        } catch (const std::exception& e) {
            LOG_WARNING(std::string("failed to connect downstream: ") + e.what());
            wait_reestablish(stop_event, cfg);   // reestablish_seconds + random jitter
            continue;
        }
        { std::lock_guard lock(active_dispatcher_mutex); active_dispatcher = /* alias into session */; }
        session->run_until_disconnect(srv_sock.get());
        { std::lock_guard lock(active_dispatcher_mutex); active_dispatcher = nullptr; }
        if (!stop_event.is_set()) wait_reestablish(stop_event, cfg);
    }
    cmd.stop();
    return 0;
}
```

`wait_reestablish` waits `reestablish_seconds + uniform(0, reconnect_jitter_seconds)` — the jitter
avoids multiple routers sharing a downstream/crypto host from reconnecting in lockstep after a
shared outage.

### Actor process lifecycle (applies to `router_main.cpp` and all three simulator mains)

`main(argc, argv)` parses `--config <path>`, loads the config, calls the actor's `run()`, and
returns `0` on clean completion, `1` on any uncaught exception (a top-level `try`/`catch` around the
body of `main`). As noted under `command_server.h`, no explicit `exit()`/`_exit()` call is needed
purely to terminate the process — but the reusable `run()` function itself must still stay
side-effect-free with respect to process lifetime (no direct `std::exit`/`abort` calls inside it),
for the same reason as the Java version: a future in-process integration test needs to call `run()`
directly without ending the test binary.

---

## Simulators (`src/simulators/*`)

All three follow the same shape: load `config.json`, build a `Stats` + `CommandServer`, register any
custom routes, start, and (for the two that aren't a bare HTTP service) run an accept/connect loop
until the stop event fires. Config loading in each is a plain `nlohmann::json` object read directly
(no dedicated config struct — unlike the router, these configs are small and used mostly as-is).

**Pitfall — a single-shared-config deployment (all four binaries reading one `router_1.json` via
`RouterConfig::from_file`, rather than the four separate per-actor JSON files shown below) is a
legitimate simplification, but it reintroduces two footguns the four-file design avoids for free:**
1. **Command-port collisions.** Each actor still needs its *own* distinct `command_port` — deriving
   it arithmetically from another field (e.g. `upstream.port + 1`) is not safe, because that can
   collide with a *different* actor's primary listen port (in this project's own port numbering,
   `upstream.port(5000) + 1 == downstream.port(5001)`, so upstream_host's command server would try
   to bind the exact port downstream_host already owns). Give every actor block its own explicit
   `command_port` key in the shared config (`upstream.command_port`, `downstream.command_port`,
   `crypto.command_port`) and read that, never `some_port + 1`.
2. **Host-field double duty.** The same `upstream`/`downstream`/`crypto` sub-object's `host` field
   is read by *two different processes* for *two different purposes* — the router binds/connects
   using it, and the corresponding simulator (if it also needs to reach a peer, e.g. `upstream_host`
   connecting out to the router) reads the same field as its own connect target. A value that's
   correct for one direction can be wrong for the other: `"0.0.0.0"` is a valid *bind* host for the
   router's upstream listen socket but not a portable *connect* target (Linux happens to accept
   `connect()` to `0.0.0.0` as `localhost`, but this is not standard, portable behavior and
   shouldn't be relied on). Likewise, docker-compose *service names* like `"downstream_host"` or
   `"crypto_host"` only resolve when each actor is its own compose service on a shared network — if
   all four binaries instead run as sibling processes inside **one** container (e.g. via
   `network_mode: host`, as this project's `docker-compose.yml` does), every cross-actor `host`
   value must be `"localhost"`, not a service name that will never resolve. Pick the topology first,
   then set every `host` field to match it — don't copy `"0.0.0.0"`/service-name values from a
   different topology's example config.

### `crypto_host`

Stateless HTTP validation service — no TCP actor loop, just one extra HTTP route served from a
**second** `httplib::Server` bound to `cfg.port` (separate from `CommandServer`'s port, exactly as
the Java version separates its two `HttpServer` instances). Same Fortanix-shaped wire interface as
`CryptoClient` above.

**Config** (`config/crypto_host.json`):
```json
{
  "name": "crypto_host", "type": "crypto", "is_active": true,
  "port": 5002, "command_port": 8082,
  "pans_defined": "pans_defined.json",
  "yellow_threshold_seconds": 60,
  "plugin_id": "a53c0b4e-2f7e-4c1e-9c58-1e6f2b6d7a10",
  "bearer_token": "dev-fortanix-bearer-token"
}
```

No `iso_spec` key (same rationale as the router config). `plugin_id`/`bearer_token` must match
`router_1.json`'s `crypto` block — no shared-secret store in this project; both sides read the same
literal string from their own config file.

**Route** (on the port-5002 `httplib::Server`, POST only): `POST /sys/v1/plugins/:plugin_id`.
1. `:plugin_id` path parameter must equal the configured `plugin_id` → else `404`.
2. `Authorization` header must equal `"Bearer " + bearer_token` → else `401` with body
   `{"error": "unauthorized"}`.
3. Request body: `{"operation": "validate_0100"|"validate_0110", "f2": pan, "f47": f47JsonString}` —
   `stats.record_recv()` once the body is successfully parsed.
4. Response: run `validate(pan, f47_str)` to get the enriched `f47`, encode `{"f47": enriched_f47}`
   as a JSON string, base64-encode that string, write the base64 text as the literal JSON response
   body (a quoted string, not an object) — the `PluginOutput` envelope. `stats.record_sent()` once
   the response body is written. (Both counters are easy to half-wire — `record_sent()` is the
   obvious one since it sits right next to constructing the response, but `record_recv()` on the
   request side is just as required for `/stats` to mean anything; omitting it doesn't fail any
   test, it just leaves `recv_total` at zero forever, which only shows up much later as "why does
   the monitor say crypto_host is silently starved.")

**`validate(pan, f47_str)` logic** (pure business logic, unaware of the HTTP envelope):
1. Decode the f47 JSON string.
2. PAN not in `pans_defined` → `response_code = "14"`; return immediately.
3. `rc = "00"`.
4. If `f52` present: `verify_pin`; failure → `rc = "55"`.
5. If `f55` present, `message_type == "0100"`, and `rc == "00"`: `verify_arqc`; failure → `rc = "82"`.
6. If `f55` present and `message_type == "0110"` (regardless of `rc`): derive the UDK and session
   key, compute the ARPC from the request's `cryptogram` and the current `rc` (as a 2-hex-digit
   "ARC" value), and store it base64-encoded into `f55.arpc`.
7. If `cvv2` present and `rc == "00"`: `verify_cvv2`; failure → `rc = "N7"`.
8. If `aav` present and `rc == "00"`: `verify_aav`; failure → `rc = "82"`.
9. Set `response_code = rc` on the data map; JSON-encode and return.

The router always calls crypto regardless of whether f47/f55 is present — an empty f47 exercises
none of the above checks and `rc` stays `"00"`.

### `downstream_host`

**Config** (`config/downstream_host.json`):
```json
{
  "name": "downstream_host", "type": "downstream", "is_active": true,
  "port": 5001, "command_port": 8081,
  "pans_defined": "pans_defined.json",
  "yellow_threshold_seconds": 40
}
```

**Architecture**: single listen socket; each accepted connection is dispatched by reading its first
IMS frame in a **fresh thread** (not the acceptor thread — the acceptor must be free to accept both
the to- and from-socket of a session before either read can block):
- `irm_f0 == 0x80` → this is the **from-conn**: register a bounded blocking queue
  (`std::deque<std::vector<uint8_t>>` + mutex + condition_variable, capacity-bounded the same way
  the dispatcher's queue is) under the connection's `client_id` (as a string key), then loop
  (pop with a 1s timed wait) → `ims_connect::write_response(fd, item)` until the stop event fires or
  the write fails.
- `irm_f0 == 0x00` → this is the **to-conn**: loop `ims_connect::read_request(fd)` →
  `route_frame(client_id_key, transcode, iso_data)` until the read fails (remote close).

**`route_frame`**:
- Transcode equals `PING_TRANSCODE` → wait (poll, up to 2s) for the from-conn queue to exist for
  this `client_id`, then enqueue `to_ebcdic("PING", 4) + to_ebcdic("PIPES cleaned", ...)`. **Both
  halves must be EBCDIC**, including the literal `"PING"` marker — it must match the router's
  skip-check byte-for-byte. (No stats counters here — a ping never touches `record_recv`/`record_sent`.)
- Every other branch first decodes the frame via `iso_codec::decode` and calls `stats.record_recv()`
  — do this once, right after decode, before branching on MTI, so every branch below gets it for
  free rather than needing its own call.
- MTI `0800` → build an `0810` echoing field 24, enqueue to the from-conn, `stats.record_sent()`.
- MTI `0120` → build `0130` with field 39 = `"00"`, enqueue, `stats.record_sent()`.
- MTI `0420` → build `0430` with field 39 = `"00"`, enqueue, `stats.record_sent()`.
- MTI `0100` → `process_0100(req)`, enqueue, `stats.record_sent()`.
- else → log a warning, drop (no `record_sent()` — nothing was actually sent).

**Connection-lifecycle stats**: `stats.set_connection("downstream_from", true/false)` around the
from-conn's queue-registration lifetime, `stats.set_connection("downstream_to", true/false)` around
the to-conn's read loop — same "wire it or the monitor shows nothing" reasoning as `record_recv`/
`record_sent` above, just for the connection-health indicator instead of the counters.

**`process_0100(req)`**:
- PAN not in `pans_defined` → `rc = "01"`.
- Else if the request's decoded f47's `response_code` (default `"00"`) is not `"00"` (crypto
  already declined it upstream) → `rc = "01"`.
- Else → `rc = "00"`, and generate the next sequential 6-digit auth code for field 38.
- **Every response must echo f47 back**: take the request's decoded f47, set
  `message_type="0110"` and `response_code=rc`, re-encode it into the response's field 47 — required
  even though `downstream_host` itself never reads f47 back out, because `crypto_host`'s ARPC
  computation on `validate_0110` needs the original `f55` cryptogram/ATC, and this response is the
  only place that data can reach that later call.

**Wait-for-from-conn polling**: before writing any response, the to-conn handler waits up to 2
seconds for the from-conn's queue to exist — the from-conn's resume-TPIPE can genuinely still be in
flight when the to-conn's first frame (the pipe-cleaner ping) arrives.

### `upstream_host`

Simulates an upstream card-network client: sends ISO 8583 `0100`s from a CSV, collects `0110`
responses.

**Config** (`config/upstream_1.json`):
```json
{
  "name": "upstream_1", "type": "upstream", "is_active": true,
  "command_port": 8083,
  "router": { "host": "localhost", "port": 5000 },
  "framing": { "header_hex": "", "length_field_type": "ASCII", "length_field_bytes": 4 },
  "input_dir": "upstream_1_input",
  "ping_0800_seconds": 30,
  "yellow_threshold_seconds": 40
}
```

**Modes**: `mode: "client"` (default) — connects out to the router, reconnecting on disconnect;
`mode: "server"` — listens, router connects to it.

**Custom command routes** (registered on the actor's own `CommandServer`, using cpp-httplib's
built-in multipart parsing for `/upload` rather than hand-rolling one):
- `POST /upload` — reads `req.files.at("file")`, writes its content to
  `<input_dir>/test_cases.csv`, overwriting in place.
- `GET /start` — reads the CSV, launches the send loop in a detached thread, returns
  `{"rows": N}`. Returns `503` if there is no live connection to the router yet.
- `GET /results` — returns the accumulated list of result maps as JSON.

**CSV format**: semicolon-delimited, UTF-8 with BOM (a leading `\xEF\xBB\xBF` on the header line) —
the reader must explicitly detect and strip that 3-byte sequence before splitting the header, since
C++ standard file/stream reading does not strip a BOM automatically. Column names are ISO 8583 field
numbers; non-matching columns (e.g. an `expected_39` column used only by test tooling) are silently
ignored by checking each key against `iso_codec::is_known_field`. Field 11 (STAN) is always
overwritten by the sender regardless of what's in the CSV.

```
2;3;4;11;expected_39
4111111111111111;000000;000000000100;000001;00
4222222222222222;000000;000000000200;000002;00
9999999999999999;000000;000000000300;000003;01
```

**Send loop**: for each CSV row not yet stopped, assign the next sequential 6-digit STAN (wrapping
at 1,000,000), stash the original row under that STAN in a pending map, build an `0100` from the
row's known-field columns plus `t=0100` and the assigned STAN, encode, `framing::write_message`,
`stats.record_sent()`, sleep 20ms before the next row.

**Receive loop**: read frames; MTI `0810` → ignore; MTI in `{0110, 0130, 0430}` → pop the pending row
by STAN (field 11), merge every response field into the row under a `resp_`-prefixed key (e.g.
`resp_39`, `resp_38`, `resp_47`), append to the results list; any other MTI → log a warning and
continue; a read error → mark the disconnect flag and stop.

**Keepalive loop**: send an `0800` immediately upon connecting, *then* wait `ping_0800_seconds`
(checking the disconnect/stop flags roughly every second so the wait is interruptible) before the
next send. Sending first avoids a dead window of up to `ping_0800_seconds` on every fresh connection
during which the monitor would show the actor as permanently yellow.

**Connect loop** (client mode): non-blocking `connect()` + `select()`/`poll()` with a 5000ms timeout;
on failure, wait `retry_seconds` (default 5) and retry. Once connected, explicitly clear any
socket-level timeout before running the send/receive/keepalive loops concurrently until the
connection drops, then loop back to reconnect — unlike Java's `Socket` connect-timeout constructor
(which only ever applies to the connect call itself), a raw POSIX `connect()` with a timeout
implemented via `select()`/`poll()` on a non-blocking socket does **not** leave any timeout attached
to the socket afterward either, so no explicit clear is strictly required — but the code should set
it explicitly and comment why, rather than relying on that being obviously true to a future reader
porting this file elsewhere.

---

## Monitor (`monitor/main.py`, Python, runs on the **host** — unchanged design, updated launch mechanics)

The monitor's HTTP contract, layout, and Flask app are **unchanged** from the Java project's
`monitor/main.py` — this is the whole point of keeping the monitor decoupled: "any future rewrite of
an individual actor into a different language stays compatible with this monitor for free, provided
the HTTP contract is preserved exactly," and the C++ actors preserve `CommandServer`'s routes
byte-for-byte. Only the pieces that assumed a JVM process launched via a jar need to change:

```python
# was: MAIN_CLASS_BY_TYPE = {"router": "com.xv6.router.RouterMain", ...}
# now: a path to the built executable, relative to the project root:
BINARY_BY_TYPE = {
    "router":     "build/router",
    "upstream":   "build/upstream_host",
    "downstream": "build/downstream_host",
    "crypto":     "build/crypto_host",
}
STARTUP_ORDER = {"crypto": 0, "downstream": 1, "router": 2, "upstream": 3}   # unchanged
```

**`launch_actor(actor)`**: `docker exec -d <container> bash -c "mkdir -p logs &&
./build/<binary> --config <relative-config-path> > logs/<name>.console.log 2>&1"` — same
`bash -c` + redirect rationale as the Java version (`docker exec -d`'s client detaches immediately;
without redirecting to a file, a crash's stderr goes nowhere retrievable). Log file truncated on
every (re)launch.

**`is_running(name)`**: unchanged — liveness is still "the actor's own `/stats` endpoint answers
HTTP 200," since `docker exec -d` still gives no process handle to poll regardless of what language
runs inside the container.

**`wait_for_ready(actor, timeout=10)`**: unchanged logic (polls `/stats`, additionally checks
`connections.downstream`/`connections.router` for routers/upstreams).

**Monitor API routes, status logic, shutdown safety net**: unchanged verbatim from the Java doc's
Monitor section — every route, JSON shape, and the green/yellow/red status logic carries over with
no code change needed on the monitor side beyond the `BINARY_BY_TYPE` table above.

**Container console visibility** (`/api/actor/<name>/commands`) — **one command changes**:
- **`kill`**: the Java version used `jps -lm` (a JVM-specific tool with no C++ equivalent) to find
  the PID by matching `<main class> --config <relative config path>`. The C++ replacement matches
  the same full command string via `ps` instead:
  ```
  PATTERN="build/router --config config/router_1.json"
  PID=$(docker exec <container> sh -c "ps -eo pid,args" | grep -F "$PATTERN" | awk '{print $1}')
  # explicit "no matching process" message and non-zero exit if nothing matched
  docker exec <container> kill -9 "$PID"
  ```
  Matching on the **full binary path + config argument string**, not just the binary name, keeps
  this safe when multiple instances would otherwise share a bare executable name (e.g. two router
  instances in a future multi-router scenario) — same rationale as the Java version's `jps` match.
- **`tail`**: unchanged — `docker exec <container> tail -F logs/<name>.console.log`.

### `monitor/static/index.html`

**Unchanged.** No C++-specific change touches the frontend — it only ever talks to the monitor's own
`/api/*` routes, which are unchanged. The same known open bug (log-level `<select>` snapping back to
`INFO` on every poll tick) carries forward undisturbed, for the same reason the Java doc gives: it's
documented, not silently patched over, as part of an unrelated change.

---

## Message flow (0100 authorization)

Unchanged from the Java doc — reproduced for self-containedness:

```
upstream_host          router                        crypto_host         downstream_host
     │                   │                                │                    │
     │──0100 (framed)───►│                                │                    │
     │                   │──POST /sys/v1/plugins/{id}────►│                    │
     │                   │  Bearer token; {operation:      │                    │
     │                   │   validate_0100, f2, f47}        │                    │
     │                   │◄─base64({f47: enriched})───────│                    │
     │                   │──IMS frame (0100)─────────────────────────────────►│
     │                   │◄──────────────────────────────────────IMS frame (0110)
     │                   │──POST /sys/v1/plugins/{id}────►│                    │
     │                   │  {operation: validate_0110}      │                    │
     │                   │◄─base64({f47: +arpc})──────────│                    │
     │◄──0110 (framed)───│                                │                    │
```

**STAN rewrite**: the router replaces field 11 with its own sequential counter before forwarding to
`downstream_host`; on the response, it restores the original upstream STAN before sending back.

**Keepalive (0800/0810)**: `upstream_host` sends `0800` immediately on connect and every
`ping_0800_seconds` thereafter. The router forwards it to `downstream_host` (as an IMS frame), which
responds `0810`; the router forwards that `0810` straight back to the upstream. This path bypasses
`Dispatcher` entirely — handled directly in `RouterSession` via `forward_0800`/`forward_0810`.

## Message flow (0120 advice / 0420 reversal)

```
0120 Advice   (decision already taken upstream — F38/F39 pre-filled, no crypto call)
  upstream ──0120──→ router ──0120──→ downstream_host ──0130 (F39=00)──→ router ──0130──→ upstream

0420 Reversal (command to revert an earlier transaction, no crypto call)
  upstream ──0420──→ router ──0420──→ downstream_host ──0430 (F39=00)──→ router ──0430──→ upstream
```

Both ride the same `Dispatcher` path as `0100` (STAN rewrite, pending-map lookup) but **skip the
crypto call** — `Dispatcher::process` only calls `crypto.validate` when `mti == "0100"`.
`downstream_host` always replies approved (`F39=00`) to these.

---

## Container

`Dockerfile`: `ubuntu:22.04` (or `mcr.microsoft.com/devcontainers/base:ubuntu`, matching the Java
project's base image choice) + `build-essential` (g++ ≥ 11, supporting C++20) + `cmake` (≥ 3.20) +
`libssl-dev` + `git` (needed by CMake `FetchContent`'s git-clone step) + `nodejs`/`npm` (+
`npm install -g @anthropic-ai/claude-code`, matching this repo family's existing container
convention — omit if that convention doesn't apply in the target environment). `WORKDIR /workspace`.

`start.sh`: ensures the Docker daemon is running (`dockerstart.sh`), `docker build --network host`
the image, remove any pre-existing `xv7cpp` container, then `docker run -d --name xv7cpp --network
host -v <project>:/workspace -w /workspace xv7cpp tail -f /dev/null` — the container idles; all
actual work happens via `docker exec`. `--network host` means this container and any other project
using the same default ports (5000-5002, 8080-8083, 8090) — including a live `xv6java` container —
cannot run at the same time; this is the accepted drop-in-replacement tradeoff from the "Coexistence"
decision above.

`stop.sh`: `docker stop xv7cpp && docker rm xv7cpp`.

`dockerstart.sh`: unchanged rationale from the Java doc — separate from `start.sh` so it can be
re-run standalone; checks `docker info`, tries `sudo service docker start`, falls back to a direct
`sudo dockerd` in the background if that doesn't work within ~10s.

`terminal.sh`: `docker exec -it xv7cpp bash`.

Build inside the container: `docker exec xv7cpp cmake -S . -B build && docker exec xv7cpp cmake
--build build -j` → produces `build/router`, `build/crypto_host`, `build/downstream_host`,
`build/upstream_host`. Run tests: `docker exec xv7cpp ctest --test-dir build`.

**Pitfall — unqualified `-j` (use every core) can OOM-kill the compiler in a memory-constrained
container**, and the failure mode is easy to misdiagnose as a source bug rather than a resource
one. `router_main.cpp` is the single heaviest translation unit in this project — it pulls in
`httplib.h` (header-only, large) and the full `RouterConfig`/`RouterSession`/`Dispatcher` object
graph in one file — and under `-j8` on an 8-core/~2.8GB container, `cc1plus` compiling that one file
concurrently with several others gets killed by the OOM killer while every *other* target (the
shared/router static libs, the three simulators, the test binary) links and builds fine. The
observable symptom is a `make`/`ninja` error report naming only `router_main.cpp` — `c++: fatal
error: Killed signal terminated program cc1plus` — with everything else reported as built
successfully, which looks like a compiler crash specific to that file rather than what it actually
is (memory exhaustion under parallelism). If a build fails this way: re-run with a smaller `-j` (or
`-j1` just for the affected target, e.g. `cmake --build build -j1 --target router_main`) rather than
assuming the source changed underneath it; a memory-constrained CI/dev container should default to
a bounded `-j` (e.g. `-j$(nproc --ignore=4)` or a fixed small number) rather than unqualified `-j`.

**Default port assignments** (unchanged from the Java version — see "Coexistence" decision):
- Router upstream listen: 5000
- Downstream host IMS: 5001
- Crypto host REST: 5002
- Router command API: 8080
- Downstream command API: 8081
- Crypto command API: 8082
- Upstream command API: 8083
- Monitor: 8090

---

## Running

```bash
./start.sh                            # build image + start the container (idle, ready for docker exec)
docker exec xv7cpp cmake -S . -B build
docker exec xv7cpp cmake --build build -j
./monitor_start.sh                    # dashboard on http://localhost:8090, on the HOST
# work in the dashboard: Start All -> upload a CSV -> Start -> watch /results
./monitor_stop.sh
./stop.sh
```

Individual actors, each as `docker exec -d xv7cpp ./build/<binary> --config config/<name>.json`,
using the `BINARY_BY_TYPE` names above.

`run_test.sh <csv_file>` — an end-to-end CLI driver, run on the **host**, same shape as the Java
version's script:
1. Builds (`cmake --build build -j`) unless run with `--manual`.
2. Launches all four actors via `docker exec -d`, as above.
3. Polls each actor's `/stats` with `curl -s -o /dev/null -f` (fail-fast on non-2xx) up to 30 times,
   1s apart.
4. Uploads the CSV to the upstream's `/upload`.
5. Retries `GET /start` up to 15 times, 1s apart, tolerating an initial 503.
6. Polls `/results` until every row has a response or 30 seconds elapse.
7. Prints a PAN/RC/auth-code/field-47 report and the router's 30-second stats.
8. On any exit path (`trap cleanup EXIT`), POSTs `/stop` to every actor's command port — not a
   host-side PID kill, for the same reason as the Java version: actors run inside the container's
   own PID namespace via `docker exec -d`, unreachable by a host-side signal.

`run_test.sh --manual <csv_file>` skips steps 1–2 and drives already-running actors.

### Glue-script safety checklist (unchanged from the Java doc)

Any re-runnable script (`run_test.sh`, `monitor_start.sh`, `monitor_stop.sh`) must fail loud, not
fail silent:

- **Every HTTP readiness/polling check must fail-fast on a bad response** — `curl -s -f`.
- **Never let a single flaky iteration of a polling/retry loop kill the whole script** under `set
  -e` — guard bare command-substitution assignments (`STATUS=$(cmd) || STATUS=""`).
- **Guarantee teardown with `trap ... EXIT`**, not a final line at the bottom of the script.

---

## Testing

**Catch2** (`ctest --test-dir build`, or `build/xv6_tests` directly): framing round-trip (all four
`length_field_type` encodings, plus `max_message_bytes` rejection), rolling-window stats counters,
`crypto_utils` (ARQC/ARPC/PIN/CVV2/AAV against known test keys), ISO 8583 round-trip via
`iso_codec::encode`/`decode` (specifically exercising the hex-MTI pitfall with a deliberately
non-decimal-looking hex value, per the note under "ISO 8583 codec" above), `RouterConfig::from_file`
parsing (including that unknown JSON keys are tolerated), `Dispatcher` resilience (bounded-queue
backpressure, pending-entry TTL expiry producing a decline, STAN-collision logging, `purge()` drop
counts), and one full-stack integration test wiring crypto/downstream/router/upstream together
in-process (constructing and running each actor's `run()`/equivalent directly in the test binary,
not via subprocess) with CSV-equivalent rows in and field 39 asserted on the results.

**`run_test.sh`**, exercised for real against actual `docker exec` subprocesses (not just in-process
Catch2) — CSV in, `/start`, poll `/results`, assert on field 39, verify clean teardown (no orphaned
processes, no ports left bound after the script exits).

**The dashboard itself**, exercised live in a browser — unchanged from the Java doc: "Start All"
launches all 4 actors and shows them connected; CSV upload + Start + results through the dashboard's
own proxy routes produces correct response codes; "Stop All" cleanly stops all 4 actors;
`monitor_stop.sh` frees port 8090 and removes its pidfile.

---

## Known limitations (intentionally out of scope, unchanged from the Java doc)

- No authentication on the upstream or downstream TCP sockets — first TCP connector wins.
- `command_auth_token` defaults to unset (auth disabled) — set it explicitly before exposing any
  command port beyond loopback.
- Crypto traffic between the router and `crypto_host` is plaintext HTTP (no TLS).
- `pans_defined.json` stores master keys in plaintext JSON — a test fixture only.
- The known monitor log-level display bug is intentionally carried forward as documented.
- **New to this port**: no per-MTI schema validation (see "ISO 8583 codec" above) — a message
  carrying a field its MTI shouldn't have decodes silently rather than being rejected. Accepted
  tradeoff for dropping `j8583`/`test_spec.xml`; revisit only if this ever needs to matter.

---

## Future optimizations (documented, not built in this spec's baseline)

Carried forward from the Java doc's "C++ portability notes" — these were the reason the concurrency
model was designed the way it was, but per the "Concurrency scope" decision above, none of them are
part of this baseline. Listed here so a later performance pass has a starting point instead of
rediscovering the same analysis:

- **Sharded pending map**: `Dispatcher::pending_` is a single `unordered_map` + one mutex. At high
  TPS this is a contention point (workers insert, the ds-receiver thread pops, on every
  transaction). Shard by `router_stan % N_BUCKETS` across N separate maps, each with its own mutex —
  16 buckets cuts per-lock contention roughly 16×.
- **Pending reaper — min-heap instead of linear scan**: maintain a min-heap keyed on expiry time
  alongside the hash map — push on insert, pop and discard stale top entries on each wake instead of
  scanning every entry every second.
- **Edge-triggered stop/reconnect signal**: replace the 200ms poll in `Upstream`'s accept/connect
  loops with an `eventfd`-based wake (or a self-pipe), integrated via `poll()`/`epoll()` alongside
  the listening/connecting socket — removes the fixed poll-interval latency entirely.
- **Lock-free bounded queue**: a lock-free bounded MPMC ring buffer for `Dispatcher`'s queue avoids
  the mutex entirely, at real implementation-complexity cost — only worth it after profiling shows
  the mutex version's contention actually matters at target volume.
