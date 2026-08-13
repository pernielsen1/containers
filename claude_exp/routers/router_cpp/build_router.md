# ISO 8583 Router — Build Specification: C++ core in a container + Python monitor on the host

## Purpose

Build a router that routes ISO 8583 payment messages between one or more upstream clients (card
networks/acquirers) and a downstream IMS Connect host (authorization system), with a crypto host
handling EMV cryptographic validation and a web dashboard managing/observing all components. The
router, and the three simulators standing in for real systems (crypto host, downstream host,
upstream host), are **C++**, built and run inside a Docker container. The web dashboard is
**Python**, running on the host, talking to every actor over plain HTTP.

This is a from-scratch C++ port of a working Java implementation of the same system
(`../router_java/build_router.md`). Behavior — wire formats, message flows, config semantics, and the
non-negotiable design principles below — is unchanged from that implementation, and is restated in
full below rather than left as a cross-reference: this document is self-contained, and no access to
the Java project's source is required to build this one. The Java doc's "C++ portability notes"
section was the starting point for every concurrency decision here.

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
  (container name `router_cpp`) is a drop-in replacement, not a side-by-side variant. It cannot run at
  the same time as a live `router_java` container.

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
├── Dockerfile                     # ubuntu:22.04 + cmake/g++/git/libssl-dev/pkg-config; builds at image-build time
├── docker-compose.yml             # one service, network_mode: host, launches all four actors
├── start.sh                       # docker compose up -d --build, then polls localhost:8080/stats
├── stop.sh                        # docker compose down
├── monitor.sh                     # runs the dashboard (Flask, port 8090) on the HOST
├── .gitignore                     # build/, logs/, upstream_1_input/, *.log, __pycache__/
├── config/
│   ├── router_1.json              # single shared config, read by all four binaries
│   ├── router_1_perf.json         # router_1.json, but crypto points at the shared crypto_host
│   │                               # container (localhost:5099) instead of this stack's own stub —
│   │                               # used only by stress_run.sh, never for functional testing
│   └── pans_defined.json          # card + key data for downstream_host and crypto_host
├── test_csv_files/                # mirror of routers/test_csv_files/ (the master), re-synced via
│                                   # routers/sync_test_csv.sh; host-side CSVs offered by the
│                                   # dashboard's CSV dropdown
├── monitor/                       # Python + Flask, runs on the HOST -- never bundled into the container
│   ├── main.py
│   └── static/index.html
├── src/
│   ├── shared/         framing.{h,cpp}, ebcdic.{h,cpp}, ims_connect.{h,cpp}, iso_codec.{h,cpp},
│   │                   stats.{h,cpp}, stop_event.h, log.{h,cpp}, command_server.{h,cpp},
│   │                   pans_defined.{h,cpp}, base64.{h,cpp}, hex.{h,cpp}
│   │                   (no crypto_utils here — see "Crypto validation has moved" below)
│   ├── router/         router_config.{h,cpp}, upstream.{h,cpp}, downstream_connection.{h,cpp},
│   │                   crypto_client.{h,cpp}, dispatcher.{h,cpp}, router_session.{h,cpp},
│   │                   router_main.cpp
│   └── simulators/{crypto_host,downstream_host,upstream_host}/*_main.cpp
└── test/               Catch2 unit + integration tests
```

`build/`, `logs/`, and `upstream_1_input/` (the CSV upload landing directory `upstream_host` creates
at its own working directory at runtime) are all gitignored, not part of the tracked layout above.

Every actor is its own executable, all linking a common static library for shared code (`xv6_shared`)
and the router-specific pieces linking `xv6_router` as well. There is no single "jar with many
main classes" equivalent here — CMake's natural idiom is one executable target per actor:

```
router_main     <- xv6_router, xv6_shared
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

## `CMakeLists.txt`

Every simulator links `xv6_router` as well as `xv6_shared` (not just `xv6_shared`) — all three of
them decode/encode ISO 8583 messages, and `downstream_host`/`crypto_host` both need
`shared/pans_defined.h`, so it's simplest for every actor to see the same include path
(`target_include_directories(... PRIVATE src)`) and link the same two static libraries rather than
carving out a narrower dependency graph per actor for marginal build-time savings.

```cmake
cmake_minimum_required(VERSION 3.20)
project(router_cpp CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()

find_package(OpenSSL REQUIRED)
find_package(Threads REQUIRED)

include(FetchContent)
FetchContent_Declare(httplib GIT_REPOSITORY https://github.com/yhirose/cpp-httplib.git GIT_TAG v0.15.3)
FetchContent_Declare(json    GIT_REPOSITORY https://github.com/nlohmann/json.git       GIT_TAG v3.11.3)
FetchContent_Declare(catch2  GIT_REPOSITORY https://github.com/catchorg/Catch2.git      GIT_TAG v3.5.4)
FetchContent_MakeAvailable(httplib json catch2)

add_library(xv6_shared STATIC
    src/shared/hex.cpp
    src/shared/base64.cpp
    src/shared/ebcdic.cpp
    src/shared/framing.cpp
    src/shared/ims_connect.cpp
    src/shared/iso_codec.cpp
    src/shared/stats.cpp
    src/shared/log.cpp
    src/shared/command_server.cpp
    src/shared/pans_defined.cpp
)
target_include_directories(xv6_shared PUBLIC src)
target_link_libraries(xv6_shared PUBLIC httplib nlohmann_json::nlohmann_json
                                          OpenSSL::SSL OpenSSL::Crypto Threads::Threads)

add_library(xv6_router STATIC
    src/router/router_config.cpp
    src/router/upstream.cpp
    src/router/downstream_connection.cpp
    src/router/crypto_client.cpp
    src/router/dispatcher.cpp
    src/router/router_session.cpp
)
target_include_directories(xv6_router PUBLIC src)
target_link_libraries(xv6_router PUBLIC xv6_shared)

add_executable(router_main src/router/router_main.cpp)
target_include_directories(router_main PRIVATE src)
target_link_libraries(router_main PRIVATE xv6_router xv6_shared)

add_executable(crypto_host src/simulators/crypto_host/crypto_host_main.cpp)
target_include_directories(crypto_host PRIVATE src)
target_link_libraries(crypto_host PRIVATE xv6_router xv6_shared)

add_executable(downstream_host src/simulators/downstream_host/downstream_host_main.cpp)
target_include_directories(downstream_host PRIVATE src)
target_link_libraries(downstream_host PRIVATE xv6_router xv6_shared)

# No upstream_host target - it's the shared routers/upstream_host Python component now, not a
# binary built here. See "upstream_host" below.

enable_testing()
file(GLOB TEST_SOURCES CONFIGURE_DEPENDS test/*.cpp)
add_executable(xv6_tests ${TEST_SOURCES})
target_link_libraries(xv6_tests PRIVATE xv6_router xv6_shared Catch2::Catch2WithMain)
include(CTest)
include(Catch)
catch_discover_tests(xv6_tests)
```

Each simulator's source file is named `<name>_main.cpp` (`crypto_host_main.cpp`, not `main.cpp`) —
three separate files that would otherwise all be called `main.cpp` living in different directories
works fine on disk, but named per-actor avoids any ambiguity in error messages, `#include` guards,
or an IDE's "which main.cpp is this" when several are open at once.

Build: `cmake -S . -B build && cmake --build build -j` produces `build/router_main`,
`build/crypto_host`, `build/downstream_host`, `build/xv6_tests` (no `upstream_host` - see below).

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

**Two more functions, added for `iso_codec`'s EBCDIC support** (see "ISO 8583 codec" below) — pure
byte-for-byte translation on the *same* lookup tables, deliberately **without** `to_ebcdic`'s
padding/truncation:

```cpp
std::vector<uint8_t> ascii_to_ebcdic_bytes(const std::vector<uint8_t>& ascii);
std::vector<uint8_t> ebcdic_to_ascii_bytes(const std::vector<uint8_t>& ebcdic);
```

`to_ebcdic`'s pad-with-EBCDIC-space/truncate-keeping-the-tail semantics are right for
`irm_id`/`client_id`/the PING marker, but wrong for `iso_codec`'s already-shaped field bytes
(space-padded ALPHA values truncated keeping the *head*, and LLVAR/LLLVAR length-prefix digits that
must not be padded/truncated at all) — reusing `to_ebcdic` directly there would silently corrupt
already-correct byte layouts. These two functions exist purely to avoid that mismatch: same table,
no shape opinion, output length always equals input length.

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

// Text fields (Alpha/Llvar/Lllvar, including LLVAR/LLLVAR length-prefix digits) and the MTI can
// be sent as EBCDIC (cp500) instead of ASCII, matching a real-world partner that speaks EBCDIC —
// see router_2's `upstream.encoding` config. Binary/Lllbin fields are raw bytes already, not
// text, and are never translated either way. Defaults to Ascii everywhere, so every call site
// that predates this enum (and router_1's config) is unaffected.
enum class Encoding { Ascii, Ebcdic };

std::vector<uint8_t> encode(const std::map<std::string, std::string>& data, Encoding encoding = Encoding::Ascii);
    // 1. mti = data.at("t") -> 4 ASCII (or, if Encoding::Ebcdic, cp500) characters on the wire,
    //    e.g. "0100" -> {'0','1','0','0'} translated byte-for-byte if EBCDIC (NOT the 16-bit
    //    binary value 0x0100 — that was this codec's original, buggy convention; see the
    //    cross-language wire-compat fix noted further down).
    // 2. Build the bitmap: for every field in FIELD_SPECS present in `data` (ascending field
    //    number), set that bit. Bit 1 (secondary bitmap present) is set automatically if any
    //    field > 64 is present; this project's field set never exceeds 64, so the primary
    //    bitmap alone always suffices today, but the encoder still emits a correct secondary
    //    bitmap if a future field addition ever needs one. The bitmap itself is always raw
    //    binary, never EBCDIC-translated, regardless of `encoding`.
    // 3. Write: MTI, 8-byte (or 16-byte) bitmap, then each present field's value encoded per its
    //    FieldSpec, in ascending field-number order:
    //      ALPHA:  fixed `length` bytes, space-padded/truncated, then EBCDIC-translated whole if
    //              Encoding::Ebcdic
    //      LLVAR:  2-digit ASCII decimal length prefix + value bytes, both EBCDIC-translated
    //              together as one unit if Encoding::Ebcdic (the length prefix must be EBCDIC
    //              too for a genuinely EBCDIC-speaking partner — see the j8583 cross-check note
    //              in ../router_java/build_router.md)
    //      LLLVAR: same as LLVAR but a 3-digit length prefix
    //      BINARY: fixed `length` bytes, zero-padded/truncated, never translated (unused today;
    //              specified for parity)
    //      LLLBIN: 3-digit ASCII decimal length prefix + raw bytes, never translated (unused
    //              today; specified for parity)

std::map<std::string, std::string> decode(const std::vector<uint8_t>& bytes, Encoding encoding = Encoding::Ascii);
    // 1. Read 4 MTI bytes -> data["t"], EBCDIC-decoded to ASCII first if Encoding::Ebcdic.
    // 2. Read the 8-byte primary bitmap; if bit 1 is set, read the 8-byte secondary bitmap too
    //    (bitmap bytes are never EBCDIC-translated).
    // 3. For each set bit (2..128), look up FIELD_SPECS[bit]; if absent from the table, throw
    //    (an unknown field number appearing on the wire is a hard decode error, not silently
    //    skipped — the Java version can't hit this case since j8583 only ever sets bits for
    //    fields the caller told it about, but a hand-rolled decoder must reject the case
    //    explicitly rather than reading garbage past a field it doesn't understand the length of).
    // 4. Decode that field's value per its type/length (ALPHA/BINARY: fixed width; LLVAR/LLLVAR/
    //    LLLBIN: read the N-digit length prefix — EBCDIC-decoded to ASCII first if
    //    Encoding::Ebcdic, since std::stoi needs real ASCII digits — then that many bytes,
    //    likewise EBCDIC-decoded) and insert into the map. Decoding genuinely EBCDIC bytes as
    //    Encoding::Ascii throws outright (the length-prefix bytes aren't valid ASCII digit
    //    characters), rather than silently producing garbage — a useful property the round-trip
    //    test in `test/` relies on to prove the bytes are genuinely EBCDIC on the wire.

bool is_known_field(const std::string& key);   // true if key parses as an int present in FIELD_SPECS
std::vector<uint8_t> build_0800(Encoding encoding = Encoding::Ascii);                       // {"t":"0800","24":"100"}
std::vector<uint8_t> build_0810(const std::string& f24, Encoding encoding = Encoding::Ascii); // {"t":"0810","24":f24}
std::string f47_encode(const nlohmann::json& data);              // JSON serialize
nlohmann::json f47_decode(const std::string& value);              // JSON parse; {} on error/blank
```

`Encoding::Ebcdic`'s field-level translation (both the length-prefix digits and the value bytes) is
implemented by running `encode_field()`'s fully-assembled output through the new
`ascii_to_ebcdic_bytes()` helper (see `ebcdic.h` above) in one pass, rather than translating the
length prefix and value bytes separately — since both are already-ASCII decimal digit or text
bytes at that point, a single byte-for-byte pass over the whole thing is correct and simpler than
special-casing the length prefix. `decode_field()` does the mirror image: read the raw bytes off
the wire first, `ebcdic_to_ascii_bytes()` them if `Encoding::Ebcdic`, then parse/interpret as
normal (so `std::stoi` on a length prefix always sees real ASCII digits, whichever wire encoding
was used).

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

### Crypto validation has moved to a shared container

`shared/crypto_utils.h`/`.cpp` (and their test, `test/crypto_utils_test.cpp`) — the MasterCard
M/Chip EMV operations (`derive_udk`, `derive_session_key`, `verify_arqc`,
`calculate_arpc_method1`, `verify_pin`, `verify_cvv2`, `verify_aav`, and their OpenSSL-backed 3DES/
HMAC-SHA1 plumbing) that used to live in this project — have been **deleted from router_cpp entirely**.
That real, OpenSSL-backed crypto logic is now the basis of a new standalone shared container at
`routers/crypto_host/` (its own CMake/C++ project), used by all three sibling implementations
(router_py, router_java, router_cpp) so that performance comparisons measure the same crypto backend instead of
each implementation's own simulator. See `routers/divide_and_conquer.md` for the full rationale and
`routers/crypto_host/build_router.md` for that container's own spec — not repeated here.

router_cpp's own `crypto_host` (`src/simulators/crypto_host/crypto_host_main.cpp`) is now just a
lightweight **stub**: no OpenSSL, no PIN/ARQC/CVV2/AAV math, no dependency on the fields above at
all. It exists purely so this implementation can still be built and tested standalone without the
shared container running — see `validate(pan, f47_in, pans)` under "Simulators" below for its
actual (much shorter) logic.

---

## `config/pans_defined.json`

Unchanged shape from the Java doc. Keys are PAN strings. The shared `routers/crypto_host/`
container's PAN table uses every field; this project's own (stub) `crypto_host` and its
`downstream_host` both only care about key presence, to decide PAN-known vs. unknown — the struct
still carries all six fields (`PanRecord` in `shared/pans_defined.h`) so the file's shape stays
identical across implementations, even though router_cpp's local stub never reads past presence:

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
"known" as far as the `pans_defined.count(pan)` check goes. This loader is unchanged in router_cpp
itself — it's the same code, and this project's own (stub) `crypto_host` still relies on it for its
presence check — but the PIN/ARQC/CVV2/AAV checks that actually *use* the other five fields no
longer run inside router_cpp at all (see "Crypto validation has moved to a shared container" above): a
malformed `pans_defined.json` here only breaks router_cpp's own PAN-known/unknown decision (`rc`
`"00"`/`"14"`), it can't produce the confusing `"55"`/`"82"`/`"N7"` symptom below. That symptom now
belongs entirely to the shared `routers/crypto_host/` container, which keeps its own copy of this
same loader and struct shape and does still run those checks: there, a missing key loads *without
error* and every PIN/ARQC/CVV2/AAV check using the empty-string fields fails for a reason that has
nothing to do with the wire data being tested — `verify_pin` compares against an empty
`reference_pin`, `derive_udk` runs on an empty `imk_hex`, etc. — producing declines that look like a
crypto bug in the *router* or *crypto_host* logic when the actual defect is a malformed config file
in the shared container. When debugging an unexpected decline during a perf run against the shared
container, check its `pans_defined.json`'s shape against the schema above (all six keys present,
non-empty) before suspecting the crypto code itself.

The Python (router_py) and Java (router_java) ports' own local stub crypto_hosts made the same move (presence
check only — `pan not in self.pans` / `pans.containsKey(pan)`), so the same "this pitfall no longer
bites inside the per-implementation project itself" logic applies to all three — it now lives
solely in the shared `routers/crypto_host/` container, which keeps its own copy of the real
PIN/ARQC/CVV2/AAV checks and is where a malformed `pans_defined.json` would actually surface this
symptom.

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

`upstream.encoding` (optional, `"ascii"` (default) | `"ebcdic"`) is the one addition since: governs
only the upstream-facing leg's wire encoding (MTI, and LLVAR/LLLVAR length-prefix digits + value
bytes — see `iso_codec::Encoding` below); the downstream-facing leg always stays ASCII, since it
still talks to the shared `downstream_host`. `router_1.json` omits it (defaults to ASCII, byte-for-
byte unchanged from before this field existed); `router_2.json` sets `"upstream": {..., "encoding":
"ebcdic"}` — see "`router_2`/`upstream_2`" below.

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

### `router_2`/`upstream_2` — a second partner, disabled by default

`config/router_2.json` + `config/upstream_2.json`: a second, independent router+load-generator
pair, `is_active: false` in both, mirroring router_py's `router/router_2`/`simulators/upstream_2`
pattern (and identically shaped to router_java's `config/router_2.json`/`config/upstream_2.json`).
`router_2` connects **out** to `upstream_2` (`"upstream": {"mode": "client", "host": "localhost",
"port": 5010, ...}`) rather than listening for it — the reverse of `router_1`'s `mode: "server"` —
while `upstream_2.json` (the shared `upstream_host` binary's own config shape, not a
`RouterConfig`) sets `"mode": "server"`. It reuses the **same already-running**
`downstream_host`/`crypto_host` as `router_1`, distinguished only by `downstream.client_id`
(`CLIENT03` vs `router_1`'s `CLIENT01`) — no second downstream/crypto binary is launched for it.

`router_2.json` sets `"upstream": {..., "encoding": "ebcdic"}` (see `iso_codec::Encoding` above) —
its upstream leg speaks EBCDIC, while the rest of its config (no `iso_spec` key exists in this
implementation at all, see above) means the downstream leg is unaffected, still ASCII, since it
still talks to the shared `downstream_host`, which doesn't understand EBCDIC. A literal
single-encoding swap on `router_2` — applying `Encoding::Ebcdic` to *every* `iso_codec::encode`/
`decode` call, not just the upstream-facing ones — would break its downstream leg outright:
`downstream_host` would fail to decode an EBCDIC frame and every request would time out
(`pending_ttl_seconds`) rather than complete. `config/upstream_2.json`'s own `iso_spec` points at
the shared `routers/upstream_host/test_spec_ebcdic.json` (a pure endpoint, no leg split needed
there).

**Actor discovery extended to support this**: see "Extended for `router_2`/`upstream_2`" under
Monitor below — this project's monitor previously read exactly one shared config file for all four
`router_1`-derived actors; `router_2`/`upstream_2` needed genuine per-actor config paths, the first
departure from that design.

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
        // 1. Connect to_fd to cfg.host:cfg.port with a 5s connect timeout implemented as
        //    non-blocking connect() + poll() (connect_with_timeout: set O_NONBLOCK, connect(),
        //    poll() up to 5000ms, then restore the original fcntl flags) — not a socket-level
        //    SO_RCVTIMEO, which would otherwise leak the connect-timeout onto subsequent blocking
        //    reads. Same requirement as the Java version, different mechanism (fcntl/poll vs.
        //    a receive timeout that needs clearing).
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

**DEBUG-level message tracing (new to this port — neither this doc's earlier drafts nor the Java doc
ever had a single call site at `LogLevel::Debug`/`Level.FINE`)**: the `DEBUG` level was fully plumbed
end-to-end (settable via `/log_level`, persisted, correctly displayed by the monitor once the
dropdown bug above was fixed) but had nothing to actually show — a user switching an actor to `DEBUG`
expecting to see per-message activity (e.g. periodic `0800` network-management pings) saw nothing new
at all, silently, with no error. `process()` and `handle_response()` each log one `LOG_DEBUG` line
per message: `"dispatcher: queued mti=<mti> (queue_depth=<n>)"` on submit, `"dispatcher: forwarded
mti=<mti> to downstream, upstream_stan=<x> router_stan=<y>"` after the downstream write, and
`"dispatcher: forwarded mti=<mti> to upstream, router_stan=<y> upstream_stan=<x>"` after the upstream
write.

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
- Loop: `framing::read_message(fd, cfg.upstream.framing)` → `iso_codec::decode` → `stats.record_recv()`
  → `LOG_DEBUG("upstream recv mti=" + mti)` (see the DEBUG-tracing note under `Dispatcher` above).
  - MTI `0100`/`0120`/`0420` → `dispatcher_.submit({req, fd, write_lock, addr})`.
  - MTI `0800` → `forward_0800(req)`.
  - anything else → log a warning.
  - A read error (covers both a genuine remote disconnect and a local close racing this blocked
    read during teardown) → log, set `reconnect_event`, break the loop.
- On exit: `stats.set_connection("upstream", false)`, clear the stashed upstream reference if it
  still points at this connection.

**`forward_0800(req)`**: re-encode, wrap in an IMS frame, `downstream.send(frame)`,
`stats.record_sent()`, `LOG_DEBUG("forwarded 0800 to downstream")` — wrapped in try/catch since
teardown on another thread can close the downstream connection out from under this write.

**`forward_0810(resp)`**: reads the stashed upstream reference under its lock; if none, log a
warning and return. Otherwise re-encode, acquire the upstream write lock, write, release,
`stats.record_sent()`, `LOG_DEBUG("forwarded 0810 to upstream")` — wrapped in try/catch, racing the
same teardown.

**`downstream_receiver()`** (the ds-receiver thread, not shown above): on each frame, if its first 4
bytes are the EBCDIC `"PING"` pipe-cleaner marker, `LOG_DEBUG("downstream PING pipe-cleaner received,
skipping")` and `continue` — otherwise decode, `stats.record_recv()`, `LOG_DEBUG("downstream recv
mti=" + mti)`, then dispatch to `forward_0810` (MTI `0810`) or `dispatcher_.handle_response` (anything
else).

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
    LOG_INFO("router command API listening on port " + std::to_string(cfg.command_port));

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
        LOG_INFO("router connected to downstream, dispatcher active");
        { std::lock_guard lock(active_dispatcher_mutex); active_dispatcher = /* alias into session */; }
        session->run_until_disconnect(srv_sock.get());
        { std::lock_guard lock(active_dispatcher_mutex); active_dispatcher = nullptr; }
        if (!stop_event.is_set()) {
            LOG_INFO("router session ended, reestablishing");
            wait_reestablish(stop_event, cfg);
        } else {
            LOG_INFO("router session ended, stop requested");
        }
    }
    cmd.stop();
    return 0;
}
```

`wait_reestablish` waits `reestablish_seconds + uniform(0, reconnect_jitter_seconds)` — the jitter
avoids multiple routers sharing a downstream/crypto host from reconnecting in lockstep after a
shared outage.

**Pitfall — `router_main` must log *something* at `INFO` level on the happy path, not only on
warnings/errors, or its `/logs` is indistinguishable from broken.** Unlike the three simulators
(each of which logs an explicit `"<actor> listening on port <N>"` line right after `cmd.start()`),
it's easy to write `router_main`'s loop with only `LOG_WARNING`/`LOG_ERROR` calls — there's no
*correctness* reason it needs more, since the router's actual job is proxying bytes, not announcing
milestones. But the dashboard's log viewer (see "Monitor" below) has no way to distinguish "actor
running fine, nothing noteworthy has happened" from "actor's logging is broken" — both look like an
empty modal with nothing but the Export button. A router that ran an entire successful multi-hour
test session without a single reconnect would have a permanently empty log, which reads as "this
feature doesn't work" the first time someone opens it during exactly that kind of clean run. Log the
command port on startup and both ends of a session (connected / ended, distinguishing "reestablishing"
from "stop requested" so the two don't read as identical) — matching the same "listening on port"
convention the three simulators already establish, for the same reason: a monitor's log viewer needs
routine positive signal, not just failure signal, to be trustworthy at a glance.

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

This is router_cpp's own **stub** implementation — no OpenSSL, no PIN/ARQC/CVV2/AAV math. The real
crypto validation logic this section used to describe now lives only in the shared
`routers/crypto_host/` container; see "Crypto validation has moved to a shared container" above.

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
   `stats.record_recv()` once the body is successfully parsed. (The stub, like the real crypto
   host, decodes `f47` via `iso_codec::f47_decode` before calling `validate` but never reads
   `operation` — every field of the enriched f47 it doesn't set is passed through unchanged.)
4. Response: run `validate(pan, f47, pans)` to get the enriched `f47`, encode `{"f47": enriched_f47}`
   as a JSON string, base64-encode that string, write the base64 text as the literal JSON response
   body (a quoted string, not an object) — the `PluginOutput` envelope. `stats.record_sent()` once
   the response body is written. (Both counters are easy to half-wire — `record_sent()` is the
   obvious one since it sits right next to constructing the response, but `record_recv()` on the
   request side is just as required for `/stats` to mean anything; omitting it doesn't fail any
   test, it just leaves `recv_total` at zero forever, which only shows up much later as "why does
   the monitor say crypto_host is silently starved.")

**`validate(pan, f47_in, pans)` logic** — the entire stub, pure business logic unaware of the HTTP
envelope:
1. Copy `f47_in` into the result (`f47`) unchanged.
2. Set `f47["response_code"]` to `"14"` if `pan` is not a key in `pans` (the loaded
   `std::map<std::string, PanRecord>`), otherwise `"00"`.
3. Return `f47`.

That's the whole function — it never inspects `message_type`, `f52`, `f55`, `cvv2`, or `aav`, and it
performs no PIN/ARQC/CVV2/AAV math and no ARPC computation. The router still always calls crypto
regardless of whether f47/f55 is present, exactly as before; the stub's response now only reflects
whether the PAN is provisioned, not any per-field cryptographic outcome. The real per-field checks
and ARPC computation only happen when the router is pointed at the shared `routers/crypto_host/`
container (see `config/router_1_perf.json` and the `ROUTER_CONFIG` mechanism under "Container"
below).

### `downstream_host` (now the shared `../downstream_host/main.py`)

**Moved**: `downstream_host_main.cpp` is gone — `downstream_host` is now the shared
`routers/downstream_host/` Python component (see `../downstream_host/build_router.md`), launched
as a host subprocess like `upstream_host`, not one of this container's own binaries. It previously
read its settings from a nested block inside the shared `config/router_1.json`; now it has its own
flat `config/downstream_host.json` / `downstream_host_perf.json` (this implementation's own
config, extracted from that nested block plus the top-level `pans_defined`/`iso_spec` it used to
inherit implicitly — `iso_spec` now points at `../../upstream_host/test_spec.json`, the pyiso8583
JSON format the shared component needs). The architecture notes below describe the now-retired
C++ implementation, kept for historical reference.

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

### `upstream_host` — now the shared `routers/upstream_host/` component

`upstream_host_main.cpp` was deleted (and its CMake target removed) — `upstream_host` was
promoted out of all three implementations into a standalone Python component shared by
router_py/router_java/router_cpp (`routers/upstream_host/`, host-side process, not containerized). See
`../divide_and_conquer.md` (part 2) for why, and `../upstream_host/build_router.md` for the full
spec (endpoints, config schema, framing, CSV format, send/receive/keepalive loop internals — all
a straight line-by-line port of what used to be documented here, unchanged in behavior).

**Real wire-compat bug found migrating to it**: this codec's `encode()`/`decode()` wrote the MTI
as 2 raw binary bytes (`mti >> 8` / `mti & 0xff`), but pyiso8583 (and j8583) encode it as 4 ASCII
characters ("0100"). This was invisible before the migration because this router had only ever
been tested against its own same-language `upstream_host`, which used this same codec on both
ends (internally consistent, but not matching Python/Java). Fixed in `iso_codec.cpp`'s
`encode()`/`decode()` to read/write the MTI as 4 ASCII bytes directly instead of round-tripping
through a `uint16_t`. The bitmap encoding needed no fix — this codec already used raw binary
bytes for it (`std::array<uint8_t, 16> bitmap`), matching pyiso8583's convention by coincidence
rather than by any shared source of truth (see the note in `../divide_and_conquer.md` about
`test_spec` needing to become that source of truth, not per-language hardcoded assumptions).

**Integration points that remain locally relevant:**
- **Launch mechanism**: this implementation's stack is docker-compose-managed
  (crypto_host/downstream_host/router_main run as background processes inside one container),
  but `upstream_host` no longer does — `run_test.sh`/`stress_run.sh` bring up the compose stack
  via `./start.sh` first, then separately launch the shared component as a bare host subprocess
  (`python3 ../upstream_host/main.py --config ../upstream_host/config.json &`) once the router is
  confirmed listening. Teardown changed to match: `./stop.sh` (`docker compose down`) no longer
  reaches it, so `cleanup()` also does `POST :8083/stop` first.
- **Monitor integration**: `monitor/main.py` synthesizes all four logical actors from
  `config/router_1.json`'s nested blocks rather than scanning a directory (no per-actor config
  files to begin with, so no discovery gap like router_py's/router_java's) — the `upstream` entry's
  `command_port` still comes from that file's `upstream.command_port` (router_main still needs
  that block for its own listen socket), but `launch_actor()`/`actor_commands()` branch on
  `actor["type"] == "upstream"` to use a host `subprocess.Popen` instead of `docker exec -d`, and
  to show a plain `kill <pid>` instead of a `docker exec ... kill` command.

---

## Monitor (`monitor/main.py`, Python + Flask, runs on the **host**)

A thin dashboard that talks to every actor's `CommandServer` purely over HTTP (`/stats`, `/stop`,
`/log_level`, `/logs`, plus `upstream_host`'s `/start`/`/results`/`/upload`) — it has no idea, and no
reason to care, what language runs behind a command port; the only contract that matters is those
HTTP routes, specified exactly above. Never bundled into the container image (no Python in the
`Dockerfile`, deliberately) — it only needs plain HTTP to `localhost`, which `network_mode: host` on
the `router_cpp` service already provides.

**Dependencies**: `flask`, `requests`, installed on the host (not the container) via
`pip install flask requests` or equivalent.

**Pitfall — actor discovery must be adapted for this project's single-shared-config reality.** A
prior design for this kind of monitor (used by an earlier, structurally different sibling project in
this repo family) assumed one JSON file per actor under `config/`, each with its own `name`/`type`/
`command_port`, and discovered actors by scanning that directory. **This project does not work that
way**: all four binaries load the *same* `config/router_1.json` (see `RouterConfig::from_file`
above), which has `command_port`/`command_auth_token` at the top level for the router itself, and a
per-actor `command_port` nested inside its own `upstream`/`downstream`/`crypto` sub-object for the
other three. `discover_actors()` therefore does not scan a directory — it reads the one file once
(cached for the monitor's process lifetime; restart the monitor to pick up a config edit) and
synthesizes four logical actor descriptors from it:

```python
CONFIG_REL_PATH = "config/router_1.json"   # relative to the project root

