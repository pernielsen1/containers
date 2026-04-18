# ISO 8583 Authorization Test Utility — Brief v2

## Overview

Build a command-line application that tests ISO 8583 authorization messages over TCP/IP.
The application runs as either a **client** (test sender) or a **test server** (authorization simulator).
The role is the first positional argument: `client` or `server`.

---

## Configuration

All tuneable values live in `config.json`.
Command-line arguments override config where both exist.
Unknown keys in the CSV or config must be silently ignored.

```json
{
  "tcp_framing": "TCP_framing_standard",
  "log_level": "INFO",
  "client": {
    "iso_spec":        "test_spec.json",
    "input_dir":       "input",
    "output_dir":      "output",
    "connect_timeout": 60,
    "batch_size":      50,
    "batch_wait":      10,
    "send_delay":      0.05
  },
  "server": {
    "iso_spec":        "test_spec.json",
    "positive_list":   "positive_list.json",
    "idle_timeout":    120
  }
}
```

---

## Command-line Parameters

| Parameter       | Applies to     | Default             | Description |
|-----------------|----------------|---------------------|-------------|
| `role`          | both           | *(required)*        | `client` or `server` |
| `--port`        | both           | `1042`              | TCP port |
| `--host`        | client         | `localhost`         | Server hostname or IP |
| `--framing`     | both           | *(from config)*     | Override TCP framing scheme |
| `--verbose` / `--no-verbose` | both | on             | Enable per-message hex dump |
| `--log-level`   | both           | *(from config)*     | Override log level: `DEBUG` `INFO` `WARNING` `ERROR` `CRITICAL` |

---

## ISO 8583 Message Format

The message structure is defined in `test_spec.json` (path configurable per role in config.json).
Fields are referenced by their element key names as defined in the spec (e.g. `t`, `2`, `3`, `11`, `39`).

Fields auto-managed by the library (header, primary bitmap, secondary bitmap, binary fields) must never
be set from CSV data — identify and exclude them before encoding.

---

## TCP Framing

Two framing schemes are supported, selected by `tcp_framing` in config.json:

### `TCP_framing_standard`
```
[ 4 bytes big-endian uint32 length ][ data ]
```

### `TCP_framing_FFFF_nnnn`
```
[ FF FF FF FF ][ 4 ASCII digit decimal length ][ data ]
```
If the 4-byte marker is not `0xFFFFFFFF`, log a warning and discard the frame.

---

## Threading Model

After the TCP connection is established both client and server operate with two threads per connection:

- **receive thread** — reads and processes inbound frames
- **send thread** — encodes and writes outbound frames (fed via a queue)

---

## Client Behaviour

### Input
- Reads `{input_dir}/test_cases.csv`
- Semicolon (`;`) separator, UTF-8 with BOM encoding
- Column headings are ISO 8583 field element keys plus optional metadata columns
- Metadata columns (`comment`, `expected_39`, etc.) are passed through to results but never encoded into ISO messages

### Sending
- For each row: encode an ISO 8583 message and send it to the server
- Auto-generate field `11` (STAN): 6-digit zero-padded sequential counter
- Field `63` is sent as-is from the CSV; it is the **correlation key** for matching responses
- Do not wait for a response before sending the next message
- After every `batch_size` messages, pause `batch_wait` seconds
- Apply `send_delay` seconds between individual messages

### Connection
- Retry connection every 1 second for up to `connect_timeout` seconds
- Exit with an error if the server is not reachable within the timeout

### Receiving
- Match each response to its request using **field 63** (not STAN)
- After all messages are sent, wait up to 20 seconds for all responses to arrive

### Output
Create `{output_dir}/` automatically if it does not exist.

**`{output_dir}/results.csv`** — every response row, merged with its original request row.
Response fields are prefixed `resp_` (e.g. `resp_39`, `resp_38`).
Preserve all original request columns including metadata.
Semicolon separator, UTF-8 with BOM.

**`{output_dir}/errors.csv`** — subset of results where `expected_39 ≠ resp_39`.
Same format as results.csv.
If no mismatches exist, log a clean summary message and do not write the file.

---

## Server Behaviour

### Startup
- Bind to `0.0.0.0:{port}`, accept one client at a time
- Load the positive prefix list from `positive_list.json`:
  ```json
  { "starts_with": ["543210", ...] }
  ```

### Per-message processing
1. Decode the ISO 8583 frame
2. Check MTI (field `t`):
   - `0100` (Authorization Request) → process and respond with `0110`
   - Anything else → log a warning and skip (do not respond)
3. Build response:
   - Set MTI (`t`) to `0110`
   - Echo fields: `2`, `3`, `4`, `11`, `37`, `41`, `42`, `63`
   - If field `2` starts with any prefix in the positive list:
     - Set field `39` = `"00"` (approved)
     - Set field `38` = 6-digit zero-padded sequential auth code (global counter, incremented per approval)
   - Otherwise:
     - Set field `39` = `"01"` (declined)
4. Encode and enqueue the response

### Shutdown
- If no inbound messages are received for `idle_timeout` seconds, shut down gracefully

---

## Logging

Default level: `INFO` (config.json `log_level`, overridden by `--log-level`).

| Level   | Events |
|---------|--------|
| DEBUG   | Per-message: hex dump, RECV/SEND details, Approved/Declined per PAN, Client connected, Response field 63 / RC |
| INFO    | Session start/stop, connection established, batch milestones, final stats, results written |
| WARNING | Unexpected MTI, decode/encode errors, unexpected framing marker |

---

## Test Driver (`run_test`)

A separate script/program that runs the full test suite for both framing schemes sequentially.

For each framing scheme:
1. Start the server process with `--framing {scheme}`
2. Wait briefly for the server to bind (0.5 s)
3. Start the client process with `--framing {scheme}`
4. Wait for the client to finish (timeout: 60 s); kill if it times out
5. Terminate the server; wait up to 10 s; kill if needed
6. Check that `{output_dir}/results.csv` exists → PASS / FAIL

Print a summary table of PASS/FAIL per scheme. Exit with a non-zero code if any scheme failed.

---

## File Layout

```
project/
├── config.json
├── test_spec.json
├── positive_list.json
├── main.[ext]
├── run_test.[ext]
├── input/
│   └── test_cases.csv
└── output/           ← created at runtime
    ├── results.csv
    └── errors.csv    ← only if mismatches exist
```

---

## test_cases.csv Columns

| Column        | Type   | Description |
|---------------|--------|-------------|
| `t`           | string | MTI, e.g. `0100` |
| `2`           | string | PAN |
| `3`           | string | Processing code |
| `4`           | string | Transaction amount |
| `11`          | string | STAN — leave blank; auto-generated |
| `37`          | string | Retrieval reference number |
| `41`          | string | Terminal ID |
| `42`          | string | Merchant ID |
| `63`          | string | Correlation reference (echoed by server) |
| `comment`     | string | Free text — ignored during encoding |
| `expected_39` | string | Expected response code for validation |

Additional columns are passed through to results but ignored during encoding.
