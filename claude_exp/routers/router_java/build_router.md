# ISO 8583 Router — Build Specification: Java core in a container + Python monitor on the host

## Purpose

Build a router that routes ISO 8583 payment messages between one or more upstream clients (card
networks/acquirers) and a downstream IMS Connect host (authorization system), with a crypto host
handling EMV cryptographic validation and a web dashboard managing/observing all components. The
router, and the three simulators standing in for real systems (crypto host, downstream host,
upstream host), are **Java**, built and run inside a Docker container. The web dashboard is
**Python**, running on the host, talking to every actor over plain HTTP.

This file is self-contained: everything needed to build this system from scratch — wire formats,
config schemas, message flows, class responsibilities, container setup — is specified below. No
access to any other project or directory is required or assumed.

### Design principles (non-negotiable)

- **No process exits without releasing its sockets.** A malfunctioning actor must never retain a
  lock on a TCP port — all socket close paths run even on error/exception exit.
- **Thread-per-connection, blocking I/O, one lock per shared mutable structure** (pending-request
  map, stats counters) — chosen deliberately over NIO/reactive frameworks so the implementation
  maps 1:1 to a future C++ port (`std::thread` + `std::mutex` + blocking `recv`/`send`). An
  event-loop model would need a full conceptual rewrite in C++; blocking threads do not. This
  applies regardless of which language currently implements the router — see "C++ portability
  notes" at the end of this document for the concrete mapping.
- **The router must not stall on crypto calls.** Each upstream connection accepts the next message
  as soon as the current one is handed to a worker — it does not block waiting for that worker's
  crypto-host round-trip to finish. This rules out a naive "call crypto synchronously in the read
  loop" design; it is why `Dispatcher` exists as a bounded worker pool with a configurable
  worker-thread count rather than spawning a thread per message (thread-per-message does not scale
  at high volume).
- **Bounded resources, not unbounded growth.** The dispatcher queue and the in-flight pending map
  must have a ceiling. When the system is overloaded (slow/dead downstream or crypto host), the
  queue blocks `submit()` rather than growing without limit — this throttles the upstream read
  loop naturally instead of risking OOM during an extended outage. A bounded queue also means an
  operator always has a finite, inspectable backlog to discard via the purge endpoint when
  replaying stale traffic into a freshly-recovered downstream would do more harm than dropping it.
- **Command APIs default to localhost, and mutating routes are gate-able behind a shared secret.**
  `/stop`, `/log_level`, and `/dispatcher/purge` can stop, reconfigure, or drop in-flight traffic
  for an actor — they must not be reachable by default from anything other than the monitor on the
  same host.
- **Daemon threads that are the sole reader of a connection must never die silently.** Any
  exception inside the downstream-receiver or an upstream read thread that is not caught and
  logged will leave the session in a broken state with no diagnostic output. Wrap dispatch calls
  (not just I/O) in a catch-all around the whole dispatch block.

---

## Repository layout

```
project/
├── pom.xml                       # single Maven module, shaded jar
├── Dockerfile                    # Java 25 + Maven + Node/Claude Code CLI
├── start.sh / stop.sh            # container lifecycle (bind-mount + docker exec, no devcontainer.json)
├── dockerstart.sh                # ensures the Docker daemon itself is running
├── terminal.sh                   # interactive shell into the running container
├── run_test.sh                   # end-to-end CLI driver, run on the HOST
├── monitor.sh / monitor_stop.sh   # dashboard lifecycle, run on the HOST
├── config/
│   ├── test_spec.xml             # j8583 ConfigParser XML — per-MTI field lists
│   ├── pans_defined.json         # card + key data for simulators and crypto host
│   ├── f47.json                  # documents the field-47 JSON schema (reference only, not parsed)
│   ├── router_1.json
│   ├── router_1_perf.json         # like router_1.json but crypto block points at the shared
│   │                              # routers/crypto_host/ container; used only by stress_run.sh
│   ├── router_2.json              # second, independent router+partner instance, is_active:
│   │                              # false by default - see "router_2/upstream_2" below
│   ├── upstream_2.json            # router_2's paired load generator (shared upstream_host
│   │                              # binary, router_java-local config) - is_active: false
│   ├── crypto_host.json
│   └── downstream_host.json
│                                  # no upstream_1.json - upstream_host's config now lives in the
│                                  # shared routers/upstream_host/ component
├── test_csv_files/                # mirror of routers/test_csv_files/ (the master) - local
│   └── test.csv                    # convenience only; re-sync via routers/sync_test_csv.sh
├── monitor/                      # Python, runs on the HOST
│   ├── main.py
│   └── static/index.html
├── src/
│   ├── main/java/com/router/
│   │   ├── shared/     Framing, FramingConfig, Charset500, ImsConnect, IsoUtils, Stats,
│   │   │               StopEvent, LogBuffer, LogLevels, CommandServer
│   │   ├── router/     RouterConfig, RouterConfigJson, UpstreamConfig, DownstreamConfig,
│   │   │               DownstreamConfigJson, CryptoConfig, Upstream, UpstreamConn,
│   │   │               DownstreamConnection, CryptoClient, PendingEntry, RoutedMessage,
│   │   │               Dispatcher, RouterSession, RouterMain
│   │   └── simulators/{cryptohost,downstreamhost}/*Main.java   # upstream_host is the shared
│   │                              # routers/upstream_host/ Python component now, not a Java class
│   └── test/java/com/router/   # JUnit 5
└── logs/                          # gitignored; per-actor console logs written at runtime
```

One Maven module, one shaded jar (`target/router_java.jar`). Every actor is a different `Main` class
launched from the same jar: `java -cp target/router_java.jar com.router.router.RouterMain --config
config/router_1.json`, and likewise for the three simulator `Main` classes.

Scope: router + simulators (crypto_host, downstream_host, upstream_host); router_1 is the primary
instance. A second, independent instance (`router_2`/`upstream_2`, partner_b, disabled by default)
now exists too — see "`router_2`/`upstream_2`" below. No `router_1.01`-equivalent (same-partner,
second instance) scenario — deferred, router_py is the only implementation with that one.

---

## `pom.xml`

```xml
<properties>
  <maven.compiler.release>25</maven.compiler.release>
  <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
</properties>
<dependencies>
  <dependency><groupId>net.sf.j8583</groupId><artifactId>j8583</artifactId><version>3.0.1</version></dependency>
  <dependency><groupId>com.fasterxml.jackson.core</groupId><artifactId>jackson-databind</artifactId><version>2.17.1</version></dependency>
  <dependency><groupId>org.junit.jupiter</groupId><artifactId>junit-jupiter</artifactId><version>5.10.2</version><scope>test</scope></dependency>
</dependencies>
```

`maven-shade-plugin` bound to the `package` phase produces `target/router_java.jar` (finalName
`router_java`). No other runtime dependency: HTTP is the JDK's built-in `com.sun.net.httpserver`,
crypto is standard JCE (`javax.crypto`) — neither needs a library.

**j8583 note**: the Maven groupId (`net.sf.j8583`) differs from the library's own Java package
(`com.solab.iso8583`) — both are correct, just don't confuse them when writing imports vs. the POM.

**Monitor (Python, host-side) dependencies**: `flask`, `requests`. No `requirements.txt` file is
required by this spec; install however the target environment prefers.

---

## Shared modules (`com.router.shared`)

### `Framing` — length-prefixed TCP framing

Two static methods, no state. Config (`FramingConfig` record): `headerHex` (may be null/empty),
`lengthFieldType` (`"BIG_ENDIAN"|"LITTLE_ENDIAN"|"ASCII"|"EBCDIC"`), `lengthFieldBytes`,
`maxMessageBytes` (default 65536).

```java
static byte[] readMessage(Socket sock, FramingConfig cfg) throws IOException
    // Reads optional fixed header (hex-decoded), reads the length field, decodes it per
    // lengthFieldType, then reads exactly that many payload bytes. Throws IOException
    // immediately if the decoded length exceeds maxMessageBytes, instead of blocking waiting
    // for bytes that may never arrive — a corrupt or hostile length field must fail fast and
    // drop the connection, not hang its read thread forever.

static void writeMessage(Socket sock, byte[] data, FramingConfig cfg) throws IOException
    // Writes header + encoded length + data in one write() + flush().
```

Internal `recvExact(sock, n)` loops on `InputStream.read()` until `n` bytes are collected; a `-1`
read (remote EOF) throws `IOException("connection closed while reading")`. Java's checked
`IOException` already covers both a remote disconnect and a local socket close racing a blocked
read from another thread (e.g. session teardown) — no separate exception-wrapping step is needed
here, unlike languages that distinguish a raw OS-level error from "connection closed."

ASCII/EBCDIC length-field encoding is zero-padded decimal text of width `lengthFieldBytes` (e.g.
4-byte ASCII length field for a 37-byte payload → `"0037"`). BIG_ENDIAN/LITTLE_ENDIAN encode the
length as raw bytes of the given width.

### `Charset500` — EBCDIC charset handle

Java ships IBM code page 500 (`Cp500`) as a built-in `Charset` — no extra library needed for
EBCDIC encode/decode.

### `ImsConnect` — IMS Connect wire protocol

Dual-socket model: one socket sends requests (to-socket), one receives responses (from-socket).

```java
static final int IRM_HEADER_LEN = 28;
static final byte[] PING_TRANSCODE = toEbcdic("PING0001", 8);

static byte[] toEbcdic(String s, int length)
    // EBCDIC-encode; left-pad with EBCDIC spaces (or right-truncate, keeping the tail) to
    // exactly `length` bytes.

static byte[] buildFrame(int irmF0, byte[] irmId, byte[] clientId, String mti, byte[] data, byte[] transcode)
    // irmF0=0x80 -> resume TPIPE (no data). irmF0=0x00 -> normal request.
    // transcode defaults to EBCDIC("TRAN"+mti, 8) when data is present and transcode is null.

static void writeResponse(Socket sock, byte[] data) throws IOException
    // 4-byte big-endian length + data.

static byte[] readResponse(Socket sock) throws IOException
    // Reads and returns ISO data bytes only (length prefix stripped).

record ImsRequest(int irmF0, byte[] clientId, byte[] transcode, byte[] isoData)
static ImsRequest readRequest(Socket sock) throws IOException
```

Wire format of `buildFrame`'s output:

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

`readRequest` parses `irmF0` from payload byte offset 3, `clientId` from bytes 20–28 (relative to
the 28-byte header start), and everything past byte 28 as `transcode` (first 8 bytes) + `isoData`
(rest) when present.

### `IsoUtils` — j8583 glue code

j8583 requires one `<parse>` XML block per incoming MTI (see `config/test_spec.xml` below), treats
the MTI as `IsoMessage.getType()/setType(int)` rather than a settable field, and computes the
primary/secondary bitmap itself from whichever fields are actually set — there is no bitmap field
to declare.

To keep the rest of the codebase (dispatcher, sessions, simulators) working with a simple,
uniform shape instead of touching j8583 types everywhere, every decoded/encoded message is
represented as `Map<String, String>` with key `"t"` for the MTI (4-digit string, e.g. `"0100"`)
and field numbers as string keys (e.g. `"2"`, `"11"`) — mirroring a plain dict.