def discover_actors():
    with open(PROJECT_ROOT / CONFIG_REL_PATH) as f:
        cfg = json.load(f)
    return [
        {"name": cfg.get("name", "router_1"), "type": "router",
         "command_port": cfg.get("command_port", 8080),
         "auth_token": cfg.get("command_auth_token"),
         "partner_id": cfg.get("partner_id"), "is_active": True},
        {"name": "downstream_host", "type": "downstream",
         "command_port": cfg.get("downstream", {}).get("command_port", 8081),
         "auth_token": None, "partner_id": None, "is_active": True},
        {"name": "crypto_host", "type": "crypto",
         "command_port": cfg.get("crypto", {}).get("command_port", 8082),
         "auth_token": None, "partner_id": None, "is_active": True},
        {"name": "upstream_host", "type": "upstream",
         "command_port": cfg.get("upstream", {}).get("command_port", 8083),
         "auth_token": None, "partner_id": None, "is_active": True},
    ]
```

**Extended for `router_2`/`upstream_2` — a second, genuinely per-actor-config pair.** The
single-shared-config design above still holds for `router_1`'s four actors, but a second,
independent router+load-generator instance (`config/router_2.json` + `config/upstream_2.json`,
`is_active: false` in both, mirroring router_py's `router/router_2`/`simulators/upstream_2`
pattern) needed real per-actor config paths — the first departure from "one shared file" this
project has had. `discover_actors()` conditionally loads these two extra files, if present, and
appends two more synthesized entries:

```python
def _load_router_2_actors():
    actors = []
    router2_path = PROJECT_ROOT / "config" / "router_2.json"
    if not router2_path.exists():
        return actors
    with open(router2_path) as f:
        cfg2 = json.load(f)
    actors.append({
        "name": cfg2.get("name", "router_2"), "type": "router",
        "command_port": cfg2.get("command_port", 8085),
        "auth_token": cfg2.get("command_auth_token"), "partner_id": cfg2.get("partner_id"),
        "is_active": cfg2.get("is_active", False),
        "config_abs_path_in_container": "/config/router_2.json",
    })
    upstream2_path = PROJECT_ROOT / "config" / "upstream_2.json"
    if upstream2_path.exists():
        with open(upstream2_path) as f:
            ucfg2 = json.load(f)
        actors.append({
            "name": ucfg2.get("name", "upstream_2"), "type": "upstream",
            "command_port": ucfg2.get("command_port", 8086),
            "auth_token": None, "partner_id": None,
            "is_active": ucfg2.get("is_active", False),
            "upstream_config_path": upstream2_path,   # NOT the shared UPSTREAM_HOST_DIR/config.json
        })
    return actors
