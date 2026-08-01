# crypto_host — shared EMV crypto validation service

## Purpose

Real (OpenSSL-backed) EMV cryptographic validation — PIN/ARQC/CVV2/AAV verification, ARPC
computation — for all three ISO 8583 router implementations in this project (`../router_py`, `../router_java`,
`../router_cpp`). Promoted out of router_cpp's own `crypto_host` actor into this standalone container so it
can be shared: in real life this actor will be a Fortanix DSM-backed service, scaled independently
behind a load balancer, and it's the actual performance bottleneck for all three router
implementations alike. Testing each implementation against its own bundled crypto simulator
muddied the python-vs-java-vs-c++ performance comparison the project's `stress_test.sh` exists to
produce — this container gives all three the same crypto backend to measure against. See
`../divide_and_conquer.md` for the original design discussion.

Each of router_py/router_java/router_cpp still keeps its own lightweight **stub** crypto_host (no OpenSSL, no
PIN/ARQC/CVV2/AAV math — just a PAN-presence check returning response_code `"00"`/`"14"`) so each
implementation can still be built and functionally tested standalone, without this container
running. This container is only required for performance-comparison runs (`stress_run.sh` in each
implementation, orchestrated by `../stress_test.sh`).

## Wire contract

Identical to the contract router_java/router_cpp's routers already speak (deliberately shaped to mimic
Fortanix DSM's real "invoke a plugin" API, so a later swap to a real Fortanix DSM tenant is a
config/URL change, not a rewrite):

- `POST /sys/v1/plugins/{plugin_id}`
- Header: `Authorization: Bearer {bearer_token}`
- Body: `{"operation": "validate_0100"|"validate_0110", "f2": "<pan>", "f47": "<f47_json_string>"}`
- Response: a base64-encoded JSON string that decodes to `{"f47": "<enriched_f47_json_string>"}`
- `404` if `plugin_id` doesn't match config; `401` if the bearer token doesn't match.

`validate()` runs the same checks as the original router_cpp implementation: PAN lookup (→
response_code `14` if unknown), `f52` PIN verification, `f55` ARQC verification (0100) or ARPC
computation (0110), `cvv2` verification, `aav` verification — see `src/simulators/crypto_host/crypto_host_main.cpp`.

A separate `CommandServer` (same shared module as every other actor in this project) exposes
`/stats`, `/stop`, `/log_level`, `/logs` on its own port.

## Repository layout

```
crypto_host/
├── CMakeLists.txt          # single executable (crypto_host) + crypto_host_tests (Catch2)
├── Dockerfile              # ubuntu:22.04 + cmake/g++/git/libssl-dev/pkg-config
├── docker-compose.yml      # one service, network_mode: host
├── start.sh                # docker compose up -d --build, polls localhost:8099/stats
├── stop.sh                 # docker compose down
├── config/
│   ├── crypto_host.json    # {name, log_level, pans_defined, yellow_threshold_seconds,
│   │                        #  crypto: {port, command_port, plugin_id, bearer_token}}
│   └── pans_defined.json   # card + key data (copied from router_cpp's)
├── src/
│   ├── shared/     hex, base64, ebcdic, framing, iso_codec, stats, log, crypto_utils,
│   │               command_server, pans_defined, stop_event.h — all copied from router_cpp/src/shared/
│   ├── router/     router_config.{h,cpp} — reused as-is; RouterConfig::from_file tolerates a
│   │               config with no upstream/downstream section, which is all this actor needs
│   └── simulators/crypto_host/crypto_host_main.cpp
└── test/crypto_utils_test.cpp   # moved verbatim from router_cpp, Catch2
```

`ebcdic`/`framing` are linked in even though `crypto_host_main.cpp` never calls them directly —
`router_config.cpp`'s `parse_downstream()`/`parse_upstream()` helpers reference them
unconditionally (even though this actor's config never has those sections), so they have to be
present at link time. `ims_connect.{h,cpp}` is the one router_cpp shared/ file genuinely not needed
here (its `to_ebcdic` is duplicated by `ebcdic.h`, which `router_config.cpp` actually calls).

## Configuration

`config/crypto_host.json`:

```json
{
  "name": "crypto_host",
  "log_level": "INFO",
  "pans_defined": "pans_defined.json",
  "yellow_threshold_seconds": 60,
  "crypto": {
    "host": "localhost",
    "port": 5099,
    "command_port": 8099,
    "plugin_id": "emv-plugin",
    "bearer_token": "crypto-token-456"
  }
}
```

Ports 5099/8099 are deliberately distinct from every implementation's own local stub crypto_host
(5002/8082) — this container is meant to run alongside whichever implementation is under test,
not swap places with its local stub, so nothing about an implementation's normal docker-compose
setup needs to change to accommodate this container's presence.

Each router implementation's `*_perf` config variant (e.g. `../router_py/router/router_1/config_perf.json`)
points its own `crypto` section at `host: localhost, port: 5099` with these same
`plugin_id`/`bearer_token` values, so it can reach this container instead of its local stub.

## Build & run

```bash
./start.sh   # builds the image (if needed) and starts the container; polls localhost:8099/stats
./stop.sh    # docker compose down
```

This is shared infrastructure, not one of the three implementations under comparison — unlike
`router_py`/`router_java`/`router_cpp`, it's meant to stay running across all of their performance runs rather
than being torn down between them. `../stress_test.sh` starts it once at the top of a sweep and
never stops it; the individual implementations' `stress_run.sh` scripts assume it's already up.

### Manual smoke test

```bash
curl -X POST http://localhost:5099/sys/v1/plugins/emv-plugin \
  -H "Authorization: Bearer crypto-token-456" \
  -H "Content-Type: application/json" \
  -d '{"operation":"validate_0100","f2":"4111111111111111","f47":"{\"message_type\":\"0100\"}"}'
# -> base64 string; decodes to {"f47":"{\"message_type\":\"0100\",\"response_code\":\"00\"}"}
```

### Tests

`ctest` (or `docker run --rm crypto_host-crypto_host /src/build/crypto_host_tests`) runs the
Catch2 suite in `test/crypto_utils_test.cpp` — the same low-level PIN/ARQC/CVV2/AAV/ARPC math unit
tests router_cpp used to run, now living here since this is the only place that math still exists.
