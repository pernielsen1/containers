# facts

## message_protocol
For non HTTP/REST messages the message protocol means data are prepended with a
header_field, length_field then data. For each connection the actual implementation
is configured in a json file.

header_field may be zero in length.
length_field_type may be BIG_ENDIAN, LITTLE_ENDIAN, ASCII or EBCDIC.
ASCII encoding means the length is written as ASCII digit characters, e.g. a
42-byte message is encoded in 4 bytes as X'30303042'.
The data part will be length_field bytes.

### client_or_server
client or server

### port
TCP/IP port where the actor is accepting/connecting to

### command_port
The port where the actor will have an HTTP server accepting controlling commands.

### host
In case of client this is the host to connect to; for testing usually localhost.

### protocol
REST or message_protocol.
If message_protocol then include length_field encoding (BIG_ENDIAN, LITTLE_ENDIAN,
ASCII, EBCDIC) plus length_in_bytes of length_field.
The actual messages in data are ISO 8583 messages — see skill iso8583.

## PANS_defined
pans_defined.json contains a whitelist of card numbers. Card numbers are field 2
of the ISO 8583 message. There is also a key for each PAN "crypto_result" which
is either False or True.

# resilience
No process should exit without having released the TCP/IP sockets, i.e. a server
malfunctioning should not retain a lock on the port.

# concurrency model
The implementation uses threading (one thread per connection).
threading.Lock protects all shared state (pending-requests dict, stats counters).

Rationale: the threading model maps 1:1 to C++ (std::thread, std::mutex, recv/send)
making a future C++ port straightforward. asyncio would require a full conceptual
rewrite in C++.

# Primary objective
Build a resilient application acting as "man in the middle" aka the "router".
To test the application a number of other actors need to be introduced.

## actors
Each actor in the solution will have a config.json.
Each actor exposes an HTTP server on command_port with the following commands:
- stop: the actor gracefully stops and releases all system resources.
- stats: each actor tracks message statistics (number of messages received/sent)
  available for the last 30, 60, 180 and 1800 seconds.

### router
The star of the show — routes 0100 messages from upstream_host to downstream_host.
Before forwarding, the router calls crypto_host (REST, synchronous per request)
to check crypto; the reply is encoded into field 47.

The router does not wait for one crypto_host call to complete before accepting the
next request from upstream_host (non-blocking across connections). It can be assumed
that crypto_host provides load balancing.

When 0110 response messages are received from downstream_host, a new call is made
to crypto_host (/validate_0110) to enhance the contents of field 47 with the reply.
The enhanced 0110 is then forwarded back to upstream_host.

Message correlation (matching 0110 to the original 0100): STAN (field 11).

### downstream_host
A simulator — receives ISO 8583 0100 messages and determines approve or decline.
- Message protocol: BIG_ENDIAN 4-byte length field, no header.
- If PAN (field 2) is not found in pans_defined.json → decline: field 39 = 01.
- Else inspect field 47: if it is a JSON string containing key "crypto_result"
  with value False → decline: field 39 = 01.
- Else → approve: field 39 = 00, field 38 = unique 6-digit approval code
  (unique within the session).

### crypto_host
Implements crypto functionality with two REST endpoints.

#### /validate_0100
Input: field 2 (PAN) and field 47.
If PAN is found in pans_defined.json, set crypto_result = True, else False.
Encode result as JSON into field 47: {"crypto_result": true/false, ...}
Return updated field 47.

#### /validate_0110
For now mimics /validate_0100. Will be refined later.

### upstream_host
Establishes connection to router with length_field_type=ASCII, 4-byte length field.
The command server supports:
- /upload: accepts a CSV file of test cases (column headings = ISO 8583 field
  numbers; binary fields such as field 52 are hex-encoded).
- /start: begins sending the uploaded test cases to the router.
- /stop, /stats: standard commands.

ISO 8583 spec file: test_spec.json (ASCII encoding), reused from auth_test/.
pans_defined.json: shared file at xv2 root; path referenced in each actor's config.json.