```

This is why every actor dict — including the original router_1-derived four — now carries its own
`config_abs_path_in_container` (`CONFIG_ABS_PATH_IN_CONTAINER` stays as the module-level *default*
those four still use, but `launch_actor()`/`actor_commands()`'s `docker exec` command string and
kill-pattern now read `actor["config_abs_path_in_container"]`, not the global constant directly) —
without this, `router_1` and `router_2`'s kill patterns would collide (`router_main --config
/config/router_1.json` would match both, since only the config path distinguishes them, and only
one has the wrong path if the constant weren't parameterized). `upstream_2`'s entry similarly
carries its own `upstream_config_path` so `launch_actor()` passes `--config
<router_2's-own-upstream_2.json>` to the shared `upstream_host/main.py` binary, instead of the
default `UPSTREAM_HOST_DIR/config.json` used for `upstream_1`.

`router_2` reuses the **same already-running** `downstream_host`/`crypto_host` as `router_1`
(distinguished only by `downstream.client_id`, `CLIENT03` vs `CLIENT01`) — no second
downstream/crypto actor is synthesized for it, so `discover_actors()` still only ever produces at
most 6 entries total (4 from `router_1.json` + up to 2 from `router_2`/`upstream_2`), not 8.

**Auth headers are per-actor, not uniform.** Only the router's `CommandServer` is constructed with a
`command_auth_token` (`cfg.command_auth_token`, from the top-level config key); the three
simulators' `CommandServer`s are all constructed with no auth token at all (`std::nullopt`), so
`CommandServer`'s own `wrap_handler` skips the auth check entirely for them (see `command_server.h`
above — the check only runs `if (auth_token_)`). Every route below that proxies to a protected actor
route (`/stop`, `POST /log_level`, `/dispatcher/purge`) must send `X-Router-Auth: <auth_token>` when
the target actor's descriptor has one, and no such header otherwise — sending a header to an actor
that isn't expecting one is harmless (ignored), but relying on that rather than checking `auth_token`
per actor would silently break the moment any of the three simulators is later given its own token.