```java
private record FieldSpec(IsoType isoType, int length) {}

private static final Map<Integer, FieldSpec> FIELD_SPECS = Map.of(
    2,  FieldSpec(LLVAR, 0),   3,  FieldSpec(ALPHA, 6),   4,  FieldSpec(ALPHA, 12),
    11, FieldSpec(ALPHA, 6),   14, FieldSpec(ALPHA, 4),   24, FieldSpec(ALPHA, 3),
    37, FieldSpec(ALPHA, 12),  38, FieldSpec(ALPHA, 6),   39, FieldSpec(ALPHA, 2),
    41, FieldSpec(ALPHA, 8),   42, FieldSpec(ALPHA, 15),  47, FieldSpec(LLLVAR, 0)
    // fields 52/55 are declared in test_spec.xml for parity but intentionally absent here:
    // nothing in this project ever sets them as top-level ISO fields — all PIN/ICC data
    // travels inside field 47's JSON blob instead.
);

static Map<String, String> toMap(IsoMessage msg)
    // out.put("t", String.format("%04x", msg.getType()))  — !! see pitfall below !!
    // then for every field in FIELD_SPECS that msg.hasField(field): out.put(str(field), value)

static IsoMessage fromMap(MessageFactory<IsoMessage> factory, Map<String, String> data)
    // int type = Integer.parseInt(data.get("t"), 16);   — !! matching pitfall !!
    // IsoMessage msg = factory.newMessage(type);
    // for every field in FIELD_SPECS present in `data`: msg.setValue(field, value, isoType, length)

static byte[] build0800(MessageFactory<IsoMessage> factory)   // {"t":"0800","24":"100"}
static byte[] build0810(String f24, MessageFactory<IsoMessage> factory)   // {"t":"0810","24":f24}
static String f47Encode(Map<String, Object> data)             // JSON serialize
static Map<String, Object> f47Decode(String value)             // JSON parse; empty map on error/blank
static boolean isKnownField(String key)                         // true if key parses as an int in FIELD_SPECS
```

**Critical pitfall — MTI is hex, not decimal.** j8583's `IsoMessage.getType()`/`newMessage(type)`
represent the MTI as an integer whose **hex digits** equal the MTI's literal decimal digits: MTI
`"0100"` is stored/expected as the integer `0x0100` (== 256 decimal), not `100`. `toMap` must
format with `String.format("%04x", msg.getType())`, and `fromMap` must parse with
`Integer.parseInt(data.get("t"), 16)`. Using plain decimal formatting/parsing here silently
produces the wrong MTI on every message (e.g. type `256` decimal reads back as `"0100"` only
because `%04x` of `256` happens to be `0100` — the bug shows up the moment a genuinely different
MTI like `0810`, whose hex and decimal digit strings diverge, is round-tripped incorrectly if this
convention is not followed consistently both ways).

Loading the spec: `ConfigParser.createFromUrl(new File(specPath).toURI().toURL())` — a j8583
`MessageFactory<IsoMessage>`, one per config file, loaded once at session-connect time (not
per-message). `loadFactory(specPath)` and its overload `loadFactory(specPath, characterEncoding)`
both also call `setUseBinaryBitmap(true)` (see the pitfall below); the two-arg overload additionally
calls `setCharacterEncoding(characterEncoding)` **and** `setForceStringEncoding(true)` when
`characterEncoding` is non-null.

**Second pitfall — EBCDIC needs both `setCharacterEncoding` AND `setForceStringEncoding`.**
`setCharacterEncoding("Cp500")` alone translates the MTI and ALPHA/LLVAR/LLLVAR field *data* to
EBCDIC, but leaves the LLVAR/LLLVAR **length-prefix digits** in plain ASCII — confirmed by
disassembling `IsoValue.writeLengthHeader`'s bytecode: the length-prefix write only consults the
value's own character encoding on the branch gated by `MessageFactory.isForceStringEncoding()`;
without it, the length prefix goes through a different code path that ignores the configured
encoding entirely. A real EBCDIC-speaking partner needs the length prefix in EBCDIC too, not just
the field data, so both settings must be enabled together — `IsoUtils.loadFactory`'s two-arg
overload does this automatically. Verified with a standalone round-trip test (encode via a Cp500
factory, decode with `routers/upstream_host/test_spec_ebcdic.json`'s pyiso8583 spec, byte-for-byte
match) before wiring it into the live router flow — this is exactly the kind of j8583 surprise the
`setUseBinaryBitmap` pitfall above already was.

### `Stats` — thread-safe rolling counters

Windows `[30, 60, 180, 1800]` seconds, backed by a per-instance lock and two `ArrayDeque<Long>` of
send/recv timestamps (millis), trimmed to the max window on every record.

```java
Stats(Integer yellowThresholdSeconds)          // null = no yellow-status threshold
void setConnection(String name, boolean connected)     // e.g. "upstream", "downstream", "router"
void setGauge(String name, Object value)                // arbitrary named point-in-time value
void recordSent()
void recordRecv()
Map<String, Object> snapshot()
    // keys: sent_total, recv_total, sent_30s/recv_30s ... sent_1800s/recv_1800s,
    // seconds_since_last_recv (Double|null, rounded to 0.1), last_recv_datetime (HH:mm:ss|null),
    // yellow_threshold_seconds (only if set), connections (map, only if non-empty),
    // gauges (map, only if non-empty)
```

### `StopEvent` — write-once stop flag

Backed by a single-count `CountDownLatch` (the flag is only ever set, never cleared): `set()`,
`isSet()`, `waitFor(timeout, unit) -> boolean`, `await()` (blocks forever until set).

### `LogBuffer` — in-memory log ring buffer

A `java.util.logging.Handler` subclass that appends formatted log lines to a bounded deque
(default max 2000). Installed on the root logger by `CommandServer`'s constructor.

### `LogLevels` — Python-style level name mapping

Maps `DEBUG→FINE`, `WARNING`/`WARN`→`WARNING`, `ERROR`→`SEVERE`, anything else→`INFO`, and back
(`toPythonName`), so `/log_level` and its request/response bodies use the same vocabulary
(`DEBUG`/`INFO`/`WARNING`/`ERROR`) an operator or the monitor would expect.

### `CommandServer` — shared HTTP command/stats API

Every actor gets one, backed by `com.sun.net.httpserver.HttpServer` (built into the JDK — zero
extra dependency).

```java
CommandServer(int port, Stats stats, StopEvent stopEvent, String bindHost, String authToken)
    // Adds a LogBuffer handler to the root logger as a side effect of construction — configure
    // logging levels/handlers before this, or messages logged earlier than this line won't
    // retroactively appear in /logs.
void register(String path, List<String> methods, boolean protectedRoute, HttpHandler handler)
    // The handler writes its own response; this wrapper only enforces method + optional auth
    // (checks header X-Router-Auth == authToken; no-op when authToken is null) before calling it.
void start()
    // server.setExecutor(cached thread pool of daemon threads); server.start().
    // NOTE: setting a daemon executor is NOT sufficient for the JVM to exit on its own —
    // HttpServer's own internal dispatcher thread is not a daemon thread regardless. Every
    // actor's main() must call System.exit() explicitly once its stop event is honored (see
    // "Actor process lifecycle" below) rather than relying on daemon threads alone.
```

Built-in routes:

| Route | Method | Protected | Behavior |
|---|---|---|---|
| `/stats` | GET | no | `stats.snapshot()` as JSON |
| `/stop` | GET, POST | yes | sets `stopEvent`, returns `{"status":"stopping"}` |
| `/log_level` | GET | no | returns `{"level": <current>}` |
| `/log_level` | POST | yes | body `{"level": "..."}`, sets root logger level, returns `{"level": <upper>}` |
| `/logs` | GET | no | JSON array of buffered log lines; `?format=text` → newline-joined plain text |

Default `bindHost` is `127.0.0.1`, not `0.0.0.0` — every actor's command port is loopback-only
unless a config explicitly overrides `command_bind_host`. Auth token defaults to `null` (disabled)
— set `command_auth_token` before exposing any command port beyond loopback.

### Real crypto math has moved to a shared container — `crypto_host` here is a stub

`com.router.shared.CryptoUtils` used to live here and do the real EMV cryptographic work (MasterCard
M/Chip UDK/session-key derivation, Retail MAC ARQC verification, ARPC Method 1, ISO 9564-1
Format-0 PIN block verification, MasterCard CVV2 verification, HMAC-SHA1 AAV verification — all
pure JCE code, no I/O). That class (and its test, `CryptoUtilsTest`) has been **deleted**. The real
math now lives only in the shared `routers/crypto_host/` container (C++/OpenSSL, not Java) —
see `routers/divide_and_conquer.md` for the full rationale; in short, crypto_host was the
performance bottleneck across all three sibling implementations (python/java/c++), and testing
each one against its own crypto simulator was muddying the cross-implementation comparison this
project exists to produce.

`CryptoHostMain.validate()` in this repo is now a stub: it only checks whether the PAN is present
in the loaded `pans_defined.json` map, stamping `response_code = "00"` if present, `"14"` if not —
no PIN/ARQC/CVV2/AAV math happens in router_java at all anymore. It exists purely so router_java can still
be built and functionally tested standalone (`run_test.sh`) without the shared container running.
Performance runs instead point the router at the real shared `crypto_host` via
`config/router_1_perf.json` — see "Stress testing" below.

### `f47.json` (field-47 JSON schema — reference documentation, not machine-parsed)

Field 47 carries everything `crypto_host` needs in one JSON blob, round-tripped via
`IsoUtils.f47Encode`/`f47Decode`:

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

Any subset of `f52`/`cvv2`/`aav`/`f55` may be present in the request — this is the full schema a
real crypto validator (the shared `routers/crypto_host/` container, or a real Fortanix DSM tenant)
runs checks against, for whichever keys exist. This repo's own stub `CryptoHostMain.validate()`
ignores all of them and only ever stamps `response_code` (`"00"`/`"14"`) based on PAN presence — it
never sets `55`/`82`/`N7`, never touches `f55.arpc`.

---

## `config/test_spec.xml` — j8583 ConfigParser XML

One `<parse type="MTI">` block per incoming message type, each listing only the fields that MTI
carries (no header/bitmap declaration — j8583 computes the bitmap itself):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<j8583-config>
    <parse type="0100">
        <field num="2" type="LLVAR" />
        <field num="3" type="ALPHA" length="6" />
        <field num="4" type="ALPHA" length="12" />
        <field num="11" type="ALPHA" length="6" />
        <field num="14" type="ALPHA" length="4" />
        <field num="24" type="ALPHA" length="3" />
        <field num="37" type="ALPHA" length="12" />
        <field num="41" type="ALPHA" length="8" />
        <field num="42" type="ALPHA" length="15" />
        <field num="47" type="LLLVAR" />
        <field num="52" type="BINARY" length="8" />
        <field num="55" type="LLLBIN" />
    </parse>
    <parse type="0110">
        <!-- same as 0100, plus: -->
        <field num="38" type="ALPHA" length="6" />
        <field num="39" type="ALPHA" length="2" />
    </parse>
    <parse type="0120"><!-- 3,4,11,24,37,41,42 --></parse>
    <parse type="0130"><!-- 3,4,11,24,37,39,41,42 --></parse>
    <parse type="0420"><!-- 3,4,11,24,37,41,42 --></parse>
    <parse type="0430"><!-- 3,4,11,24,37,39,41,42 --></parse>
    <parse type="0800"><field num="24" type="ALPHA" length="3" /></parse>
    <parse type="0810"><field num="24" type="ALPHA" length="3" /></parse>
