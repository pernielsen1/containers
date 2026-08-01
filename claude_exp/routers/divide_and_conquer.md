# split router and simulators part 1 with stubs.
Let's discuss thie:
we are now looking at performance where crypto_host will be the weakest link.
crypto_host will real life be a fortanix implementation scalable with multiple load balanced servers.

My gut feeling says we should split the simulators (at least starting with crypto_host) from the core router.
leading me to say in the first step that we should have a simulator_host in an own container based on the c++ implementation based on openssl.  this should also reduce the rebuild impact on c++ container for router.

# downsides
splitting crypto_host to own container will make testing more complicated - should we have a stub implementation (simple without openssl - just saying here is a return field) inside each of the python, java, c++ implementations.

So what's your view

Done: crypto_host's real OpenSSL-backed validation (PIN/ARQC/CVV2/AAV verification, ARPC
computation) has been extracted from router_cpp into a new shared container at `routers/crypto_host/`
(its own CMake/C++ project, Dockerfile, docker-compose.yml, `start.sh`/`stop.sh`, listening on
ports 5099/8099) - all three implementations now measure against this one real crypto backend
during performance runs instead of their own local simulators. Each of router_py/router_java/router_cpp keeps a
lightweight stub crypto_host (no OpenSSL - just reports whether the PAN is provisioned, response
code "00"/"14") for everyday standalone functional testing without the shared container running.

Along the way, Python's wire contract had drifted from Java/C++'s Fortanix-shaped protocol
(`POST /sys/v1/plugins/{plugin_id}`, bearer auth, base64 envelope) - it still spoke a plain
`POST /validate_0100` with no auth. Fixed forward: `router_py/router/crypto_client.py` and
`simulators/crypto_host/main.py` now speak the same contract as Java/C++, so all three could
plug into the one shared container.

Each implementation gained a `*_perf` config variant (e.g. `router_py/router/router_1/config_perf.json`)
whose `crypto` section points at the shared container (`localhost:5099`) instead of the local
stub; `stress_run.sh` in each implementation uses that variant and no longer launches its own
local crypto_host during perf runs, and `routers/stress_test.sh` starts the shared container once
before sweeping all three implementations (it is not torn down between runs - it's shared
infrastructure, not the thing under test). See each implementation's `build_router.md` for the
updated wire-contract/stub details, and `routers/crypto_host/build_router.md` for the shared
container's own spec.

# divide and conquer part 2 we are at a stable stage - and have isolated where possible performance issues are.
focus is on the router not the simulators upstream, downstream nor crypto_host.
we know the isolated crypto_host will not be a problem in performance tests and have a perfectly Ok throughput.
so know I want to go for simplicity 
## simplicity
I will not finally settle on python, java or c++ for the router.
the external crypto_host will stay in it's cpp installation
crypto stubs are kept close to the routers i.e. valid for flow but not functional integration.
the downstream_host is so simple (basically an echo) so let's keep it as it is.
for the upstream_hosts - my proposal is to have these in the host as python implementations kept together with the monitor - this means that the routers are "containorized" (including the echo downstream) and the rest is outside.
an alternative is to have a python container with simulators upstream, monitor and downstream.. 
what's your opinion

Decided: host-side Python for both the upstream_host simulators and the monitor, not a shared
container. `monitor` is already an uncontainerized host process, so this extends a pattern already
accepted rather than adding a new container to build/rebuild - and since every actor talks over
`localhost` (host networking), containerizing the load generator would buy no real isolation
benefit, only a rebuild-cycle tax on the piece most actively iterated on during perf work.
`downstream_host` stays as-is, embedded per-language alongside each router (it's a trivial echo,
not a comparison point, and not worth the churn of centralizing). Net effect: the router-per-
language containers remain the thing under test; the host-side monitor + one shared upstream_host
implementation become the thing that drives and observes the test, replacing the 3 duplicate
per-language upstream_host reimplementations that existed only for parity. Not yet implemented.