```python
BINARY_BY_TYPE = {
    "router": "router_main", "upstream": "upstream_host",
    "downstream": "downstream_host", "crypto": "crypto_host",
}
STARTUP_ORDER = {"crypto": 0, "downstream": 1, "router": 2, "upstream": 3}
CONTAINER_NAME = "router_cpp"
CONFIG_ABS_PATH_IN_CONTAINER = "/config/router_1.json"   # per docker-compose.yml's volume mount
BUILD_DIR_IN_CONTAINER = "/src/build"
LOGS_DIR_IN_CONTAINER = "/src/logs"
```

**`launch_actor(actor)`**: `docker exec -d <container> bash -c "mkdir -p /src/logs &&
/src/build/<binary> --config /config/router_1.json > /src/logs/<name>.console.log 2>&1"` — the
`bash -c` wrapper (rather than invoking the binary bare) exists specifically to redirect
stdout/stderr to a per-actor log file, since `docker exec -d`'s own client process detaches and
exits the instant the command starts — without the redirect, a crash's stderr goes nowhere
retrievable. The log file is truncated on every (re)launch (`>`, not `>>`) so a live `tail -F` always
reflects the current run. Note that all four actors are typically already running by the time the
monitor starts (`docker-compose` launches them directly at container start — see "Container" below)
— `launch_actor` matters for restarting one specific actor after it was stopped or killed, not for
the common "everything's already up" case.