</j8583-config>
```

Fields 52 (PIN block) and 55 (ICC data) are declared on 0100/0110 for schema completeness even
though nothing in this project sets them on the wire — all PIN/ICC data travels inside field 47's
JSON blob instead (see `f47.json` above).

---

## `config/pans_defined.json`

Keys are PAN strings. `downstream_host` and this repo's own stub `crypto_host` both only use key
presence (to decide PAN-known vs. unknown) — the per-PAN `pin`/`pan_seq`/`imk_ac`/`cvk`/`pek`/
`aav_key` fields below are read by a real EMV validator (the shared `routers/crypto_host/`
container), not by anything in this repo:

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

Populate with 4+ distinct PANs across at least two card ranges (e.g. two `4...` Visa-shaped, two
`5...` Mastercard-shaped) for test coverage. Every `imk_ac`/`cvk`/`pek`/`aav_key` is a fresh random
16-byte hex string — there is no cross-project master key to reuse, and none of the values need to
resemble real card-scheme keys since this is a closed simulation.

**Historical pitfall — no longer reachable in router_java's own `crypto_host`.** Back when
`CryptoHostMain.validate()` ran real crypto math, it read each field straight off the parsed
`Map<String, Map<String, String>>` via `panInfo.get("pek")` etc. — a missing key yielded `null`,
which then flowed into `CryptoUtils` helpers (`hex(null)` and friends) and threw
`NullPointerException`, turning into an HTTP 500 that could trip `CryptoClient`'s circuit breaker
for every PAN, not just the one with the bad record. That code path is gone: the stub `validate()`
only calls `pans.containsKey(pan)`, so a malformed `pek`/`cvk`/`imk_ac`/`aav_key` record no longer
causes any failure in this implementation at all — it simply isn't read. The equivalent
"one bad key record breaker-wide" risk now lives only in the shared `routers/crypto_host/`
container, which reads the full record; this doc doesn't cover its internals.

---

## Router (`com.router.router`)

### Config schema (`config/router_1.json`)

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
  "iso_spec": "test_spec.xml",
  "worker_threads": 8,
  "reestablish_seconds": 10,
  "yellow_threshold_seconds": 40
}
```

Deserialized via Jackson with `PropertyNamingStrategies.SNAKE_CASE` (so `command_port` in JSON
maps to a `commandPort` Java field with no manual key-mapping code) into a raw `RouterConfigJson`
record; `@JsonIgnoreProperties(ignoreUnknown = true)` on this record (and every nested config
record) means unrecognized JSON keys — `type`, `is_active`, or any future monitor-only metadata
field — are silently ignored rather than causing a startup failure. This is the direct fix for a
documented pitfall from an earlier, dict-based implementation of this same design: there, every
JSON key not consumed by explicit parsing had to be added by hand to an "exclusion set" before
being passed as constructor kwargs, and forgetting one crashed the process at startup with an
unhelpful "unexpected keyword argument" error. Here that whole bug class is structurally
impossible.

`RouterConfig.fromFile(path)` wraps this: loads `RouterConfigJson`, resolves `iso_spec` to an
absolute path relative to the config file's own directory, and converts the raw `downstream` block
(`DownstreamConfigJson`, plain strings) into `DownstreamConfig` with `irm_id`/`client_id`
EBCDIC-encoded to exactly 8 bytes via `ImsConnect.toEbcdic`.

`upstreamIsoEncoding` (JSON key `upstream_iso_encoding`, e.g. `"Cp500"`) is an optional sibling
field — when present, `RouterSession.connect()` loads a **second** `MessageFactory` via
`IsoUtils.loadFactory(cfg.isoSpec(), cfg.upstreamIsoEncoding())` (same XML spec file, different
runtime character encoding) and uses it only for the upstream-facing leg (decode-from-upstream,
encode-to-upstream in `RouterSession.forward0810` and `Dispatcher.handleResponse`/
`pendingReaper`); the downstream-facing leg keeps using the plain ASCII `factory`. `null` (the
default, e.g. `router_1.json`) means both legs use the same ASCII factory, unchanged from before
this field existed. See "`router_2`/`upstream_2`" below for the full rationale and the j8583
encoding gotcha this uncovered.