Implemented (this round): `routers/upstream_host/` built as described above; router_py/router_java/router_cpp
all repointed to it. Two real cross-language wire-format bugs surfaced along the way, both latent
until this consolidation forced a Python client to talk to a non-Python router for the first time
(each language's router had only ever been tested against its own same-language upstream_host,
so an internally-consistent-but-wrong convention never showed up before):
- router_java: j8583's `MessageFactory` defaults to a text/ASCII-hex bitmap; the shared component's
  pyiso8583 spec (`test_spec.json`, `"data_enc": "b"`) encodes the bitmap as raw binary bytes.
  Fixed with one `factory.setUseBinaryBitmap(true)` call in `IsoUtils.loadFactory()`.
- router_cpp: the hand-rolled codec encoded the MTI as 2 raw binary bytes (`mti >> 8`/`mti & 0xff`);
  pyiso8583 (and j8583) encode it as 4 ASCII characters ("0100"). Fixed in `iso_codec.cpp`'s
  `encode()`/`decode()` to read/write the MTI as 4 ASCII bytes directly.

**Note for next round**: the user flagged that this pattern (each language quietly picking its own
"interpretation" of the wire format - bitmap encoding, MTI encoding, and whatever else hasn't
surfaced yet) shouldn't be hardcoded per-implementation and rediscovered by trial and error like
this. `test_spec` should be the single source of truth for encoding choices, not just field
shapes - and there may need to be multiple `test_spec` variants, one per real-world partner being
emulated (different partners may genuinely use different bitmap/MTI conventions on the wire, not
just different field lists). Not designed or implemented yet - needs its own discussion before
picking an approach (e.g., whether the JSON spec format itself gains explicit encoding-convention
keys that every language's codec must read and honor, rather than assuming one fixed convention
in code).

# renames, missing functionality and iso specs.
make a plan and ask questions for clarifications
## rename
since we have now split simulators and crypto_host and verified working even with performance metrics it's time to rename
router_py -> router_py
router_java -> router_py
router_cpp -> router_cpp
this rename should also be done in various config & md files. 

## missing functionality 
somewhere going from python to java we lost the upstream_2 so there is only one upstream connection in java and cpp 
add so we have upstream_2

## iso specs
each upstream connection may have their own variant of iso8583 config - so it should be possible to point at different specs - today only test_spec.json is active.
so make a test_spec_ebcdic.json where all ascii becomes EBCDIC instead.
let upstream_1 use test_spec.json as today and let upstream_2 use test_spec_ebcdic.json

(Note: line 89 above — "router_java -> router_py" — is the original "xv6java -> router_py" typo,
mechanically relabeled by this round's own rename script when it ran; the actual, clarified target
confirmed before implementation was **router_java -> router_java**, per the plan below.)

Done — plan approved after clarifying questions (three genuinely ambiguous/underspecified points,
resolved before implementation):
1. The `xv6java -> router_py` collision above was a typo; confirmed target is `router_java`.
2. "We lost upstream_2 going from python to java" turned out not to mean a concurrency gap (no
   router in any language accepts more than one live upstream connection at a time) — it's that
   router_py already runs a second, independent router+load-generator pair (`router_2`/
   `upstream_2`, disabled by default, `router_2` connecting **out** to `upstream_2` in reversed
   client/server roles from `router_1`) that never got ported to java/cpp. That pair is what got
   replicated, not a rearchitecture of connection handling.
3. A literal "swap `upstream_2`'s spec to EBCDIC" reading would have broken `router_2`'s
   downstream leg (the shared `downstream_host` only understands ASCII) — every `router_2`
   request would time out rather than complete. Resolved by splitting each router's spec/encoding
   into an upstream-facing half (EBCDIC on `router_2`, unchanged on `router_1`) and a
   downstream-facing half (always ASCII, all routers) — confirmed with the user before touching
   any dispatcher code.

**Rename**: `router_py`/`router_java`/`router_cpp` renamed across the entire repo — directories
(`git mv`-equivalent), every top-level script (`stress_test.sh`, `monitor.sh`, `start_docker.sh`,
the soak-sequence scripts), every `docker-compose.yml` `container_name` (including router_java's
two distinct containers, dev `xv6java` -> `router_java` and compose-managed
`xv6java-deploy` -> `router_java-deploy`), the Java `pom.xml` artifact/`finalName` (had to move
together with the scripts, which now expect `target/router_java.jar`), the CMake `project(...)`
name, and every doc/comment reference down to zero remaining hits outside the deliberately
untouched `com.xv6.*`/`xv6::` internal namespaces (out of scope per the plan) and historical CSV
run data (left alone — rewriting old rows under new names would falsify history; new runs write
new rows under the new names naturally).