**`is_running(actor)`**: there is no OS process handle to poll — `docker exec -d`'s client exits
immediately once the detached command starts inside the container, and even the actors started
directly by `docker-compose`'s own entrypoint script aren't spawned by *this* Python process either
way. Liveness is instead defined as "the actor's own `/stats` endpoint answers HTTP 200" —
arguably more honest for a dev tool regardless of the transport, since a process that's alive but
wedged wouldn't help an operator either.

**`wait_for_ready(actor, timeout=10)`**: polls `/stats` until it answers 200, **and** — for the
router, until `connections.downstream == true`; for `upstream_host`, until `connections.router ==
true`; every other actor type is ready as soon as `/stats` answers. Skipping the connection check
means launching an upstream and immediately calling `/start` can 503 with "not connected to router"
even though `/stats` itself already answers 200 — the HTTP server coming up and the actor's own
TCP-level connection to its peer coming up are two different milestones.

**Monitor API routes**:

| Route | Purpose |
|---|---|
| `GET /` | serve `static/index.html` |
| `GET /api/actors` | list: name/type/command_port/running/is_active/partner_id |
| `GET /api/routers_by_partner` | dict `partner_id → [{name, command_port}]` (falls back to the literal key `"default"` when `partner_id` is unset, since this project's `router_1.json` doesn't set one) |
| `GET /api/status` | parallel `/stats` health check per actor; green/yellow/red |
| `GET /api/starting` | `{"starting": bool}` — true while a background "start all" is in flight |
| `GET /api/csv_files` | `*.csv` under `test_csv_files/` at the project root (host-side; does not enumerate an upstream's own in-container `input_dir`) |
| `GET /api/commands` | `{"shell": "docker exec -it router_cpp bash"}` |
| `GET /api/actor/<name>/commands` | `{"kill": <script>, "tail": <command>}` — see below |
| `POST /api/actor/<name>/launch` | start if not already running |
| `POST /api/actor/<name>/stop` | proxy to the actor's `/stop`, then poll liveness down to confirm |
| `GET /api/actor/<name>/stats` | proxy `/stats` |
| `GET /api/actor/<name>/start` | proxy `/start` (`upstream` type only — 404 otherwise) |
| `GET /api/actor/<name>/results` | proxy `/results` (`upstream` type only) |
| `GET\|POST /api/actor/<name>/log_level` | proxy log level (auth header added on POST if the actor has a token) |
| `GET /api/actor/<name>/logs` | proxy `/logs`; `?format=text` for plain text |
| `POST /api/actor/<name>/upload` | proxy a multipart CSV upload (`upstream` type only) |
| `POST /api/actor/<name>/upload_path` | upload a host-relative file by path (`{"path": "..."}`) — path is resolved and checked against the project root (`Path.is_relative_to`) before opening, to reject anything that escapes it |
| `POST /api/actor/<name>/dispatcher/purge` | `router` type only; proxies the protected `/dispatcher/purge` with the router's auth header |
| `POST /api/start_all` | background thread: launch every active actor not already running, in `STARTUP_ORDER`, waiting up to 10s each for readiness |
| `POST /api/stop_all` | stop every running actor, in reverse `STARTUP_ORDER` |
| `POST /stop` | stop the monitor itself: best-effort `/stop` to every running actor first (background thread), then `os._exit(0)` after a short delay so the HTTP response can actually be sent before the process exits |

**Status logic** (per actor, for `/api/status`): fetch `/stats`; non-200 or unreachable → red; no
`yellow_threshold_seconds` key in the response → green; `seconds_since_last_recv` is `null` or
exceeds that threshold → yellow; otherwise green.

**Shutdown safety net**: `POST /stop` spawns a background thread that best-effort `POST`s `/stop` to
every currently-running actor (swallowing any error per actor, since one unreachable actor shouldn't
block the rest), waits briefly, then calls `os._exit(0)`. There is no process handle to fall back on
if an actor ignores its own `/stop` — `./stop.sh` (`docker compose down`, tearing down the whole
container) is the hard backstop if an actor's HTTP `/stop` doesn't work.

**Container console visibility** (`/api/actor/<name>/commands`) — rather than embedding a real
interactive terminal in the browser (rejected: the monitor binds `0.0.0.0:8090`, LAN-reachable, and
shipping an unauthenticated shell into the container over HTTP isn't worth it for a dev tool), the
dashboard hands the operator two copy-pasteable commands per actor:
- **`kill`**: a small multi-line script (readable before running, not a single opaque one-liner) —
  finds the PID by matching the **full binary path + config argument string** via `ps` (not just
  the bare binary name, which keeps this safe if a future multi-router scenario means two instances
  share a name):
  ```bash
  PATTERN="/src/build/router_main --config /config/router_1.json"
  PID=$(docker exec router_cpp sh -c "ps -eo pid,args" | \
        awk -v pat="$PATTERN" '{cmd=$0; sub(/^[ \t]*[0-9]+[ \t]+/, "", cmd);
                                 if (index(cmd, pat) == 1) print $1}')
  if [ -z "$PID" ]; then echo "no matching process"; exit 1; fi
  docker exec router_cpp kill -9 "$PID"
  ```
  **Pitfall — the match must be anchored to the start of the command, not a bare substring search.**
  PID 1 inside the container is `docker-init`/`tini` (see `init: true` under "Container" above), and
  `ps` shows *its* `args` as the entire wrapped shell script text passed to `bash -c` — i.e. every
  actor's full invocation, concatenated, as one long string. A plain `grep -F "$PATTERN"` matches
  that line too (the pattern is trivially a substring of the whole script), and since `ps` lists PID
  1 first, `awk '{print $1}'` over multiple matching lines yields both PIDs concatenated
  (`"1\n11"`), which then fails to parse as a single `kill -9` argument — the safe failure mode here,
  but only by luck (a `PID` variable holding a single stray digit instead of two newline-joined ones
  could easily have resolved to PID 1 alone and torn down the entire container instead of the one
  actor requested). The `awk` version above strips the leading PID column from each candidate line
  first, then requires the pattern to match starting at position 1 of what's left (`index(cmd, pat)
  == 1`) — i.e. the command must *start with* the pattern, not merely contain it anywhere — which
  excludes `docker-init`'s line (its `args` starts with `/sbin/docker-init -- bash -c ...`, not the
  actor's own binary path) while still matching the real actor process.
- **`tail`**: `docker exec router_cpp tail -F /src/logs/<name>.console.log`. Only meaningful for an
  actor that was (re)started via the dashboard's own `launch_actor` — one still running from
  `docker-compose`'s original startup script was never redirected to a per-actor log file in the
  first place (its stdout/stderr instead went to the container's own combined log, viewable via
  `docker compose logs -f`), so `tail`-ing that file will report "no such file" until the actor is
  restarted through the dashboard at least once.

### `monitor/static/index.html`

Single-page vanilla JS, no build step, no framework — talks only to the monitor's own `/api/*`
routes above.

**Layout**: header (title + Start All / Stop All + a "starting…" indicator while `/api/starting` is
true) → router-partner groups (one `<h2>` + card grid per distinct `partner_id`, `"default"` when
unset) → a "Simulators" heading with a card grid for `crypto_host`/`downstream_host`/`upstream_host`
→ a test-runner panel (upstream selector, a CSV dropdown sourced from `/api/csv_files` plus a raw
file-upload input, a **Refresh List** button next to the dropdown, Upload/Start buttons, a results
table).

**Pitfall — the CSV dropdown is empty by default, and looks broken rather than "just empty" until
you know why.** `test_csv_files/` isn't created by `git clone`/a from-scratch checkout (nothing
seeds it, and it's reasonable to keep it out of version control if its contents are throwaway test
fixtures) — `/api/csv_files` correctly returns `[]` against a missing directory rather than erroring,
so the dropdown silently has nothing but its placeholder option and gives no indication *why*. Create
`test_csv_files/` with at least one `.csv` (matching the semicolon/BOM format documented under
`upstream_host` above) as part of first-time setup, not left for a user to discover is missing.
Additionally: the dropdown is only populated once, at page load (`refreshCsvList()` runs on load,
not on the 2-second `/api/status` poll interval that keeps everything else current) — a CSV added
to the directory *after* the page was already open won't appear until either the page is reloaded
or the **Refresh List** button next to the dropdown is clicked; this is deliberate, not a bug (an
`/api/csv_files` filesystem scan doesn't need to run every 2 seconds alongside the actor-status
polling, which is genuinely time-sensitive), but a user unaware of that button will reload the whole
page unnecessarily.

**Per-actor card**: a status dot (from `/api/status`), one small dot per key in `stats.connections`
(green if `true`, red if `false`), sent/recv counters (total, 30s, 60s), last-recv time, a log-level
`<select>`, and Logs/Commands/Start/Stop buttons. The router's card additionally shows
`gauges.queue_depth`/`gauges.pending_count` and a confirmation-gated ("this will drop in-flight
transactions") Purge Queue button, proxying `POST /api/actor/<name>/dispatcher/purge`.

**Polling**: `/api/actors`, `/api/status`, and `/api/starting` every 2 seconds (one combined refresh
cycle re-renders every card).

**Results table columns**: PAN (field `2`), RC (field `39`, highlighted green when `"00"`), Auth
code (field `38`), Field 47 (truncated to ~40 characters with the full value in a hover tooltip).

**Log viewer modal**: fetches `/logs?format=text` for the selected actor, auto-refreshes every 2s
while open, has an export-to-file button (client-side `Blob`/`URL.createObjectURL`, no server round
trip needed for the download itself).

**Log-level display (fixed; this was an open bug in the Java doc's original design, carried forward
once in this doc and now corrected)**: `actor_status()` on the monitor backend fetches `GET
/log_level` alongside `GET /stats` and folds the result into `stats.log_level`, so `/api/status`
reports each actor's real current level, not just its traffic counters. On the frontend, the
`<select>`'s `selected` option is computed from `stats.log_level` instead of being hardcoded to
`INFO`, and a client-side `pendingLogLevel` map records the level the user just picked immediately
on `change` (before the `POST /log_level` round-trip resolves) and keeps that value authoritative
across renders until a subsequent poll's `stats.log_level` echoes it back — this avoids reverting to
a stale value while the POST is in flight.

Getting the *value* right wasn't sufficient on its own, though: the original per-poll re-render
(`container.innerHTML = allCardsHTML`, rebuilding every card from scratch every 2s) unconditionally
destroys and recreates every `<select>` on each tick, including whichever one the user currently has
open. A first attempt at fixing this tracked which actor's `<select>` had focus and re-focused the
freshly-rebuilt replacement afterward — that's not enough: assigning a parent's `innerHTML` removes
*all* existing children before the new ones are parsed in, so the old (focused, possibly
mid-native-dropdown) `<select>` is torn out of the document regardless of whether a replacement gets
refocused afterward. In practice this meant a poll tick landing while the user had the dropdown
physically open — trivially possible, since opening a picker and clicking an option easily spans
more than the 2-second poll interval — would silently close it and discard the click, which is
exactly the "selecting DEBUG doesn't do anything" symptom this was meant to fix. (It also meant
naively reading the focus-tracking variable *after* the rebuild doesn't work either: removing a
focused element from the DOM fires its `blur` handler synchronously, nulling the tracking variable
out before any post-rebuild code runs — it must be snapshotted into a local before the rebuild.)

The actual fix (`patchCards()`) abandons whole-container `innerHTML` rebuilds in favor of patching
one `.card` element at a time: for each actor, if it's not the one whose `<select>` currently has
focus (tracked via `onfocus`/`onblur` into `focusedLogLevelActor`), replace just that card's
`outerHTML`; if it *is* the focused actor, skip it entirely for this tick, leaving its DOM node —
and any open native dropdown, and whatever option the user is mid-click on — completely untouched.
Once the user commits a selection, `onchange` calls `this.blur()` so the card resumes normal
per-poll updates on the next tick. Router cards are patched the same way inside a per-partner
`<section data-partner="...">` wrapper (created once and reused, rather than being torn down and
recreated every tick like the rest of `#router-groups` previously was), so a focused router card
survives poll ticks the same way a simulator card does.

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

All four binaries are built into the image itself (at `docker build` time) and launched together
as one `docker-compose` service — **not** the idle-container-plus-`docker exec` pattern some sibling
projects in this repo family use. Simpler for this project's scope: one container, one command,
`network_mode: host` so every actor's port is directly reachable at `localhost` from both the other
actors and the host-side monitor, with no port-mapping bookkeeping.

**`Dockerfile`**:
```dockerfile
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    cmake g++ git libssl-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY . .

# -j2, not -j$(nproc) -- see the OOM pitfall below.
RUN mkdir -p build && cd build && \
    cmake -DCMAKE_BUILD_TYPE=Release .. && \
    make -j2

RUN mkdir -p /config
ENV LD_LIBRARY_PATH=/usr/local/lib:/usr/lib
ENV PATH=/src/build:$PATH
EXPOSE 5000 5001 5002 8080 8081 8082 8083
CMD ["/bin/bash"]
```

**`docker-compose.yml`**: one service, `network_mode: host`, binds `./config` to `/config` (the
config file and `pans_defined.json` live here, editable on the host without a rebuild) and `./src`
to `/src/src` (source visible for reference/debugging — irrelevant to the already-built binaries in
`/src/build`, which aren't affected by this mount since only `/src/src` is bound over). `init: true`
tells Docker Compose to run a minimal init process (`tini`) as the container's actual PID 1, ahead of
the `command` below — see the pitfall immediately after for why this isn't optional. The `command`
launches all four actors in the background and then idles forever (`sleep infinity`), rather than
`wait`ing on them or `exec`ing the last one. `crypto_host`/`downstream_host`/`upstream_host` always
read `router_1.json` unconditionally; only `router_main`'s `--config` varies, via
`${ROUTER_CONFIG:-router_1.json}` — see the pitfall right after the listing for why that default
matters.

```yaml
services:
  router_cpp:
    build: .
    container_name: router_cpp
    network_mode: host
    init: true
    volumes:
      - ./src:/src/src
      - ./config:/config
    environment:
      - CONFIG_PATH=/config/router_1.json
    command:
      - bash
      - -c
      - |
        /src/build/crypto_host --config /config/router_1.json &
        /src/build/downstream_host --config /config/router_1.json &
        /src/build/router_main --config /config/${ROUTER_CONFIG:-router_1.json} &
        sleep infinity
```

**Pitfall — a multi-line double-quoted YAML scalar for `command` (`command: bash -c "` followed by
further lines, closed on a later line) is fragile and can fail to parse at all**, with an unhelpful
`go-yaml load error in scanner (while scanning a quoted scalar) ... found unexpected end of stream`
that gives no hint the fix is "use a different YAML construct," not "there's a typo somewhere in
this string." Use the YAML list-plus-literal-block-scalar form shown above instead (`command:` as a
list, whose last element is a `|` block scalar containing the actual multi-line script) — it parses
unambiguously and needs no escaping for the embedded quotes/newlines a shell script naturally has.

**Pitfall — `${VAR}` inside the `command` block scalar is interpolated by docker compose against
the HOST's shell environment / `.env` file at `docker compose up` parse time, not against the
container's own `environment:` block at container-runtime, and a bare reference with no default
silently blanks out if the host doesn't have it exported.** `ROUTER_CONFIG` exists so perf runs
(`stress_run.sh`, via `ROUTER_CONFIG=router_1_perf.json ./start.sh`) can point just `router_main`'s
`--config` flag at `config/router_1_perf.json` — which differs from `router_1.json` only in its
`crypto.port` (`5099` instead of `5002`, i.e. the shared `routers/crypto_host/` container instead of
this stack's own local stub) — without touching the other three actors' config. The `command`
string is YAML, but it's still a shell script, and docker compose treats `${...}` anywhere in the
whole compose file (including inside that multi-line string) as a substitution against the host
environment it sees when it parses the file — never against the sibling `environment:` block a few
lines above, which only takes effect *inside* the container after it starts. The first version of
this had a bare `${ROUTER_CONFIG}` with no default: on any host that hadn't exported the variable,
compose silently substituted the empty string, producing `--config /config/` (no filename at all)
in `router_main`'s actual argv. `router_main` then failed to start with no message that pointed at
the cause — `docker compose logs` had to be checked to see the failure at all, since the other three
actors started fine and the container itself kept running (`sleep infinity` never cared). The fix
is the inline default shown above, `${ROUTER_CONFIG:-router_1.json}`, directly in the command string
itself — never rely on an external `.env` file or documentation to guarantee the variable is always
set before `docker compose up` runs.

**Pitfall — the container's own lifecycle must be decoupled from every individual actor's
lifecycle, or the dashboard's per-actor stop/restart and `/api/stop_all`+`/api/start_all` break in a
way that only shows up once you actually drive them, not during a plain build-and-smoke-test.** Two
tempting-looking `command` endings both fail this, for different reasons:
- **`... & exec /src/build/router_main --config /config/router_1.json`** (background the first
  three, `exec` the last, no `init: true`): `exec` replaces the shell's own process image without
  forking, so `router_main` becomes the container's PID 1. That sounds like a feature (`docker
  stop` delivers `SIGTERM` straight to a real actor instead of an intermediary shell) but it means
  stopping *just the router* — including via the router's own `/stop` HTTP route, which is
  precisely what the dashboard's `/api/actor/<router>/stop` and `/api/stop_all` call — terminates
  the **entire container** the instant `router_main`'s `main()` returns, since a container's
  lifetime is tied to whether its PID 1 is still running. Every other actor gets hard-killed along
  with it (observed as the container exiting with code 139), and any subsequent
  `docker exec -d ...` to relaunch anything fails outright because the container no longer exists.
- **`... & /src/build/router_main --config /config/router_1.json & wait`** (background all four,
  then a bare `wait` with no `-n`): fixes the "stopping just the router kills everything" problem,
  but introduces a different one — `wait` (no arguments) blocks until *every* backgrounded job has
  exited, so stopping all four actors via the dashboard's `/api/stop_all` (a legitimate, intended
  operation — "pause everything, inspect state, restart") makes the wrapper script itself finish and
  exit, which **still** ends the container (cleanly, exit code 0 this time, but just as unable to
  `docker exec` anything back in afterward).

The fix needs both pieces together: `init: true` (so `tini`, not `bash` or `router_main`, is the
real PID 1 — a plain child of `tini` exiting doesn't end the container) *and* ending the script with
an unconditional `sleep infinity` instead of `wait` (so the wrapper script — and therefore the
container — stays alive regardless of whether zero, some, or all four actor processes are still
running). With both in place: killing or stopping any subset of actors, including all four, leaves
the container itself running and `docker exec -d`-reachable; `docker stop`/`docker compose down`
still tears the whole thing down via `SIGTERM` to `tini` (forwarded to the wrapper script, whose
default handling for an unhandled `SIGTERM` terminates it) with `SIGKILL` of the whole cgroup as the
guaranteed fallback after the grace period, regardless of whether every child received or handled
the signal individually.

**`start.sh`**: `docker compose up -d --build`, then polls `http://localhost:8080/stats` (the
router's command port) up to 30 times, 1s apart, before reporting ready — `--build` means every
invocation re-verifies the image is current, at the cost of a full rebuild whenever the Dockerfile
or any `COPY`'d source file changed since the last build (Docker's own layer cache still short-
circuits an invocation where nothing changed).

**`stop.sh`**: `docker compose down` — stops and removes the container. `SIGTERM` reaches
`router_main` directly (see the `exec` note above); no actor-level graceful-shutdown handling is
required for this to work, since the whole container is being torn down anyway, not just one actor.

**`monitor.sh`**: checks that the `requests` and `flask` Python packages are importable, then runs
`python3 monitor/main.py` in the foreground (`Ctrl+C`, or the dashboard's Stop-All-then-`/stop`
path, to end it). Runs on the **host**, never bundled into the container image — the container has
no Python at all, deliberately, since the monitor's only job is to talk to each actor's
`CommandServer` over plain HTTP, and `network_mode: host` already makes every command port reachable
at `localhost` without any in-container Python needed to bridge that.

Build inside the container (only needed again after editing source without rebuilding the image,
e.g. while iterating): `docker exec router_cpp bash -c "cd build && cmake --build . -j2"`. Run tests:
`docker exec router_cpp bash -c "cd build && ctest"` (or `docker exec router_cpp ./build/xv6_tests` directly).

**Pitfall — a separate ad-hoc dev container for fast local compile-checks (`router_cpp_build`, e.g.
`docker run -d --name router_cpp_build -v $(pwd):/workspace gcc:13 sleep infinity`, not part of
`docker-compose.yml`) is convenient for iterating on unit tests without waiting on the full
`docker-compose build`, but its binaries must never be copied directly into the deployed `router_cpp`
container.** `gcc:13`'s base image ships a newer `libstdc++` than the `router_cpp` image's `ubuntu:22.04`
base, so a `router_main` built in `router_cpp_build` fails at runtime in `router_cpp` with `libstdc++.so.6:
version 'GLIBCXX_3.4.32' not found` — the two containers are not binary-compatible, only source-
compatible. Anything that needs to actually *run* as part of the stack must be built via `docker
compose build` (which uses the Dockerfile's own `ubuntu:22.04` + `apt`-installed `g++`), not
`docker cp`'d in from `router_cpp_build`. Relatedly: if `router_cpp_build` is bind-mounted straight onto the
host project root (as in the example above) and its own `cmake`/`make` was ever run there, the
resulting host-side `build/` directory (gitignored, but still present on disk) gets picked up by the
Dockerfile's `COPY . .` on the next `docker compose build` — its `CMakeCache.txt` records
`/workspace/build` as the source dir, which doesn't match `/src` inside the image, so `cmake`
refuses to reuse it and the image build fails outright. Run `rm -rf build/` on the host before
`docker compose build` if `router_cpp_build` (or any other bind-mounted dev container) was used earlier
in the same session.

**Pitfall — unqualified `-j` (use every core) can OOM-kill the compiler in a memory-constrained
build host**, and the failure mode is easy to misdiagnose as a source bug rather than a resource
one. `router_main.cpp` is the single heaviest translation unit in this project — it pulls in
`httplib.h` (header-only, large) and the full `RouterConfig`/`RouterSession`/`Dispatcher` object
graph in one file — and under `-j8` on an 8-core/~2.8GB machine (true both for a constrained CI
runner and for `docker build` on a memory-limited dev host — this is not just a container-internal
concern), `cc1plus` compiling that one file concurrently with several others gets killed by the OOM
killer while every *other* target (the shared/router static libs, the three simulators, the test
binary) links and builds fine. The observable symptom is a `make`/`ninja` error report naming only
`router_main.cpp` — `c++: fatal error: Killed signal terminated program cc1plus` — with everything
else reported as built successfully, which looks like a compiler crash specific to that file rather
than what it actually is (memory exhaustion under parallelism). If a build fails this way: re-run
with a smaller `-j` (or `-j1` just for the affected target, e.g. `cmake --build build -j1 --target
router_main`) rather than assuming the source changed underneath it. Don't "fix" it back to
`-j$(nproc)` without confirming the build host has enough memory per core to support it.

**Update from stress-testing work**: on the actual dev host this project runs on (a ~2.8GB
container also running an IDE's Java language servers), even `-j2` reliably OOM-killed the build
— not on `router_main.cpp` itself this time, but on `crypto_host_main.cpp` compiling concurrently
with `router_main` *linking* (4 of 5 attempts failed, each at the identical step). Every stress
run rebuilds the image (any edit to a file inside the build context, e.g. `stress_run.sh`,
invalidates Docker's layer cache and forces a full recompile from scratch), so this isn't a
one-time cost — it's hit on every source change. The Dockerfile now defaults to `-j1` for this
reason: a full build takes longer (~400s vs. ~370s) but has been reliable across repeated runs,
whereas `-j2` failed 80% of the time in this exact environment. If run on a host with more memory
headroom, `-j2` (or higher) is worth trying again.

**Default port assignments**:
- Router upstream listen: 5000 (router_1), 5010 (router_2, client mode)
- Downstream host IMS: 5001
- Crypto host REST: 5002
- Router command API: 8080 (router_1), 8085 (router_2)
- Downstream command API: 8081
- Crypto command API: 8082
- Upstream command API: 8083 (upstream_1, shared component), 8086 (upstream_2, router_cpp-local)
- Monitor: 8090

`--network host` means this container and any other project using the same default ports —
including a live `router_java` container from a sibling project in this repo family — cannot run at the
same time; accepted drop-in-replacement tradeoff, same as the "Coexistence" decision above.

---

## Running

```bash
./start.sh      # docker compose up -d --build; polls localhost:8080/stats until ready
./monitor.sh    # dashboard on http://localhost:8090, on the HOST (Ctrl+C to stop)
# work in the dashboard: Start All -> upload a CSV -> Start -> watch /results
./stop.sh       # docker compose down
```

All four binaries are already running as soon as `start.sh` reports ready — `docker-compose`
launches them directly (see the `Dockerfile`/`docker-compose.yml` above), no separate per-actor
launch step is needed for the common case. The dashboard's per-actor Start/Stop buttons exist for
finer-grained control on top of that default (e.g. after killing one actor via the dashboard's
`kill` command for a deliberate crash test, restart just that one with the dashboard's Start button,
via `docker exec -d`, without tearing down the whole container).

Manual/CLI equivalent of the same workflow (no dashboard) — for each actor, `curl -s
http://localhost:<command_port>/stats` to check liveness; `curl -F 'file=@your.csv'
http://localhost:8083/upload` then `curl http://localhost:8083/start` then `curl
http://localhost:8083/results` to drive a test run end-to-end against `upstream_host` directly.

`run_test.sh <csv_file>` automates the above end-to-end: `./start.sh` (build, launch the container,
poll `/stats` readiness for all four command ports), upload the CSV, retry `/start` past an initial
non-2xx (the upstream's TCP handshake with the router can still be in flight even after `/stats`
itself answers), poll `/results` to completion, print a PAN/RC/auth-code/field-47 report and the
router's 30s stats, then `./stop.sh` via `trap ... EXIT` on any exit path. `./run_test.sh --manual
<csv_file>` skips the start/stop and drives an already-running stack instead — see the "Testing"
section below for the CLI-compatibility note versus router_py's/router_java's `run_test.sh`. The manual/CLI
workflow above and the dashboard both still work for interactive/ad-hoc use.

### Glue-script safety checklist (unchanged from the Java doc)

Any re-runnable script (`start.sh`, `stop.sh`, `monitor.sh`, `run_test.sh`) must fail loud, not fail
silent:

- **Every HTTP readiness/polling check must fail-fast on a bad response** — `curl -s -f`.
- **Never let a single flaky iteration of a polling/retry loop kill the whole script** under `set
  -e` — guard bare command-substitution assignments (`STATUS=$(cmd) || STATUS=""`).
- **Guarantee teardown with `trap ... EXIT`**, not a final line at the bottom of the script.

---

## Stress testing

`upstream_host`'s `/start` route accepts two optional query params (`req.has_param("rate")`/
`req.get_param_value("rate")`): `rate` (target sends/sec) and `duration` (seconds). Omitted,
`/start` behaves exactly as before — one pass through the uploaded CSV at a fixed 20ms pace, for
the functional `run_test.sh` flow. With `duration` given, the send loop instead **cycles** the CSV
rows (wrapping back to index 0) at `1/rate` intervals until the wall-clock duration elapses, so a
3-row functional-test CSV can sustain an arbitrary-length load run. Every `/start` call also resets
per-run state (pending map, results, latency samples) so repeated stress runs against the same
container don't mix data across runs.

`GET /stress_stats` (separate from the existing `/results`, unchanged, still returning the full
per-row list for functional tests) reports aggregate numbers for the current/most recent run —
same shape as router_py's and router_java's equivalent endpoint:
`{sent, received, errors, elapsed_s, achieved_tps, p50_ms, p95_ms, p99_ms, max_ms}`. `errors` is
`sent - received`. Percentiles are nearest-rank over a bounded (200k-sample) latency list,
timestamped from send (`steady_clock::now()` in the send loop) to match (in the receive loop) by
STAN, via a parallel `map<string, steady_clock::time_point>` alongside the existing STAN-keyed
pending map.

`stress_run.sh [--manual] <tps> <duration_s> <csv_file>` is the per-implementation CLI driver:
same `./start.sh`/`./stop.sh`-wrapped scaffolding as `run_test.sh`, but calls
`/start?rate=&duration=` and polls `/stress_stats` instead of `/results`, printing **exactly one
semicolon-delimited line to stdout** (all progress goes to stderr, including `./start.sh`'s own
docker-compose build/up output — see the pitfall note in router_py's doc, which applies here too:
`docker compose up --build`'s progress writes to stdout, not stderr, and would otherwise land
inside the captured result row) so it's directly consumable by the top-level orchestrator,
`routers/stress_test.sh`, which sweeps a list of TPS values across all three implementations in
turn (mutually exclusive on host ports) and appends one CSV row per run to
`routers/csv_results/stress_results.csv`. See `routers/the_routers.md` for the schema.

**Crypto under stress is not this implementation's own local stub.** `stress_run.sh` runs
`ROUTER_CONFIG=router_1_perf.json ./start.sh` (rather than plain `./start.sh`) so `router_main`
loads `config/router_1_perf.json` instead of `router_1.json` — identical except `crypto.port` is
`5099`, pointing the router's `CryptoClient` at the shared, OpenSSL-backed `routers/crypto_host/`
container instead of this stack's own stub. `CRYPTO_CMD` in the script is `8099` (the shared
container's command port) rather than `8082` (this stack's own local `crypto_host`'s command port)
for the same reason — `wait_for_stats` polls the crypto backend actually under test, and that's now
the shared container, which `stress_run.sh` does not start or stop itself (see
`routers/stress_test.sh`/`routers/crypto_host/start.sh`). This stack's own local `crypto_host` stub
still starts as usual (on its usual port 5002/8082) alongside the other three actors — it just sits
unused for the duration of the perf run. See "Crypto validation has moved to a shared container"
above and the `ROUTER_CONFIG` pitfall under "Container" for the mechanism this relies on.

---

## Testing

**Catch2** (`ctest --test-dir build`, or `build/xv6_tests` directly): framing round-trip (all four
`length_field_type` encodings, plus `max_message_bytes` rejection), rolling-window stats counters,
EBCDIC table round-trip (`ebcdic_test.cpp` — `to_ebcdic`/`from_ebcdic` padding/truncation, plus
`ascii_to_ebcdic_bytes`/`ebcdic_to_ascii_bytes`'s byte-for-byte no-padding semantics), ISO 8583
round-trip via `iso_codec::encode`/`decode` (the MTI is 4 ASCII characters on the wire, not a
2-byte binary value — `iso_codec_test.cpp` asserts the literal wire bytes to catch a regression
back to the old, buggy binary-MTI convention; plus a dedicated `Encoding::Ebcdic` suite covering
the MTI, LLVAR length-prefix digits, and field data all translating correctly, cross-checked
against a real pyiso8583/j8583 encode of the same message — see "ISO 8583 codec" above),
`RouterConfig::from_file` parsing (including that unknown JSON keys are tolerated),
`Dispatcher` resilience (bounded-queue backpressure, pending-entry TTL expiry producing a decline,
STAN-collision logging, `purge()` drop counts), and one full-stack integration test wiring
crypto/downstream/router/upstream together in-process (constructing and running each actor's
`run()`/equivalent directly in the test binary, not via subprocess) with CSV-equivalent rows in and
field 39 asserted on the results.

**Manual/CLI end-to-end verification**, exercised for real against the actual running container (not
just in-process Catch2) — `./start.sh`, upload a CSV to `upstream_host`'s `/upload`, `GET /start`,
poll `/results`, assert on field 39, then `./stop.sh` and verify clean teardown (no orphaned
processes, no ports left bound). `run_test.sh` automates this exact sequence — CLI-compatible with
`router_py/run_test.sh` and `router_java/run_test.sh` (same `[--manual] <csv_file>` usage, same results-table
and 30s-stats output), but its spawn/teardown wraps `./start.sh`/`./stop.sh` rather than
launching per-actor processes: unlike router_java, there is no separate long-lived dev container to
`docker exec` individual actor binaries into here — the docker-compose stack's single container
*is* all four actors (see docker-compose.yml's `command`), so "spawn" and "teardown" mean
"start/stop that one container" and `--manual` means "assume it's already up". `wait_for_stats`/CSV
row counting/results polling/report formatting are copied verbatim from router_py's script.

**The dashboard itself**, exercised live in a browser: "Start All" launches all 4 actors and shows
them connected; CSV upload + Start + results through the dashboard's own proxy routes produces
correct response codes; "Stop All" cleanly stops all 4 actors; `Ctrl+C` (or the dashboard's own
Stop-All-then-`/stop` path) frees port 8090.

---

## Known limitations (intentionally out of scope, unchanged from the Java doc)

- No authentication on the upstream or downstream TCP sockets — first TCP connector wins.
- `command_auth_token` defaults to unset (auth disabled) — set it explicitly before exposing any
  command port beyond loopback.
- Crypto traffic between the router and `crypto_host` is plaintext HTTP (no TLS).
- `pans_defined.json` stores master keys in plaintext JSON — a test fixture only.
- **Fixed in this port** (was intentionally-carried-forward in the Java doc): the monitor's
  log-level display bug — see the "Log-level display (fixed...)" note in the Monitor section above.
- **New to this port**: the router now has real `LOG_DEBUG` message-level tracing (received/forwarded
  MTIs, the downstream PING pipe-cleaner skip, dispatcher queue/forward events) — see the
  "DEBUG-level message tracing" note under `Dispatcher` above. The Java doc's `DEBUG`/`FINE` level was
  never backed by any call sites at all; only the router got this treatment here, not the simulators.
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