Defaults (applied in `RouterConfigJson`'s compact constructor when the JSON key is absent/zero):
`log_level=INFO`, `worker_threads=8`, `reestablish_seconds=10`, `yellow_threshold_seconds=40`,
`queue_maxsize=1000`, `pending_ttl_seconds=30`, `crypto_breaker_threshold=5`,
`crypto_breaker_cooldown_seconds=30`, `reconnect_jitter_seconds=2.0`,
`command_bind_host="127.0.0.1"`. `partner_id` and `command_auth_token` default to `null`.
`upstream.mode` defaults to `"server"`, `upstream.host` to `"localhost"`, `upstream.retry_seconds`
to `5`.

`is_active` controls whether the monitor's "Start All" launches this actor (see Monitor section).
JSON booleans are lowercase (`true`/`false`) — a hand-edited config using any other casing/spelling
fails to parse.

### `router_2`/`upstream_2` — a second partner, disabled by default

`config/router_2.json` + `config/upstream_2.json`: a second, independent router+load-generator
pair, `is_active: false` in both, mirroring router_py's existing `router/router_2` +
`simulators/upstream_2` pattern. `router_2` connects **out** to `upstream_2`
(`"upstream": {"mode": "client", "host": "localhost", "port": 5010, ...}`) rather than listening
for it — the reverse of `router_1`'s `mode: "server"` — while `upstream_2.json` (the shared
`upstream_host` binary's own config shape, not a `RouterConfigJson`) sets `"mode": "server"`. It
reuses the **same already-running** `downstream_host`/`crypto_host` as `router_1`, distinguished
only by `downstream.client_id` (`CLIENT03` vs `router_1`'s `CLIENT01`) — no second
downstream/crypto instance is launched for it.

`router_2.json` sets `"upstream_iso_encoding": "Cp500"` — its upstream leg speaks EBCDIC (see the
`IsoUtils.loadFactory` pitfall above), while `iso_spec` stays `test_spec.xml` for the downstream
leg (still ASCII, since it still talks to the shared `downstream_host`, which doesn't understand
EBCDIC). A literal single-encoding swap on `router_2` — no leg split — would break its downstream
leg outright: `downstream_host` would fail to decode an EBCDIC frame and every request would time
out rather than complete. `config/upstream_2.json`'s own `iso_spec` points at the shared
`routers/upstream_host/test_spec_ebcdic.json` (a pure endpoint, no leg split needed there).

**Actor discovery gap fixed to support this**: `monitor/main.py`'s `_consider()` only accepted
`type` values present in `MAIN_CLASS_BY_TYPE` (`router`/`downstream`/`crypto`) — `"upstream"` has
no Java main class (it's the shared Python binary, launched via `subprocess.Popen`, not `docker
exec`), so `config/upstream_2.json` would otherwise be silently dropped from discovery. The gate
now also accepts `actor_type == "upstream"` explicitly.

### `Upstream` — server/client connection acquisition

Two nested classes, both returning `UpstreamConn(Socket, SocketAddress, ReentrantLock writeLock)`:

```java
final class UpstreamServer {
    UpstreamServer(UpstreamConfig cfg) throws IOException
        // ServerSocket, setReuseAddress(true), bind(port), setSoTimeout(1000).
        // Created once outside the session loop — survives reconnects.
    UpstreamConn accept(BooleanSupplier shouldStop)
        // Loops on accept() with a 1s socket timeout, rechecking shouldStop each iteration;
        // returns null on stop or a hard IOException.
    void close()
}

final class UpstreamClient {
    UpstreamClient(UpstreamConfig cfg)
    UpstreamConn connect(BooleanSupplier shouldStop)
        // Connects to cfg.host:cfg.port (5s connect timeout); on failure, waits
        // cfg.retrySeconds() (polling shouldStop every 200ms so it can be interrupted
        // promptly) before retrying. Returns null if shouldStop becomes true while waiting.
}
```

`shouldStop` is a combined "stop OR reconnect" predicate — the caller (`RouterSession`) passes
`() -> stopEvent.isSet() || reconnectEvent.isSet()` so a single accept/connect loop can be woken by
either condition without either API needing to know about both. (In a language with a native
condition-variable primitive that wakes immediately when signaled, prefer that over polling; the
200ms poll here is a deliberate simplicity/latency tradeoff acceptable given this project's
multi-second retry/reestablish intervals — see "C++ portability notes" for the edge-triggered
alternative.)

### `DownstreamConnection` — dual-socket IMS session

```java
static DownstreamConnection connect(DownstreamConfig cfg) throws IOException
    // 1. Connect toSock to cfg.host:cfg.port (5s timeout), then setSoTimeout(0) — switch to
    //    blocking. The 5s value passed to the connect call is connect-only; explicitly
    //    clearing the timeout after a successful connect is required, or every subsequent
    //    blocking read on this socket would incorrectly time out after 5 seconds of idle.
    // 2. Same for fromSock.
    // 3. Send resume TPIPE on fromSock: buildFrame(0x80, irmId, clientId, null, [], null).
    // 4. Send pipe-cleaner ping on toSock: data = "1234 clean the pipes" in EBCDIC (Cp500);
    //    buildFrame(0x00, irmId, clientId, null, data, PING_TRANSCODE).

void send(byte[] frame) throws IOException     // acquires an internal ReentrantLock, writes to toSock
byte[] recv() throws IOException                // blocking read from fromSock via ImsConnect.readResponse
void close()                                     // closes both sockets, swallowing IOException
```

### `CryptoClient` — HTTP client to crypto_host with a circuit breaker

Its wire interface deliberately mimics Fortanix DSM's "invoke a plugin execution" API
(`POST /sys/v1/plugins/{plugin_id}`, bearer-token auth, base64 `PluginOutput` response) so that a
later swap to a real Fortanix DSM tenant is a config/URL change, not a rewrite of this class.

```java
CryptoClient(CryptoConfig cfg, int breakerThreshold, int breakerCooldownSeconds)
    // baseUrl = "http://" + cfg.host() + ":" + cfg.port() + "/sys/v1/plugins/" + cfg.pluginId()
    // One shared java.net.http.HttpClient (thread-safe) across all dispatcher worker threads.
    // Breaker state: a failure counter + an "open until" timestamp, guarded by one lock.

String validate(String endpoint, String pan, String f47)
    // If now < openUntil: skip the HTTP call entirely, return "" immediately — same fallback
    //   as any other error path — so worker threads stay free to drain the queue with
    //   declines instead of each independently stalling a full 5s timeout against a crypto
    //   host that is known to be down.
    // Otherwise: POST {baseUrl} with JSON {"operation": endpoint, "f2": pan, "f47": f47} and
    //   header Authorization: Bearer {cfg.bearerToken()}, 5s timeout.
    //   - HTTP status >= 400 (401 unauthorized, 404 unknown plugin_id) or any exception: log,
    //     increment failure counter (reset on success); once the counter reaches
    //     breakerThreshold, set openUntil = now + breakerCooldownSeconds and return "" (half-open
    //     retry once the cooldown elapses, since the next call after openUntil passes will
    //     attempt the HTTP call again).
    //   - success: the 2XX body is a JSON string literal — the `PluginOutput` envelope every
    //     Fortanix DSM plugin-invocation response uses (base64, "format": "byte"), not a JSON
    //     object wrapping it. Parse the body as a JSON string, base64-decode it, then JSON-parse
    //     the decoded bytes to reach the inner {"f47": ...} object; reset failure counter to 0;
    //     return that inner object's "f47" field (empty string if null). A failure at either
    //     decode layer is treated the same as an HTTP error above.
    // endpoint is "validate_0100" or "validate_0110" — carried as the "operation" field in the
    // request body rather than as two distinct URL paths, since a real Fortanix plugin is invoked
    // at one fixed URL regardless of which logical operation it performs; the plugin's own input
    // schema is where operation-specific dispatch belongs.
```

Callers only overwrite their working `f47` when the return value is non-empty — every failure path
(breaker open, HTTP error, bad auth, unknown plugin_id, malformed response) leaves the original
`f47` unchanged, so a down or misconfigured crypto host degrades to "PIN/ARQC/CVV2/AAV checks
silently skipped," never to a crash.

**Two stacked SSL bugs trip the breaker on every SSL run — found and fixed 2026-08-15.** Both
needed fixing together; fixing only the first (which looked sufficient in isolation) still left the
breaker tripping under the real router's concurrency.

*Bug 1 — JVM TLS cold start.* Building the custom `SSLContext`/`HttpClient`
(`SslUtils.buildClientContext` + `HttpClient.newBuilder().sslContext(...).build()`) and making the
*first* HTTPS request through it are both genuinely slow the first time any JVM process does it —
measured in isolation, on an otherwise idle host: ~0.5-1.4s just to build the client, then
~1-2s for a first request. This isn't crypto_host being slow - a genuinely simultaneous 8-way burst
against crypto_host itself (Python `threading.Barrier`, not just backgrounded processes) completed
in ~60-80ms per request, 5 rounds straight, no issue. It's pure JVM-side class-loading/JIT cold
start, paid once per `HttpClient` instance the first time it's used.

*Bug 2 — concurrent construction/first-use of independent `HttpClient` instances is itself unsafe.*
Isolated outside the router entirely: 8 threads, each given its own fully independent
`SSLContext`/`HttpClient` (no shared state at all) but all built and first-used *concurrently*,
reliably fails 1-2 of the 8 with `javax.net.ssl.SSLException: (internal_error) Received fatal alert:
internal_error` - reproduced whether the `SSLContext` was shared or not, so the trigger is
concurrent `HttpClient` construction/first-use itself, not certificate/trust-manager sharing. The
same 8 clients built *sequentially* (a plain for-loop) and then used concurrently afterward: 0
failures across every run. This rules out crypto_host/OpenSSL entirely (also confirmed separately:
a real simultaneous burst against crypto_host from Python succeeds every time) and points at a
genuine `java.net.http.HttpClient` concurrency bug specific to standing up several brand-new mTLS
connections at once.

Originally, `CryptoClient` held one `HttpClient` **shared** across all 8 dispatcher worker threads
(`worker_threads: 8`) - exactly the trigger for Bug 2, on every single router_java SSL run, since
`Dispatcher.start()` launches all worker/response-worker threads together and they immediately
start calling `crypto.validate()` concurrently. The circuit breaker (`breakerThreshold` defaults to
5) sees a burst of near-simultaneous failures (Bug 1's slow first request and/or Bug 2's outright
alert) and opens before the JVM/connections ever stabilize - silently skipping crypto validation
(`f47` left unenriched) for whichever transactions land in that opening window, every run.

**Fix (both bugs together):**
- `CryptoClient` now holds a `ThreadLocal<HttpClient>` (`clientTL`) instead of one shared client -
  each dispatcher worker/response-worker thread gets its own fully independent `HttpClient`/
  `SSLContext`, eliminating Bug 2 (concurrent *use* of already-built, independent clients is fine;
  only concurrent *construction/first-use* was ever unsafe). The constructor still eagerly builds
  and discards one `SSLContext` purely to fail fast on a bad cert/key/ca path at startup, same as
  before.
- `CryptoClient.warmup()` - a synchronous dummy `validate("validate_0100", "0", "", "warmup")` -
  is now called once from *inside* `Dispatcher.workerLoop`/`responseWorkerLoop`, as the first thing
  each thread does, so it warms and first-uses *that thread's own* `ThreadLocal` client (calling it
  from `RouterSession.connect()`, on a different thread, would only warm a client nobody else uses -
  tried this first, looked right, didn't fix anything, because it warmed the wrong thread).
- `CryptoClient` also gets a `Semaphore(1)` (`warmupGate`) guarding only the `warmup()` call - this
  is Bug 2's actual fix: `ThreadLocal` alone still lets every worker thread race to build+first-use
  its (now independent) client concurrently at startup, reproducing Bug 2 again (confirmed live -
  switching to `ThreadLocal` alone still failed every worker's `warmup()` call itself, all at once,
  with the exact same alert). The gate serializes that one-time moment per thread without touching
  anything else. **First attempt, reverted**: making `Dispatcher.start()` launch worker/response-
  worker threads one at a time - starting a thread, then blocking on a per-thread `CountDownLatch`
  until its warm-up finished, before starting the next - also fixed the alert, but delayed
  `Dispatcher.start()` (and therefore the router's upstream-accept readiness, which starts *after*
  it in `RouterSession.runUntilDisconnect()`) by roughly `(workerThreads + responseWorkerThreads) *
  ~1-1.5s` - long enough to blow past `stress_run.sh`'s own "wait for upstream_1 to connect"
  timeout, confirmed live (`Timed out waiting for upstream_1 to connect to the router`). The
  semaphore gets the same serialization without blocking the launcher: each worker thread still
  self-serializes its own warm-up moment against the others, but `Dispatcher.start()` returns
  immediately as before, so router readiness is unaffected - only real crypto traffic on each
  worker is delayed a few seconds behind that worker's own warm-up, which is the intended tradeoff.
- The one-time warm-up call also gets its own longer timeout (`WARMUP_TIMEOUT`, 20s vs. the
  standard `REQUEST_TIMEOUT`, 5s) - `validate(String,String,String,String)` (public, still the
  method test doubles like `DispatcherResilienceTest`'s `NoOpCrypto` override) now delegates to a
  private `validate(..., Duration timeout)` overload; `warmup()` calls that private overload
  directly with `WARMUP_TIMEOUT` instead of the public one. **Gotcha this caused**: `warmup()`
  bypassing the public, overridable method meant `NoOpCrypto` (whose `validate()` override returns
  `""` with zero network I/O) no longer intercepted the warm-up call - `warmup()` was silently
  attempting a real connection to `NoOpCrypto`'s fake `localhost:1` in every Dispatcher test, only
  caught by an unrelated-looking timing failure (`DispatcherResilienceTest.stanCollisionIsLogged`,
  a 300ms sleep no longer enough). Fixed by also overriding `warmup()` itself in `NoOpCrypto` as a
  true no-op, rather than trying to route the longer timeout back through the overridable method.

**Status: Bug 2 (data corruption) is fixed and verified - zero `internal_error` alerts across every
run since the `ThreadLocal` fix, including all the runs below.** A *different*, not fully understood
problem remains open, discovered only once testing with longer, more realistic run durations:
`HTTP connect timed out` warnings that don't stay confined to the one-time warm-up window - a 30s
duration / 60s warmup run kept hitting them roughly every 5s **throughout the entire run**, with
surviving transactions showing p50 latency around 30s. This is not a cold-start signature anymore.
`crypto_host` itself was idle between runs (0.02% CPU, 0 open connections) each time it was
checked, which doesn't confirm the server side, but doesn't clearly indict it either. Two
untested hypotheses, not distinguished: (a) a per-thread `HttpClient`'s connection pool getting
into a bad state after one slow/failed connect and never recovering for that thread's remaining
requests (nothing currently rebuilds a `ThreadLocal` client once created), or (b) genuine
contention on this specific WSL2 dev host after several hours of continuous testing in one session,
impossible to cleanly separate from a real bug without a fresh host state. **Deliberately left
open** (user's call, 2026-08-16) rather than continuing to redesign against an increasingly
uncertain signal - next session should retest on a quiet/fresh host before assuming this is a real
remaining bug in the fix above.

**Response envelope — unverified assumption, flag before pointing at a real Fortanix tenant.**
Fortanix's published schema for this endpoint defines the 2XX response body as `PluginOutput`:
`{"type": "string", "format": "byte"}` — a bare base64-encoded byte string, not an object wrapping
one — but Fortanix's docs show no worked example of the literal response body. This spec reads that
schema the standard OpenAPI way: the entire HTTP body is a JSON string literal (e.g.
`"eyJmNDci...="`), so `crypto_host` produces exactly that and `CryptoClient` decodes exactly that.
If a real Fortanix DSM tenant is later substituted in and its actual wire body differs (e.g.
wrapped in `{"result": "..."}`), only this one decode step in `CryptoClient` needs to change — the
rest of the router (STAN rewrite, dispatcher, pending map) is unaffected either way.

### `Dispatcher` — worker pool + STAN rewrite + pending map

Routes `0100` upstream → crypto → downstream. Routes `0110`/`0130`/`0430` downstream → upstream
(via STAN lookup).

```java
Dispatcher(RouterConfig cfg, DownstreamConnection downstream, CryptoClient crypto,
           MessageFactory<IsoMessage> factory, Stats stats, StopEvent reconnectEvent)
    // queue = new ArrayBlockingQueue<>(cfg.queueMaxsize())

void start()
    // Spawns cfg.workerThreads() daemon worker threads running workerLoop(), plus one daemon
    // pending-reaper thread.

void submit(RoutedMessage msg) throws InterruptedException     // blocking enqueue (backpressure)
void handleResponse(Map<String, String> resp)                   // called from the ds-receiver thread
Map<String, Integer> purge()                                     // operator drain; returns dropped counts
void drainAndStop()                                               // poison-pill sentinels + join (session teardown)
```

**STAN rewriting**: the dispatcher owns its own 6-digit counter (`(counter + 1) % 1_000_000`,
zero-padded). On a `0100`, it saves `PendingEntry(upConn, upWriteLock, upstreamStan,
createdAtNanos)` keyed by the new `routerStan`, and sends the message downstream with `routerStan`
in field 11. On a matching response, it looks up `routerStan`, restores `upstreamStan` into field
11, and forwards upstream. If a `routerStan` slot the counter is about to reuse is still occupied
(the counter wrapped while the old entry was still outstanding), log at severe/error before
overwriting it.

**`workerLoop()`** (one per worker thread): `queue.take()`, break on the poison-pill sentinel, else
call `process(msg)`; an `IOException` from `process` (a failed downstream write) sets the
`reconnectEvent`; any other exception is logged and swallowed (the worker keeps running — one bad
message must not kill the pool).

**`process(msg)`** (runs in a worker thread):
1. Extract `mti`, `pan` (field 2), `upstreamStan` (field 11) from `msg.req()`.
2. Generate the next `routerStan`.
3. If `mti == "0100"`: call `crypto.validate("validate_0100", pan, req.get("47"))`; if non-empty,
   overwrite field 47 in the forwarded copy.
4. Set field 11 to `routerStan` in the forwarded copy; encode via `IsoUtils.fromMap` +
   `writeData()`.
5. Insert the `PendingEntry` into the pending map keyed by `routerStan` (log+overwrite on
   collision, as above); update the `pending_count` gauge.
6. Build the IMS frame (`ImsConnect.buildFrame(0x00, irmId, clientId, fwd.get("t"), encoded,
   null)`) and `downstream.send(frame)`; on success, `stats.recordSent()`.

**`handleResponse(resp)`** (runs on the ds-receiver thread):
1. If `mti == "0810"`: return immediately — handled separately by the session, not the dispatcher.
2. If `mti` not in `{0110, 0130, 0430}`: log a warning and return.
3. Pop the pending entry by `routerStan` (field 11 of `resp`); if none found, log and return.
4. Restore field 11 to the entry's `upstreamStan`.
5. If `mti == "0110"`: call `crypto.validate("validate_0110", pan, resp.get("47"))`; overwrite
   field 47 if non-empty.
6. Encode, acquire `entry.upWriteLock()`, write to `entry.upConn()`, release the lock, then
   `stats.recordSent()` — wrapped in try/catch: this write races session teardown closing the
   upstream socket from a different thread, and that race must not propagate as an uncaught
   exception on the ds-receiver thread.

**Pending reaper** (daemon thread started in `start()`): wakes every second (via
`stopEvent.waitFor(1, SECONDS)` returning false), scans the pending map for entries older than
`cfg.pendingTtlSeconds()` (measured via `System.nanoTime()`, a monotonic clock — not wall-clock
time), removes each, and for each expired entry writes a local decline (`t=0110, 11=<upstreamStan>,
39=91`) directly to the upstream connection, then logs a warning. Updates the `pending_count` gauge
after any removals.

**Queue depth / pending count gauges**: after every `submit()`/dequeue and every pending
insert/pop, call `stats.setGauge("queue_depth", queue.size())` and
`stats.setGauge("pending_count", pending.size())`.

**Traffic counters**: `stats.recordSent()`/`recordRecv()` must be called at every actual wire I/O
point — in the dispatcher (`process()` after the downstream write, `handleResponse()` after the
upstream write, the pending reaper after its decline write) *and* in `RouterSession`
(`handleUpstream()` after decoding a frame, `downstreamReceiver()` after decoding a frame,
`forward0800()`/`forward0810()` after their writes). Skipping any of these is easy to miss because
nothing fails loudly — `/stats` still returns 200 and the totals just silently stay at 0, which
means `seconds_since_last_recv` stays `null` forever and the monitor shows that actor as
permanently yellow regardless of real traffic.

**DEBUG-level tracing** (`logger.fine(...)`, i.e. `LogLevels`' `DEBUG → Level.FINE` mapping):
`submit()` logs the queued MTI and queue depth; `process()` logs the downstream forward with both
STANs; `handleResponse()` logs the upstream forward with both STANs. These were backported from
the C++ port (router_cpp), which had accreted a richer set of trace points than this port during its
own development — see the identical note under `RouterSession` below, and router_py's
`build_router.md` "Common pitfalls" section (`DEBUG-level tracing granularity was inconsistent
across ports`) for the full rationale and the cross-implementation verification method.

### `RouterSession` — one live connection session

Owns the ds-receiver thread and the up-server/up-client thread.

```java
static RouterSession connect(RouterConfig cfg, Stats stats, StopEvent stopEvent) throws IOException
    // 1. DownstreamConnection.connect(cfg.downstream()) — IOException propagates to caller,
    //    which treats it as "retry after reestablishSeconds + jitter".
    // 2. stats.setConnection("downstream", true).
    // 3. Load the MessageFactory from cfg.isoSpec(); build a CryptoClient; create a fresh
    //    reconnectEvent (StopEvent) and a Dispatcher wired to it.

void runUntilDisconnect(Upstream.UpstreamServer srvSock) throws InterruptedException
    // 1. dispatcher.start()
    // 2. Start ds-receiver daemon thread -> downstreamReceiver()
    // 3. Start up-server/up-client daemon thread depending on cfg.upstream().mode()
    // 4. Block until stopEvent OR reconnectEvent becomes set (poll stopEvent.waitFor(1s) in a
    //    loop, also checking reconnectEvent.isSet() each iteration)
    // 5. teardown(upThread)
    // 6. dsThread.join(5000)
```

**`handleUpstream(conn, addr, writeLock)`** (the upstream read loop):
- `stats.setConnection("upstream", true)`; stash `(conn, writeLock)` as the session's live
  upstream reference under its own lock (read by `forward0810`).
- Loop: `Upstream.readUpstream(conn, cfg.upstream())` → decode via `IsoUtils.toMap` →
  `stats.recordRecv()`.
  - MTI `0100`/`0120`/`0420` → `dispatcher.submit(new RoutedMessage(req, conn, writeLock, addr))`.
  - MTI `0800` → `forward0800(req)`.
  - anything else → log a warning.
  - An `IOException` from the read (covers both a genuine remote disconnect and a local close
    racing this blocked read during teardown) → log, set `reconnectEvent`, break the loop.
  - The dispatch (`submit`/`forward0800`/warning-log) is wrapped in its own `try { ... } catch
    (InterruptedException) { ... return; } catch (Exception e) { log SEVERE; }` — same "daemon
    threads must never die silently" principle as `downstreamReceiver`'s catch-all (see the design
    principle above). This was caught by a doc-vs-code audit after the fact: the design principle
    already promised coverage of "an upstream read thread", but the code only wrapped the
    downstream side until this fix, so a bad upstream message could have silently killed this
    thread while the router kept processing downstream traffic.
- On exit (finally): `stats.setConnection("upstream", false)`, clear the stashed upstream
  reference if it still points at this connection.

**`forward0800(req)`**: re-encode, wrap in an IMS frame (`buildFrame(0x00, irmId, clientId,
"0800", encoded, null)`), `downstream.send(frame)`, `stats.recordSent()` — the send is wrapped in
try/catch since teardown running on another thread can close the downstream connection out from
under this write, called from the up-server/up-client read thread itself.

**`forward0810(resp)`**: reads the stashed upstream reference under its lock; if none (no live
upstream), log a warning and return. Otherwise re-encode, acquire the upstream write lock, write,
release, `stats.recordSent()` — again wrapped in try/catch, since this runs on the ds-receiver
thread and races the same teardown.

**`downstreamReceiver()`**:
- Loop: `downstream.recv()`.
  - An `IOException` (remote disconnect or local close racing teardown) → log,
    `stats.setConnection("downstream", false)`, set `reconnectEvent`, break.
  - Skip any frame whose first 4 bytes exactly equal the EBCDIC bytes of `"PING"` — **both** the
    marker on the wire and the comparison value must be EBCDIC-encoded; comparing against a plain
    ASCII `"PING"` byte sequence will never match and the ping-response frame falls through to a
    decode error instead of being silently skipped.
  - Otherwise decode via `IsoUtils.toMap`, `stats.recordRecv()`, then:
    ```
    try {
        if (resp.get("t").equals("0810")) forward0810(resp);
        else dispatcher.handleResponse(resp);
    } catch (Exception e) {
        log.severe("unexpected error dispatching downstream message mti=" + resp.get("t"));
    }
    ```
    This catch-all is required. Any non-I/O exception from encode/decode or internal logic inside
    `forward0810`/`handleResponse`, if left unguarded, propagates up and silently kills this daemon
    thread — the session then keeps accepting upstream messages forever while never again
    processing a downstream response, with no log line indicating why.

**`teardown(upThread)`**:
1. `dispatcher.drainAndStop()`.
2. Clear and close the stashed upstream connection, if any (swallow `IOException` on close).
3. `downstream.close()` — this unblocks any thread blocked in `recv()` on the from-socket (the
   ds-receiver's blocked read returns via an `IOException` from the now-closed socket, which the
   ds-receiver's own catch treats as the normal "downstream lost" path, setting `reconnectEvent`
   and exiting — this is the *expected* teardown path, not an error condition to alarm on).
4. `upThread.join(5000)`.

**DEBUG-level tracing** (`logger.fine(...)`): `handleUpstream()` logs the received MTI;
`forward0800()` and `forward0810()` each log a one-line confirmation on success; `downstreamReceiver()`
logs the PING-skip and the received MTI. Backported from router_cpp for parity — see the note under
`Dispatcher` above.

### `RouterMain` — entry point, reconnect loop

```java
static void run(RouterConfig cfg, StopEvent stopEvent, Stats statsIn) throws Exception {
    Stats stats = statsIn != null ? statsIn : new Stats(cfg.yellowThresholdSeconds());
    // Set the root logger level from cfg.logLevel() BEFORE constructing CommandServer — mirrors
    // the general principle that any log-handler-installing construction must happen after the
    // desired level is set, or early messages are silently dropped at the default level.
    Logger.getLogger("").setLevel(LogLevels.parse(cfg.logLevel()));
    CommandServer cmd = new CommandServer(cfg.commandPort(), stats, stopEvent,
                                            cfg.commandBindHost(), cfg.commandAuthToken());

    AtomicReference<Dispatcher> activeDispatcher = new AtomicReference<>();
    cmd.register("/dispatcher/purge", List.of("POST"), /*protected=*/true, exchange -> {
        Dispatcher d = activeDispatcher.get();
        if (d == null) { sendJson(exchange, 503, Map.of("error", "no active session")); return; }
        sendJson(exchange, 200, d.purge());
    });
    cmd.start();

    UpstreamServer srvSock = "server".equals(cfg.upstream().mode())
        ? new UpstreamServer(cfg.upstream()) : null;
    try {
        while (!stopEvent.isSet()) {
            RouterSession session;
            try {
                session = RouterSession.connect(cfg, stats, stopEvent);
            } catch (IOException e) {
                log.warning("failed to connect downstream: " + e.getMessage());
                waitReestablish(stopEvent, cfg);   // reestablishSeconds + random jitter
                continue;
            }
            activeDispatcher.set(session.dispatcher);
            session.runUntilDisconnect(srvSock);
            activeDispatcher.set(null);
            if (!stopEvent.isSet()) waitReestablish(stopEvent, cfg);
        }
    } finally {
        if (srvSock != null) srvSock.close();
    }
}
```

`waitReestablish` waits `reestablishSeconds + uniform(0, reconnectJitterSeconds)` — the jitter
specifically exists to avoid multiple routers sharing a downstream/crypto host from reconnecting in
lockstep after a shared outage.

### Actor process lifecycle (applies to `RouterMain` and all three simulator mains)

`main(args)` parses `--config <path>`, loads the config, calls the actor's `run()`/`runForever()`,
and — critically — **calls `System.exit(0)` explicitly once that call returns**, then `System.exit(1)`
on any uncaught exception. This is required because `HttpServer`'s internal request-dispatcher
thread is not a daemon thread regardless of what executor is configured on it (confirmed by direct
testing: the JVM process stayed alive after `/stop` with only that one thread left running) —
unlike a runtime where every live thread is genuinely a daemon and the process exits on its own
once the stop event is honored, this JVM needs the explicit exit call. Note that the reusable
`run()`/business-logic method itself must stay exit-free (no `System.exit` inside it) — only the
outermost `main()` calls it, because a full-stack in-process integration test needs to call the
same `run()` method directly without killing the test JVM.

---

## Simulators (`com.router.simulators.*`)

All three follow the same shape: load `config.json`, build a `Stats` + `CommandServer`, register
any custom routes, start, and (for the two that aren't a bare HTTP service) run an accept/connect
loop until the stop event fires. Config loading in each is a plain `Map<String, Object>` read via
Jackson (no dedicated config record — unlike the router, these configs are small and used mostly
as-is) with `iso_spec`/`pans_defined`/`input_dir` paths resolved relative to the config file's own
directory.

### `crypto_host` (`CryptoHostMain`)

Stateless HTTP validation service — no TCP actor loop, just one extra HTTP route served from a
**second** `HttpServer` bound to `cfg.port` (separate from the `CommandServer`'s port). Its wire
interface deliberately mimics Fortanix DSM's "invoke a plugin execution" API
(`POST /sys/v1/plugins/{plugin_id}`, bearer-token auth, base64 `PluginOutput` response) so that a
later swap to a real Fortanix DSM tenant is a config/URL change, not a `CryptoClient` rewrite — see
the "Response envelope" note under `CryptoClient` above for the one part of that contract this spec
had to assume rather than confirm from Fortanix's docs.

**Config** (`config/crypto_host.json`):
```json
{
  "name": "crypto_host", "type": "crypto", "is_active": true,
  "port": 5002, "command_port": 8082,
  "pans_defined": "pans_defined.json", "iso_spec": "test_spec.xml",
  "yellow_threshold_seconds": 60,
  "plugin_id": "a53c0b4e-2f7e-4c1e-9c58-1e6f2b6d7a10",
  "bearer_token": "dev-fortanix-bearer-token"
}
```

`plugin_id` and `bearer_token` must match the same two values configured under `router_1.json`'s
`crypto` block — there is no shared-secret store in this project; both sides read the same literal
string from their own config file, the same way `router_1.json` and `downstream_host.json` already
duplicate `irm_id`/`client_id` between them. `config/router_1_perf.json` is a separate `router_1`
variant used only by `stress_run.sh`: same shape, but its `crypto` block instead points at
`localhost:5099` with the `plugin_id`/`bearer_token` the shared `routers/crypto_host/` container's
own config uses, since that pair is what the perf run must match, not this repo's `crypto_host.json`.

**Route** (on the port-5002 `HttpServer`, POST only): `/sys/v1/plugins/{plugin_id}`.
1. Trailing path segment must equal the configured `plugin_id` → else `404`.
2. `Authorization` header must equal `"Bearer " + bearer_token` → else `401` with body
   `{"error": "unauthorized"}`.
3. Request body: `{"operation": "validate_0100"|"validate_0110", "f2": pan, "f47": f47JsonString}`
   — `operation` selects which of the two logical checks below to run; everything past this point
   is unchanged from the pre-Fortanix interface.
4. Response: run `validate(pan, f47Str)` (stub logic below) to get the updated `f47`, encode
   `{"f47": updatedF47}` as a JSON string, base64-encode that string, and write the base64 text as
   the literal JSON response body (a quoted string, not an object) — this is the `PluginOutput`
   envelope; see the same caveat noted under `CryptoClient`.

**`validate(pan, f47Str)` logic** — a stub; identical regardless of which `operation` value
triggered it, and unaware of the HTTP envelope around it. Real PIN/ARQC/CVV2/AAV verification and
ARPC computation used to happen here (via the now-deleted `CryptoUtils`); that logic now lives only
in the shared `routers/crypto_host/` container (see the "Real crypto math has moved..." note
above). This repo's own `validate()` does just this:
1. Decode the f47 JSON string.
2. PAN in `pans_defined` → `response_code = "00"`; else → `response_code = "14"`.
3. JSON-encode and return — every other f47 field (`f52`, `cvv2`, `aav`, `f55`, ...) passes through
   untouched; `f55.arpc` is never set.

The router always calls crypto regardless of whether f47/f55 is present on a given message — an
empty f47 simply gets a `response_code` stamped onto it either way.

### `downstream_host` (now the shared `../downstream_host/main.py`)

**Moved**: `DownstreamHostMain.java` is gone — `downstream_host` is now the shared
`routers/downstream_host/` Python component (see `../downstream_host/build_router.md`), launched
as a host subprocess like `upstream_host`. `config/downstream_host.json` /
`downstream_host_perf.json` still live here (this implementation's own config, pointing at the
shared `iso_spec`/`pans_defined` it needs — the `iso_spec` field now points at
`../../upstream_host/test_spec.json`, the pyiso8583 JSON format, not `test_spec.xml`, since the
shared component doesn't speak j8583's XML spec format).

Simulates an IMS Connect authorization host.

**Architecture**: single listen socket; each accepted connection is dispatched by reading its
first IMS frame in a **fresh thread** (not the acceptor thread — the acceptor must be free to
accept both the to- and from-socket of a session before either read can block):
- `irmF0 == 0x80` → this is the **from-conn**: register a `BlockingQueue<byte[]>` under the
  connection's `clientId` (as a String, keyed for lookup), then loop `queue.poll(1s)` →
  `ImsConnect.writeResponse(conn, item)` until the stop event fires or the write fails.
- `irmF0 == 0x00` → this is the **to-conn**: loop `ImsConnect.readRequest(conn)` →
  `routeFrame(clientIdKey, transcode, isoData)` until the read fails (remote close).

**`routeFrame`**:
- Transcode equals `PING_TRANSCODE` → wait (poll, up to 2s) for the from-conn queue to exist for
  this `clientId`, then enqueue `EBCDIC("PING") + EBCDIC("PIPES cleaned")`. **Both halves must be
  EBCDIC**, including the literal `"PING"` marker — it has to match the router's skip-check
  byte-for-byte; an ASCII `"PING"` here would never be recognized by the router as a ping.
- MTI `0800` → build an `0810` echoing field 24, enqueue to the from-conn.
- MTI `0120` → build `0130` with field 39 = `"00"`.
- MTI `0420` → build `0430` with field 39 = `"00"`.
- MTI `0100` → `process0100(req)`.
- else → log a warning, drop.

**`process0100(req)`**:
- PAN not in `pans_defined` → `rc = "01"`.
- Else if the request's decoded f47's `response_code` (default `"00"`) is not `"00"` (i.e. crypto
  already declined it upstream) → `rc = "01"`.
- Else → `rc = "00"`, and generate the next sequential 6-digit auth code for field 38.
- **Every response must echo f47 back**: take the request's decoded f47 map, set
  `message_type="0110"` and `response_code=rc`, re-encode it into the response's field 47 — this
  is required even though nothing in `downstream_host` itself reads f47 back out, because a full
  EMV validator's (the shared `routers/crypto_host/` container's) ARPC computation on
  `validate_0110` needs the original `f55` cryptogram/ATC, and the only place that data can reach
  that later call is by being round-tripped through this response. Skipping this means ARPC
  silently never gets computed. (This repo's own stub `crypto_host` doesn't compute an ARPC at
  all, but `downstream_host`'s echo behavior is unconditional — the same either way.)

**Wait-for-from-conn polling**: before writing any response, the to-conn handler waits up to 2
seconds for the from-conn's queue to exist. The from-conn's resume-TPIPE can genuinely still be in
flight when the to-conn's first frame (the pipe-cleaner ping) arrives — polling avoids dropping
frames on that startup race rather than requiring the two connections to be strictly ordered.

### `upstream_host` — now the shared `routers/upstream_host/` component

`UpstreamHostMain.java` was deleted — `upstream_host` was promoted out of all three
implementations into a standalone Python component shared by router_py/router_java/router_cpp
(`routers/upstream_host/`, host-side process, not containerized). See `../divide_and_conquer.md`
(part 2) for why, and `../upstream_host/build_router.md` for the full spec (endpoints, config
schema, framing, CSV format, send/receive/keepalive loop internals — all a straight line-by-line
port of what used to be documented here, unchanged in behavior).

**Real wire-compat bug found migrating to it, worth keeping in mind for any future j8583 config
work**: j8583's `MessageFactory` defaults to a text/ASCII-hex bitmap, but the shared component's
pyiso8583 spec (`test_spec.json`, `"data_enc": "b"`) encodes the primary/secondary bitmap as raw
binary bytes. This was invisible before the migration because this router had only ever been
tested against its own same-language `UpstreamHostMain`, which used the same j8583 factory on both
ends (internally consistent, but not matching Python/C++). Fixed with one
`factory.setUseBinaryBitmap(true)` call in `IsoUtils.loadFactory()` — see that method's comment.

**Integration points that remain locally relevant:**
- **Launch mechanism**: `stress_run.sh`/`run_test.sh` launch it as a bare host subprocess
  (`python3 ../upstream_host/main.py --config ../upstream_host/config.json &`), replacing the old
  `docker exec -d router_java java -cp target/router_java.jar com.router.simulators.upstreamhost.UpstreamHostMain ...`.
  Teardown is unchanged in spirit — `POST :8083/stop` — since the shared component exposes the same
  `CommandServer` `/stop` route and reliably exits on it regardless of how it was launched.
- **Monitor integration**: `monitor/main.py`'s `discover_actors()` walks `router_java/`'s own tree
  (plus `config/*.json`), which can never find the shared component's config — it has an explicit
  synthesized entry for it instead. `launch_actor()`/`actor_commands()` branch on
  `actor["type"] == "upstream"` to use a host `subprocess.Popen` instead of `docker exec -d`.
- **`RouterFullStackTest.java`** (the JUnit full-stack test, direct analog of router_py's
  `test_router.py`) used to instantiate `UpstreamHostMain` in-process; it now launches the shared
  `main.py` as a real subprocess via `ProcessBuilder` instead. Since this test runs inside the
  `router_java` dev container (`docker exec router_java mvn test`), which only bind-mounts `router_java/`
  itself, `start.sh` adds a second bind mount (`routers/upstream_host` → `/upstream_host` in the
  container) so the test can reach it at a fixed path; the `router_java` image's Dockerfile also
  gained `python3-pip` + `pip install pyiso8583/flask/requests` for this one test's sake (nothing
  else inside the container needs Python).

---

## Monitor (`monitor/main.py`, Python, runs on the **host**)

The monitor is deliberately **not** part of the Java build — it is a thin, language-agnostic
dashboard that talks to every actor's `CommandServer` purely over HTTP (`/stats`, `/stop`,
`/log_level`, `/logs`, plus upstream's `/start`/`/results`/`/upload`). It has no idea, and no
reason to care, whether the process behind a command port is a JVM or anything else — the only
contract that matters is the HTTP routes above, specified exactly (paths, methods, JSON shapes) in
the `CommandServer` and per-simulator sections above. **Any future rewrite of an individual actor
into a different language stays compatible with this monitor for free, provided that HTTP contract
is preserved exactly** — this is the one guarantee that must never be broken by a future change to
any actor.

Runs on the host via `monitor.sh`/`monitor_stop.sh` (pidfile-based lifecycle; deliberately
**not** `pgrep -f "monitor/main.py"` to find the process — a pattern like that can match unrelated
processes and kill or report the wrong one). Flask app, default port 8090.

**Actor discovery** (`discover_actors()`, cached once per monitor lifetime — restart the monitor to
pick up config changes): scan every `*.json` file directly under `config/` (this project keeps all
actor configs flat in one directory, one file per actor, rather than nested one-per-actor-folder);
load each, keep it only if it has a `name` and a `type` present in the actor-type table below;
default `is_active` to `true` if the key is absent. Since `upstream_host` is the shared
`routers/upstream_host/` component now, its config lives outside `config/` entirely — the walk can
never find it, so `discover_actors()` adds one explicit synthesized entry for it (reading
`routers/upstream_host/config.json` directly) after the walk.

```
MAIN_CLASS_BY_TYPE = {
    "router":     "com.router.router.RouterMain",
    "downstream": "com.router.simulators.downstreamhost.DownstreamHostMain",
    "crypto":     "com.router.simulators.cryptohost.CryptoHostMain",
}
STARTUP_ORDER = {"crypto": 0, "downstream": 1, "router": 2, "upstream": 3}
```

**`launch_actor(actor)`**: for `router`/`downstream`/`crypto`, `docker exec -d <container> bash -c
"mkdir -p logs && java -cp target/router_java.jar <MainClass> --config <relative-config-path> >
logs/<name>.console.log 2>&1"`. The `bash -c` wrapper (rather than invoking `java` bare) exists
specifically to capture stdout/stderr to a per-actor log file — `docker exec -d`'s own client
process detaches and exits the instant the command starts, so without redirecting to a file inside
the container, JVM startup banners and any uncaught stack trace would go nowhere retrievable. The
log file is truncated on every (re)launch (`>`, not `>>`) so a live `tail -F` always reflects the
current run. For `upstream`, a plain host `subprocess.Popen([sys.executable,
"routers/upstream_host/main.py", "--config", "routers/upstream_host/config.json"])` instead — a
real Popen handle exists for this one actor type, unlike the `docker exec -d` ones, so
`actor_kill_command()` can show a plain `kill <pid>` for it rather than the `jps`-based script the
other types need.

**`is_running(name)`**: there is no OS process handle to poll — `docker exec -d`'s client exits
immediately once the detached command starts inside the container, so "the subprocess is still
running" is not an available signal. Liveness is instead defined as "the actor's own `/stats`
endpoint answers HTTP 200" — arguably more honest for a dev tool regardless of the transport, since
a process that's alive but wedged wouldn't help an operator either.

**`wait_for_ready(actor, timeout=10)`**: polls `/stats` until it answers 200, **and** — for routers,
until `connections.downstream == true`; for upstreams, until `connections.router == true`; every
other actor type is ready as soon as `/stats` answers. Skipping the connection check means a
`/start` call issued immediately after "Start All" can 503 with "not connected to router" even
though `/stats` itself already answers 200 — the HTTP server coming up and the actor's own
TCP-level connection to its peer coming up are two different milestones.

**Monitor API routes**:

| Route | Purpose |
|---|---|
| `GET /` | serve `static/index.html` |
| `GET /api/actors` | ordered list: name/type/command_port/running/is_active |
| `GET /api/routers_by_partner` | dict `partner_id → [{name, command_port}]` |
| `GET /api/status` | parallel `/stats` health check; green/yellow/red per actor |
| `GET /api/starting` | `{"starting": bool}` — true while a background "start all" is in flight |
| `GET /api/csv_files` | CSVs under `test_csv_files/` plus each upstream's own `input_dir` |
| `GET /api/commands` | `{"shell": "docker exec -it <container> bash"}` |
| `GET /api/actor/<name>/commands` | `{"kill": <script>, "tail": <command>}` — see below |
| `POST /api/actor/<name>/launch` | start if not already running |
| `POST /api/actor/<name>/stop` | proxy to the actor's `/stop`, then poll liveness down to confirm |
| `GET /api/actor/<name>/stats` | proxy `/stats` |
| `GET /api/actor/<name>/start` | proxy `/start` (upstream only) |
| `GET /api/actor/<name>/results` | proxy `/results` (upstream only) |
| `GET\|POST /api/actor/<name>/log_level` | proxy log level |
| `GET /api/actor/<name>/logs` | proxy `/logs`; `?format=text` for plain text |
| `POST /api/actor/<name>/upload` | proxy multipart CSV upload |
| `POST /api/actor/<name>/upload_path` | upload by project-relative path `{"path": "..."}` |
| `POST /api/actor/<name>/dispatcher/purge` | router only; proxies the protected `/dispatcher/purge` |
| `POST /api/start_all` | launch all active actors in `STARTUP_ORDER`, waiting up to 10s each |
| `POST /api/stop_all` | stop all running actors in reverse order |
| `POST /stop` | stop the monitor itself (best-effort `/stop` to every running actor first, then exit) |

**Status logic** (per actor, for `/api/status`): fetch `/stats`; non-200 or unreachable → red; no
`yellow_threshold_seconds` in the response → green; `seconds_since_last_recv` is `null` or exceeds
the threshold → yellow; otherwise green.

**Shutdown safety net**: on `POST /stop`, the monitor spawns a background thread that best-effort
POSTs `/stop` to every currently-running actor, then calls `os._exit(0)`. There is no process
handle to fall back on if an actor ignores `/stop` (unlike a design where the monitor holds a real
subprocess handle per actor and can forcibly kill it) — the container itself (`./stop.sh`) is the
hard backstop if an actor's HTTP `/stop` doesn't work.

**Container console visibility** (`/api/actor/<name>/commands`): rather than embedding a real
interactive terminal in the browser (rejected — the monitor binds `0.0.0.0:8090`, LAN-reachable,
and shipping an unauthenticated shell into the container over HTTP was judged not worth it for a
dev tool), the dashboard hands the operator two copy-pasteable commands per actor:
- **`kill`**: a small multi-line script, not a single one-liner (so an operator can read it before
  running it) — `PATTERN="<main class> --config <relative config path>"`, look up the PID via
  `docker exec <container> jps -lm | grep -F "$PATTERN" | cut -d" " -f1` (only `jps` itself needs
  `docker exec`; the grep/cut run in the operator's own shell — this is what avoids the
  nested-quoting a single `bash -c '...'` one-liner would need), then `docker exec <container> kill
  -9 "$PID"`, with an explicit "no matching process" message and non-zero exit if nothing matched.
  Matching on the **full class+config string**, not just the class name, is what keeps this safe
  when multiple instances would otherwise share a bare class name (e.g. two router instances in a
  future multi-router scenario) — matching on class name alone could target the wrong instance.
- **`tail`**: `docker exec <container> tail -F logs/<name>.console.log`.

### `monitor/static/index.html`

Single-page vanilla JS, no build step, no framework.

**Layout**: header (title + Start All / Stop All + a "starting…" spinner while `/api/starting` is
true) → router-partner groups (aggregate stats + a grid of compact per-router cards) → simulator
cards (crypto/downstream/upstream) → a test-runner panel (upstream selector, CSV picker,
Upload/Start buttons, a results table).

**Per-actor card**: status dot, per-connection dots, 30s/60s and total sent/recv counters,
last-recv time, a log-level `<select>`, Logs/Commands/Start/Stop buttons. Router cards additionally
show `queue_depth`/`pending_count` gauges and a confirmation-gated Purge Queue button.

**Polling**: `/api/status` and `/api/starting` every 2 seconds.

**Results table columns**: PAN, RC (highlighted green when `"00"`), Auth code (field 38), Field 47
(truncated).

**Log viewer modal**: fetches `/logs`, auto-refreshes every 2s, has an export-to-file button.

**Known open bug, not fixed in this spec's baseline** (carry forward, do not silently "fix" as
part of an unrelated change without calling it out): the log-level `<select>` always re-renders as
`INFO` on every 2-second poll tick regardless of the actor's actual current level, because
`renderCard()` rebuilds each card's entire HTML — including the dropdown — from scratch every tick
and always hardcodes `<option value="INFO" selected>`. The `change` handler does correctly POST
`/log_level`, so the actor's real level does change; only the displayed dropdown value is wrong,
snapping back within ~2 seconds and making the control look broken. A correct fix needs both:
reading back and reflecting the actor's real current level when rendering, and not clobbering the
control while it currently has focus or a pending unsent change.

---

## Message flow (0100 authorization)

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

The `f47: enriched` / `f47: +arpc` annotations above describe what a full EMV validator (the shared
`routers/crypto_host/` container, or a real Fortanix DSM tenant) does with the field. Against this
repo's own stub `crypto_host`, the wire exchange is identical but the reply only ever updates
`response_code` — no enrichment, no `f55.arpc` — see "Real crypto math has moved to a shared
container" above.

**STAN rewrite**: the router replaces field 11 with its own sequential counter before forwarding
to `downstream_host`; on the response, it restores the original upstream STAN before sending back.

**Keepalive (0800/0810)**: `upstream_host` sends `0800` immediately on connect and every
`ping_0800_seconds` thereafter. The router forwards it to `downstream_host` (as an IMS frame),
which responds `0810`; the router forwards that `0810` straight back to the upstream. This path
bypasses the `Dispatcher` entirely — handled directly in `RouterSession` via
`forward0800`/`forward0810`, since keepalives carry no crypto or STAN-rewrite work.

## Message flow (0120 advice / 0420 reversal)

```
0120 Advice   (decision already taken upstream — F38/F39 pre-filled, no crypto call)
  upstream ──0120──→ router ──0120──→ downstream_host ──0130 (F39=00)──→ router ──0130──→ upstream

0420 Reversal (command to revert an earlier transaction, no crypto call)
  upstream ──0420──→ router ──0420──→ downstream_host ──0430 (F39=00)──→ router ──0430──→ upstream
```

Both ride the same `Dispatcher` path as `0100` (STAN rewrite, pending-map lookup) but **skip the
crypto call** — `Dispatcher.process()` only calls `crypto.validate` when `mti == "0100"`.
`downstream_host` always replies approved (`F39=00`) to these; there is no decline path for advice
or reversal in this simulation.

---

## Container

`Dockerfile`: `mcr.microsoft.com/devcontainers/base:ubuntu` + `openjdk-25-jdk` + `maven` +
`nodejs`/`npm` (+ `npm install -g @anthropic-ai/claude-code`, matching this repo family's existing
container convention so Claude Code itself can also run from inside the container — omit this line
if that convention doesn't apply in the target environment). `WORKDIR /workspace`.

`start.sh`: ensures the Docker daemon is running (see `dockerstart.sh` below), `docker build
--network host` the image, remove any pre-existing `router_java` container, then `docker run -d --name
router_java --network host -v <project>:/workspace -w /workspace router_java tail -f /dev/null` — the
container just idles; all actual work happens via `docker exec`. `--network host` means the
container shares the host's ports directly, so this variant and any other variant of the same
project using the same default ports (5000-5002, 8080-8083, 8090) cannot run at the same time.

`stop.sh`: `docker stop router_java && docker rm router_java`.

`dockerstart.sh`: separate from `start.sh` so it can be re-run standalone (e.g. after a VM restart)
without triggering a rebuild. Checks `docker info`; if the daemon isn't up, tries `sudo service
docker start`, and falls back to a direct `sudo dockerd` in the background if that doesn't work
within ~10s (some restricted-capability sandboxes fail `service docker start` even though `dockerd`
itself starts fine when launched directly). Starting the daemon needs root — being in the `docker`
group only lets the *client* talk to an already-running daemon — so this will prompt for a sudo
password when run interactively and simply fails fast in a non-interactive session with no prompt
available.

`terminal.sh`: `docker exec -it router_java bash` — interactive shell into the running container.

Build inside the container: `docker exec router_java mvn -q -DskipTests package` → produces
`target/router_java.jar`. Run tests: `docker exec router_java mvn test`.

**Default port assignments** (single-instance-per-type, this spec's scope):
- Router upstream listen: 5000 (router_1), 5010 (router_2, client mode)
- Downstream host IMS: 5001
- Crypto host REST: 5002
- Router command API: 8080 (router_1), 8085 (router_2)
- Downstream command API: 8081
- Crypto command API: 8082
- Upstream command API: 8083 (upstream_1, shared component), 8086 (upstream_2, router_java-local)
- Monitor: 8090

---

## Running

```bash
./start.sh                          # build + start the container (idle, ready for docker exec)
docker exec router_java mvn -q -DskipTests package
./monitor.sh                        # dashboard on http://localhost:8090, on the HOST
# work in the dashboard: Start All -> upload a CSV -> Start -> watch /results
./monitor_stop.sh
./stop.sh
```

Individual actors, each as `docker exec -d router_java java -cp target/router_java.jar <MainClass>
--config config/<name>.json`, using the `MainClass` names from the `MAIN_CLASS_BY_TYPE` table
above.

`run_test.sh <csv_file>` — an end-to-end CLI driver (not JUnit), run on the **host**:
1. Builds the jar (`mvn -q -DskipTests package`) unless run with `--manual`.
2. Launches all four actors via `docker exec -d`, as above.
3. Polls each actor's `/stats` with `curl -s -o /dev/null -f` (fail-fast on non-2xx — see the
   glue-script safety checklist below) up to 30 times, 1s apart.
4. Uploads the CSV to the upstream's `/upload`.
5. Retries `GET /start` up to 15 times, 1s apart, tolerating an initial 503 while the upstream is
   still completing its TCP handshake with the router (a race not covered by the `/stats`
   readiness checks, since the HTTP server and the TCP client connection come up on different
   schedules).
6. Polls `/results` (guarding the `curl | parse` pipeline's exit code so a transient miss doesn't
   propagate through `set -e` — see below) until every row has a response or 30 seconds elapse.
7. Prints a PAN/RC/auth-code/field-47 report and the router's 30-second stats.
8. On any exit path (`trap cleanup EXIT`), POSTs `/stop` to every actor's command port — **not** a
   host-side PID kill: actors run inside the container's own PID namespace via `docker exec -d`,
   and a host-side kill of the exec client process does not reach (and cannot signal) the `java`
   process it launched inside the container. Every actor already exposes `/stop` via
   `CommandServer`, so going through HTTP is both the correct mechanism here and consistent with
   how `monitor_stop.sh` also stops its target via HTTP rather than a raw signal.

`run_test.sh --manual <csv_file>` skips steps 1–2 and drives already-running actors.

### Glue-script safety checklist

Any script meant to be **re-run** (not just imported/tested as a library) — `run_test.sh`,
`monitor.sh`, `monitor_stop.sh` — must fail loud, not fail silent, since none of these are
exercised by the JUnit suite; they are the only thing that drives the real multi-process system
end-to-end, so a bug in one is invisible until a human actually runs it.

- **Every HTTP readiness/polling check must fail-fast on a bad response, not feed it downstream.**
  Use `curl -s -f` (a non-2xx response makes `curl` itself return non-zero) rather than piping a
  possibly-empty or possibly-HTML response into a parser and hoping the retry loop notices.
- **Never let a single flaky iteration of a polling/retry loop kill the whole script.** Under `set
  -e` (recommended — it catches real mistakes elsewhere), a bare command-substitution assignment
  (`STATUS=$(curl ... | parse)`) that fails on an expected "not ready yet" iteration will terminate
  the entire script right there, with the failing command's stderr already redirected to
  `/dev/null` and no message printed — silently orphaning every actor process already spawned.
  Guard it explicitly (`STATUS=$(cmd) || STATUS=""`, or move it inside an `if`/`while` test, which
  `set -e` does not abort on).
- **Guarantee teardown with `trap ... EXIT`, not a final line at the bottom of the script.** If
  cleanup is just the last few lines, any early exit (`set -e`, an unbound variable under `set -u`,
  a manual Ctrl-C) skips it entirely, orphaning every spawned process and holding their ports open
  for the next run.

---

## Stress testing

The shared `upstream_host`'s `/start` route accepts two optional query params: `rate` (target
sends/sec) and `duration` (seconds). Omitted, `/start` behaves exactly as before — one pass through
the uploaded CSV at a fixed 20ms pace, for the functional `run_test.sh` flow. With `duration` given,
the send loop instead **cycles** the CSV rows (wrapping back to index 0) at `1/rate` intervals
until the wall-clock duration elapses, so a 3-row functional-test CSV can sustain an arbitrary-
length load run. Every `/start` call also resets per-run state (pending map, results, latency
samples) so repeated stress runs against the same JVM don't mix data across runs.

`GET /stress_stats` (separate from the existing `/results`, unchanged, still returning the full
per-row list for functional tests) reports aggregate numbers for the current/most recent run —
same shape as router_py's and router_cpp's equivalent endpoint:
`{sent, received, errors, elapsed_s, achieved_tps, p50_ms, p95_ms, p99_ms, max_ms}`. `errors` is
`sent - received`. Percentiles are nearest-rank over a bounded (200k-sample) latency list,
timestamped from send (in the send loop, `System.nanoTime()`) to match (in the receive loop) by
STAN, via a parallel `Map<String, Long>` alongside the existing STAN-keyed pending map.

`stress_run.sh [--manual] <tps> <duration_s> <csv_file>` is the per-implementation CLI driver:
similar `docker exec`-based spawn/wait-for-stats/upload/teardown scaffolding as `run_test.sh`, but
calls `/start?rate=&duration=` and polls `/stress_stats` instead of `/results`, printing
**exactly one semicolon-delimited line to stdout** (all progress goes to stderr) so it's directly
consumable by the top-level orchestrator, `routers/stress_test.sh`, which sweeps a list of TPS
values across all three implementations in turn (mutually exclusive on host ports) and appends
one CSV row per run to `routers/csv_results/stress_results.csv`. See `routers/the_routers.md` for the schema.

Unlike `run_test.sh`, `stress_run.sh` does **not** spawn its own `crypto_host` — perf runs need the
real, non-stubbed crypto math to be a meaningful bottleneck comparison across implementations, so
they hit the shared `routers/crypto_host/` container (C++/OpenSSL) instead, which is started once,
separately, by `routers/stress_test.sh` (or manually via `routers/crypto_host/start.sh`) and stays
up across every implementation's run. Concretely: `stress_run.sh` launches only `downstream_host`,
`router_1` (using `config/router_1_perf.json`, not `router_1.json`, so its `crypto` block points at
the shared container), and `upstream_1`; it waits on the shared container's command port (`8099`,
not the local stub's `8082`) as one of its readiness checks; and its `cleanup` trap does **not**
POST `/stop` to that port, since the shared container is infrastructure for the whole sweep, not
this run's own actor.

---

## Testing

**JUnit 5** (`mvn test`): framing round-trip (all four `length_field_type` encodings, plus
`max_message_bytes` rejection), rolling-window stats counters, ISO 8583 round-trip via
`IsoUtils.toMap`/`fromMap` (specifically exercising the hex-MTI pitfall above), `RouterConfig.fromFile`
parsing (including that unknown JSON keys are tolerated), `Dispatcher` resilience (bounded-queue
backpressure, pending-entry TTL expiry producing a decline, STAN-collision logging, `purge()` drop
counts), and one full-stack integration test wiring crypto/downstream/router/upstream together
in-process (calling `RouterMain.run()`/the simulators' constructors directly, not via subprocess)
with CSV-equivalent rows in and field 39 asserted on the results — against the stub `crypto_host`,
so this only exercises the PAN-presence check, not real EMV math (that now lives only in the
shared `routers/crypto_host/` container's own C++ test suite).

**`run_test.sh`**, exercised for real against actual `docker exec` subprocesses (not just
in-process JUnit) — CSV in, `/start`, poll `/results`, assert on field 39, verify clean teardown
(no orphaned `java` processes, no ports left bound after the script exits).

**The dashboard itself**, exercised live in a browser (not just read as source): "Start All"
launches all 4 actors and shows them connected; CSV upload + Start + results through the
dashboard's own proxy routes produces correct response codes matching each row's expected value;
"Stop All" cleanly stops all 4 actors with nothing left running; `monitor_stop.sh` frees port 8090
and removes its pidfile.

---

## Known limitations (intentionally out of scope)

- No authentication on the upstream or downstream TCP sockets — first TCP connector wins.
- `command_auth_token` defaults to unset (auth disabled) — set it explicitly before exposing any
  command port beyond loopback.
- Crypto traffic between the router and `crypto_host` is plaintext HTTP (no TLS) — PANs and
  ARQC/ARPC cross the link in the clear even though the Fortanix-shaped `/sys/v1/plugins/{id}`
  route requires a bearer token; that token is a static value duplicated across two config files,
  not a real Fortanix-issued credential, and gates the endpoint without protecting confidentiality.
- `pans_defined.json` stores master keys in plaintext JSON — fine as a test fixture only, never as
  a template for anything resembling production key storage.
- The known monitor log-level display bug (see "Monitor" section above) is intentionally carried
  forward as documented, not silently patched over.

---

## C++ portability notes

The blocking-threads model was chosen specifically because it maps 1:1 to a C++ port — this table
and the notes below identify exactly where that translation lands, regardless of which language
(Python, Java, or a future intermediate) the router happens to be implemented in today. The
simulators and monitor will be replaced by real external systems and do not need a C++ port — only
the router core needs to perform at volume.

| Concept | This spec (Java) | Future C++ |
|---|---|---|
| Per-connection I/O | blocking daemon `Thread`, `Socket`/`ServerSocket` | `std::thread` + blocking `recv`/`send` |
| Dispatcher queue | `ArrayBlockingQueue` | `std::deque` + `std::mutex` + `std::condition_variable` |
| Worker pool | fixed-size pool of daemon `Thread`s | thread pool |
| Pending-STAN map | `ConcurrentHashMap` | `std::unordered_map` + mutex (see sharding note below) |
| Per-upstream write lock | `ReentrantLock` | `std::mutex` |
| Combined stop/reconnect signal | `BooleanSupplier` polled every 200ms | `std::atomic<bool>` + edge-triggered wake (see below) |
| Pending-reaper scan | linear scan of the map every 1s | min-heap keyed on expiry (see below) |
| Monotonic clock for TTLs | `System.nanoTime()` | `std::chrono::steady_clock` |

**Hot path — framing and the per-connection read loop**: `Framing.recvExact`'s inner loop
(`while (off < n) read(...)`) becomes a blocking `recv()` loop in a dedicated thread per
connection, using a pre-allocated stack or fixed buffer — no heap allocation inside the loop. The
ISO 8583 encode/decode (currently j8583) needs a C++ field parser; the field table above
(`FIELD_SPECS`) is small enough to become a compile-time lookup table.

**Pending map sharding**: `Dispatcher.pending` is a single `ConcurrentHashMap`. At high TPS this
can still become a contention point (workers insert, the ds-receiver thread pops, on every
transaction). In C++, shard by `routerStan % N_BUCKETS` across N separate maps, each with its own
mutex — 16 buckets cuts the per-lock contention rate by roughly 16× with no algorithmic change.

**Pending reaper — linear scan vs. expiry heap**: the reaper here scans every entry every second
looking for anything past its TTL. In C++, maintain a min-heap keyed on expiry time alongside the
hash map — push on insert, pop and discard stale top entries on each wake instead of a full scan.

**Bounded queue**: `ArrayBlockingQueue` maps to a `std::deque` + mutex + condition variable, with
`submit()` waiting on the condition variable while the deque is at capacity and workers signaling
it after each dequeue. A lock-free bounded MPMC ring buffer avoids the mutex entirely but adds
real implementation complexity — get the mutex version correct first.

**Combined stop/reconnect signal**: the `BooleanSupplier` polled every 200ms in `Upstream`'s
connect/accept loops is a deliberate simplicity tradeoff, acceptable given this project's
multi-second retry/reestablish intervals. In C++, replace with a single `std::atomic<bool>` set by
either condition, and interrupt a blocking `accept()`/`connect()` via `SO_RCVTIMEO` or a self-pipe
trick rather than polling — edge-triggered is both cleaner and cheaper than any fixed poll
interval.

**Teardown — shutdown() before close()**: this spec closes sockets directly to unblock a thread
parked in a blocking read on them. On a POSIX system, `close()` on a socket that another thread is
concurrently blocked on is technically a race — the file descriptor number can be reused by an
unrelated `accept()`/`socket()` call on another thread between the `close()` and the blocked
thread's return. The JVM (and Python's GIL/fd-lifetime handling) papers over this; C++ does not.
The safe pattern in C++ is `shutdown(fd, SHUT_RDWR)` first (delivers EOF to the blocked `recv()`,
which returns 0 without invalidating the fd), *then* join the blocked thread, *then* `close()`.

**Write lock per upstream connection**: each upstream connection's single write lock, shared
between the read thread's own occasional writes (0800 forwarding) and any worker/ds-receiver
thread writing a response back, is correct and cheap as-is — no per-message allocation. A
`std::mutex` per connection struct is the direct C++ equivalent; no redesign needed here.