**`router_2`/`upstream_2`**: added to router_java and router_cpp, replicating router_py's existing
disabled-by-default pattern exactly (own `command_port`, own upstream port 5010, `router_2`
connects out as client, `upstream_2` listens as server, `downstream.client_id: CLIENT03` to stay
distinct from `router_1`'s `CLIENT01` on the shared `downstream_host`/`crypto_host`). This needed
real code changes in both monitors, not just new config files: router_java's actor-discovery gate
only recognized `router`/`downstream`/`crypto` types, silently dropping an `upstream`-typed config
from discovery; router_cpp's monitor had zero concept of more than one router instance at all
(a single hardcoded config path shared by every actor and every kill-pattern match) and needed
genuine per-actor config-path tracking added. router_py's stale `upstream_3` scaffolding (an
older, now-superseded 3-way test scenario) was dropped as part of this, since the target end state
is one `upstream_1`/`upstream_2` pair per implementation.

**EBCDIC on `router_2`'s upstream leg**: `routers/upstream_host/test_spec_ebcdic.json` — a
field-by-field copy of `test_spec.json` with `data_enc`/`len_enc` flipped from `"ascii"` to
`"cp500"` (IBM EBCDIC code page 500, the codebase's existing EBCDIC convention) on text fields;
binary fields (`p`/`1`/`52`/`55`) untouched, since they're raw bytes in either variant. Two real,
previously-unknown cross-language findings surfaced building this, both confirmed by hands-on
testing rather than assumption:
- **router_java**: j8583's `MessageFactory.setCharacterEncoding("Cp500")` alone translates the MTI
  and field *data* to EBCDIC but silently leaves the LLVAR/LLLVAR length-prefix digits in plain
  ASCII — confirmed by disassembling `IsoValue.writeLengthHeader`'s bytecode. A genuinely
  EBCDIC-speaking partner needs the length prefix in EBCDIC too (this was flagged by the user's
  own domain knowledge after an initial assumption to the contrary); fixed by also enabling
  `setForceStringEncoding(true)`, verified with a standalone round-trip test before wiring it into
  the live router.
- **router_cpp**: the hand-rolled codec had no encoding concept at all. Added an `Encoding` enum
  threaded through `iso_codec::encode`/`decode`/`build_0800`/`build_0810`, reusing the project's
  existing CP500 lookup table (`ebcdic.h`) via two new byte-for-byte, no-padding translation
  functions (`ascii_to_ebcdic_bytes`/`ebcdic_to_ascii_bytes` — the existing `to_ebcdic`/
  `from_ebcdic` pad/truncate, the wrong semantics for already-shaped ISO field bytes).

All three implementations' `router_2`/`upstream_2` pairs were verified with a live CSV burst
(correct `resp_39` response codes, including the intentionally-invalid test row) over the EBCDIC
leg, cross-checked byte-for-byte against each other (a Java- or C++-encoded EBCDIC message decodes
correctly in pyiso8583 and vice versa) — not just internally self-consistent within one language.
`router_1` in all three was confirmed unaffected (single-spec configs default `upstream_iso_spec`/
`upstream_iso_encoding`/`upstream.encoding` to unset/ascii, byte-for-byte unchanged from before
this round). See each implementation's `build_router.md` for the full config/code-level detail,
and `divide_and_conquer_v2.md` for the updated architecture snapshot.

Also fixed incidentally, found while touching the same code: a stale pre-existing test bug in
`router_cpp/test/iso_codec_test.cpp` still asserted the codec's *original*, already-superseded
2-binary-byte MTI encoding (superseded by the 4-ASCII-byte fix from the earlier upstream_host
consolidation round) — left over from before that fix, unrelated to this round's own changes, but
fixed since it would otherwise make test output noisy/misleading.




