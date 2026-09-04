import argparse
import csv
import json
import logging
import os
import socket
import sys
import threading
import time
from collections import deque
from datetime import datetime
from itertools import count

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import iso8583  # noqa: E402
from flask import jsonify, request  # noqa: E402

# upstream_shared, not shared: this component runs standalone but is also imported in-process by
# router_py's pytest suite (UpstreamHostSim) alongside router_py's own "shared" package - a same-named package
# would silently collide in sys.modules within that one process.
from upstream_shared.command_server import CommandServer  # noqa: E402
from upstream_shared.framing import read_message, write_message  # noqa: E402
from upstream_shared.iso_utils import build_0800, load_spec  # noqa: E402
from upstream_shared.json_log import configure_logging  # noqa: E402
from upstream_shared.log_throttle import ThrottledLogger  # noqa: E402
from upstream_shared.ssl_utils import wrap_client_socket, wrap_server_socket  # noqa: E402
from upstream_shared.stats import Stats  # noqa: E402

logger = logging.getLogger(__name__)
_throttled = ThrottledLogger(logger, every=200)

_STAN_MODULUS = 1_000_000
_RESPONSE_MTIS = ("0110", "0130", "0430")
# briefs/resilience_v2.md: a 0100 that times out gets both a 0420 (reversal - "forget my 0100")
# and a 0120 (advice - the STIP decision made on the cardholder's behalf) independently, each
# store-and-forward until its own ack arrives.
_ADVICE_ACK_MTI = {"0420": "0430", "0120": "0130"}


def load_config(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(path) as f:
        cfg = json.load(f)
    base_dir = os.path.dirname(os.path.abspath(path))
    cfg["iso_spec"] = os.path.normpath(os.path.join(base_dir, cfg["iso_spec"]))
    cfg["input_dir"] = os.path.normpath(os.path.join(base_dir, cfg.get("input_dir", "input")))
    cfg["error_csv"] = os.path.normpath(
        os.path.join(base_dir, cfg.get("error_csv", "error_0120_0420.csv"))
    )
    for key in ("certfile", "keyfile", "cafile"):
        if cfg.get(key):
            cfg[key] = os.path.normpath(os.path.join(base_dir, cfg[key]))
    return cfg


class _Connection:
    """One socket plus the disc_evt that tears it down (see _write_frame) - bundled into a single
    object instead of two loose fields (self._conn/self._disc_evt) that every reader/writer had to
    remember to keep in sync by hand across four separate call sites. Passed by reference wherever
    a raw socket used to be passed; .sock is the only thing actual I/O touches, .disc_evt is the
    same event object every reader of "is this connection still current" already needs. Same
    principle as crypto_client.py's per-thread cached-connection state - a stale/invalidated
    resource is modeled as one object with its own validity signal, not scattered fields."""
    __slots__ = ("sock", "disc_evt")

    def __init__(self, sock):
        self.sock = sock
        self.disc_evt = threading.Event()


class UpstreamHostSim:
    """Simulates an upstream card network client."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.spec = load_spec(cfg["iso_spec"])
        self.framing = cfg["framing"]
        self.mode = cfg.get("mode", "client")
        self.ping_0800_seconds = cfg.get("ping_0800_seconds", 30)

        os.makedirs(cfg["input_dir"], exist_ok=True)

        self.stats = Stats(yellow_threshold_seconds=cfg.get("yellow_threshold_seconds"))
        self.stop_event = threading.Event()

        self._current = None  # the active _Connection, or None - see _Connection/_get_conn
        self._conn_lock = threading.Lock()
        # Guards writes to the active connection's socket: _send_loop (stress/functional sends)
        # and _keepalive_loop
        # (periodic 0800s) run on separate threads and both write to the same connection. Under
        # plain TCP that silently worked; under TLS, two threads calling SSL_write() concurrently
        # on the same SSLSocket corrupts the record stream (seen as a DECRYPTION_FAILED_OR_BAD_
        # RECORD_MAC on the router's side, killing the connection almost immediately).
        self._write_lock = threading.Lock()

        self._stan_counter = count(1)

        self.pending = {}
        self.pending_lock = threading.Lock()
        self.results = []
        self.results_lock = threading.Lock()

        # Advice/reversal (briefs/resilience_v2.md): a 0100 with no 0110 within
        # advice_timeout_seconds gets both a 0420 and a 0120, each tracked here keyed by its own
        # (fresh) STAN and store-and-forward retried until its ack (0430/0130) arrives or
        # advice_max_retries is exhausted. Separate from `pending` above (which is real
        # transaction round-trip tracking) since these carry no crypto/latency/results semantics
        # of their own - just "did this get acknowledged."
        self.advice_timeout_seconds = cfg.get("advice_timeout_seconds", 1.0)
        self.advice_max_retries = cfg.get("advice_max_retries", 5)
        self.advice_backoff_multiplier = cfg.get("advice_backoff_multiplier", 15.0)
        # load_config() normalizes this to an absolute path; falls back to a bare relative name
        # for callers (tests) that construct UpstreamHostSim directly with a hand-built cfg dict.
        self.error_csv_path = cfg.get("error_csv", "error_0120_0420.csv")
        self.advice_pending = {}
        self.advice_lock = threading.Lock()
        # briefs/resilience_v2.md ("have been evaluating the scenario"): unthrottled, a burst of
        # 0100 timeouts (e.g. during a crypto_host kill) fires a burst of 0420/0120 sends with no
        # relation to the 0100 pacing, competing for wire capacity with live 0100 traffic and
        # clouding the achieved_tps numbers. advice_reversal_percentage caps how much of that
        # capacity 0120/0420 traffic gets, expressed as one advice/reversal dispatch per N 0100
        # sends - e.g. 10% -> N=9 (1 advice send per 9 0100 sends, brief's own worked example).
        # None (0/unset) disables throttling entirely: every advice send fires immediately, same
        # as before this feature existed (this is also what every existing advice test relies on,
        # since none of their configs set this key).
        pct = cfg.get("advice_reversal_percentage", 0)
        self._advice_ratio = max(1, round((100 - pct) / pct)) if 0 < pct < 100 else None
        # STANs waiting for their throttle slot - only used while self._advice_ratio is set and a
        # 0100 stream is actively running (see _send_loop). Actual message data lives in
        # advice_pending, keyed the same way; this just orders who gets the next slot.
        self.advice_send_queue = deque()
        self._advice_slot_counter = 0
        # Per-run (since last /start) counts of 0120/0420 traffic, split by MTI and by
        # sent-vs-acked - separate from advice_pending (current outstanding) and from
        # run_sent/results (0100/0110 only, see _send_loop/_receive_loop) so /stress_stats can
        # report advice-message volume for the same window the 0100 TPS numbers cover, without
        # either polluting the other. "sent" includes every wire send (initial + each retry from
        # _advice_retry_loop), not just the first attempt.
        self.advice_counts = {"0120_sent": 0, "0420_sent": 0, "0120_acked": 0, "0420_acked": 0}

        # Stress-run state: send timestamps keyed by STAN, and a bounded latency-sample list.
        # Capped at 200k - plenty for any run duration/rate used here, keeps memory bounded on a
        # long high-rate stress run instead of growing unboundedly.
        self._MAX_LATENCY_SAMPLES = 200_000
        self.send_times = {}
        self.latencies = []
        # (sent_offset_s, latency_s) per completed round trip - sent_offset_s is time-since-
        # run-start when the 0100 was sent, so the slowest entries can be correlated against when
        # in a long run they happened (e.g. a GC pause a few minutes in).
        self.latency_records = []
        self.run_start_time = None
        self.run_end_time = None
        self.run_sent = 0
        # Set for the duration of a warmup phase (see _run_with_warmup) - _receive_loop checks
        # this to discard warmup responses instead of counting them into stress stats.
        self._warmup_active = False

        self.cmd = CommandServer(cfg["command_port"], self.stats, self.stop_event)
        self._register_routes()
        self._listen_sock = None

    def _next_stan(self) -> str:
        stan = next(self._stan_counter) % _STAN_MODULUS
        return str(stan).zfill(6)

    def _csv_path(self) -> str:
        return os.path.join(self.cfg["input_dir"], "test_cases.csv")

    def _read_csv(self) -> list:
        with open(self._csv_path(), newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f, delimiter=";"))

    def _register_routes(self) -> None:
        @self.cmd.register("/upload", methods=["POST"])
        def upload():
            uploaded = request.files.get("file")
            if uploaded is None:
                return jsonify({"error": "no file provided"}), 400
            uploaded.save(self._csv_path())
            return jsonify({"status": "ok"})

        @self.cmd.register("/start", methods=["GET"])
        def start_route():
            try:
                rows = self._read_csv()
            except OSError:
                return jsonify({"error": "no CSV uploaded"}), 400

            connection = self._get_conn()
            if connection is None:
                return jsonify({"error": "not connected to router"}), 503

            # rate/duration are optional: omitted, this is the original one-pass-through-the-CSV
            # functional-test behavior at the legacy fixed 20ms pacing. Given, the send loop
            # instead cycles the CSV rows (wrapping back to row 0) at 1/rate intervals until
            # duration elapses - used by stress_run.sh, not by the functional run_test.sh.
            rate = request.args.get("rate", type=float)
            duration = request.args.get("duration", type=float)
            # Real traffic sent at the same rate for warmup_s seconds before the measured clock
            # starts - primes the same live connection/TLS session/thread pools the measured run
            # will use (a throwaway separate run would just tear all of that back down), so the
            # cold-start cost (TLS handshake, connection-pool fill, JIT warmup on router_java)
            # lands in the discarded warmup window instead of the first measured bucket.
            warmup_s = request.args.get("warmup_s", default=0.0, type=float)

            with self.pending_lock:
                self.pending.clear()
            self.send_times.clear()
            with self.results_lock:
                self.results.clear()
            self.latencies.clear()
            self.latency_records.clear()
            with self.advice_lock:
                self.advice_pending.clear()
                self.advice_send_queue.clear()
                for key in self.advice_counts:
                    self.advice_counts[key] = 0
            self._advice_slot_counter = 0
            self._set_advice_gauge()
            # monotonic, not wall-clock: a mid-run NTP/hv_utils clock resync (observed on this
            # WSL2 host) would otherwise show up as a bogus multi-minute latency spike on
            # whichever requests were in flight at that moment.
            self.run_start_time = time.monotonic()
            self.run_end_time = None
            self.run_sent = 0

            threading.Thread(
                target=self._run_with_warmup, args=(connection, rows, rate, duration, warmup_s), daemon=True
            ).start()
            return jsonify({"rows": len(rows)})

        @self.cmd.register("/probe_connection", methods=["GET"])
        def probe_connection():
            """Actively confirms the router connection is live, rather than trusting the
            connected-flag /stats already reports - that flag only flips to False once something
            notices the connection is dead (see _write_frame's disc_evt trigger), so it can lag
            behind reality for as long as nothing happens to write on it. Reuses _write_frame's
            own path (a harmless 0800, same as _keepalive_loop's periodic ping) rather than adding
            a second write path - a failed write here now tears the connection down for real
            (disc_evt), so a caller that gets connected: false and retries shortly after will see
            _client_connect_loop's/_server_accept_loop's fresh replacement instead of the same
            stale one."""
            connection = self._get_conn()
            if connection is None:
                return jsonify({"connected": False})
            return jsonify({"connected": self._write_frame(connection, build_0800(self.spec))})

        @self.cmd.register("/results", methods=["GET"])
        def results_route():
            with self.results_lock:
                return jsonify(list(self.results))

        @self.cmd.register("/stress_stats", methods=["GET"])
        def stress_stats_route():
            with self.results_lock:
                received = len(self.results)
            sent = self.run_sent
            with self.advice_lock:
                advice_counts = dict(self.advice_counts)
            end_time = self.run_end_time if self.run_end_time is not None else time.monotonic()
            elapsed = (end_time - self.run_start_time) if self.run_start_time else 0.0
            samples = sorted(self.latencies)

            def percentile(p):
                if not samples:
                    return None
                idx = min(len(samples) - 1, int(round(p / 100.0 * (len(samples) - 1))))
                return round(samples[idx] * 1000, 2)

            return jsonify(
                {
                    "sent": sent,
                    "received": received,
                    "errors": max(0, sent - received),
                    "elapsed_s": round(elapsed, 2),
                    "achieved_tps": round(sent / elapsed, 2) if elapsed > 0 else 0,
                    "p50_ms": percentile(50),
                    "p90_ms": percentile(90),
                    "p95_ms": percentile(95),
                    "p99_ms": percentile(99),
                    "max_ms": round(samples[-1] * 1000, 2) if samples else None,
                    "advice_0120_sent": advice_counts["0120_sent"],
                    "advice_0120_acked": advice_counts["0120_acked"],
                    "advice_0420_sent": advice_counts["0420_sent"],
                    "advice_0420_acked": advice_counts["0420_acked"],
                }
            )

        @self.cmd.register("/slow_responses", methods=["GET"])
        def slow_responses_route():
            n = request.args.get("n", default=10, type=int)
            slowest = sorted(self.latency_records, key=lambda r: r[1], reverse=True)[:n]
            return jsonify(
                [
                    {"sent_offset_s": round(offset, 3), "latency_ms": round(latency * 1000, 2)}
                    for offset, latency in slowest
                ]
            )

        @self.cmd.register("/latency_buckets", methods=["GET"])
        def latency_buckets_route():
            # Groups completed round trips by time-since-run-start into fixed windows, so a
            # smooth ramp (queueing backlog building up because service rate is a hair below
            # arrival rate) can be told apart from scattered spikes (a GC-pause fingerprint) -
            # a top-N-slowest list alone can't distinguish those two shapes.
            bucket_s = request.args.get("bucket_s", default=30.0, type=float)
            buckets = {}
            for offset, latency in self.latency_records:
                idx = int(offset // bucket_s)
                buckets.setdefault(idx, []).append(latency)

            result = []
            for idx in sorted(buckets):
                samples = sorted(buckets[idx])
                mid = len(samples) // 2
                p50 = samples[mid] if len(samples) % 2 else (samples[mid - 1] + samples[mid]) / 2
                result.append(
                    {
                        "bucket_start_s": round(idx * bucket_s, 1),
                        "count": len(samples),
                        "p50_ms": round(p50 * 1000, 2),
                        "max_ms": round(samples[-1] * 1000, 2),
                    }
                )
            return jsonify(result)

    def _get_conn(self):
        with self._conn_lock:
            return self._current

    def _write_frame(self, connection, encoded: bytes) -> bool:
        """Shared by every writer (_send_loop, _keepalive_loop, the advice loops below): the
        staleness check + _write_lock + OSError handling every one of them needs. Returns False
        instead of raising - a stale/dead connection or write failure is routine here (a chaos
        kill, a reconnect race - see _send_loop's own comment on why the staleness check
        matters), not something callers should treat as exceptional.

        A genuine write failure also sets this connection's disc_evt (if it's still the active
        one) instead of just reporting False to this one caller - otherwise reconnection depends
        entirely on _receive_loop's read side noticing independently, which can lag arbitrarily
        far behind (or never happen at all on a half-open/blackholed socket) while every writer
        - including _keepalive_loop, whose own failed write used to just silently give up - stays
        quiet about it. Same "anticipate, don't discover by failing" principle as the crypto-client
        generation/idle-timeout checks."""
        try:
            with self._write_lock:
                if connection is not self._get_conn():
                    return False
                write_message(connection.sock, encoded, self.framing)
            self.stats.record_sent()
            return True
        except OSError:
            with self._conn_lock:
                if self._current is connection:
                    connection.disc_evt.set()
            return False

    def _run_with_warmup(self, connection, rows, rate, duration, warmup_s) -> None:
        if warmup_s:
            self._warmup_active = True
            self._send_loop(connection, rows, rate, warmup_s)
            # Wait for in-flight warmup responses to actually land before clearing `pending`,
            # rather than guessing a fixed grace window - a slow backend (e.g. router_java's
            # per-thread crypto-client warmup: up to 16 dispatcher threads each doing a real TLS
            # handshake to crypto_host, serialized through one gate) can leave far more than a
            # couple seconds of warmup traffic outstanding. Clearing `pending` while those
            # responses are still in flight makes them arrive as unmatched STANs once the
            # measured phase starts - logged as "no pending request" and counted as errors
            # instead of being silently absorbed by the warmup they belong to. Capped so a
            # response that's never coming (dead connection, breaker stuck open) can't hang the
            # run forever.
            drain_deadline = time.monotonic() + max(warmup_s, 30.0)
            while time.monotonic() < drain_deadline:
                with self.pending_lock:
                    if not self.pending:
                        break
                time.sleep(0.1)
            self._warmup_active = False

        with self.pending_lock:
            self.pending.clear()
        self.send_times.clear()
        with self.results_lock:
            self.results.clear()
        self.latencies.clear()
        self.latency_records.clear()
        with self.advice_lock:
            self.advice_pending.clear()
            self.advice_send_queue.clear()
            for key in self.advice_counts:
                self.advice_counts[key] = 0
        self._advice_slot_counter = 0
        self._set_advice_gauge()
        self.run_start_time = time.monotonic()
        self.run_end_time = None
        self.run_sent = 0
        self._send_loop(connection, rows, rate, duration)

    def _send_loop(self, connection, rows, rate=None, duration=None) -> None:
        interval = (1.0 / rate) if rate else 0.02
        deadline = (time.monotonic() + duration) if duration else None
        # No duration: legacy one-pass-through-the-CSV functional-test behavior. With a
        # duration: cycle the (usually tiny) CSV rows to sustain load for the requested window -
        # used by stress_run.sh.
        row_iter = iter(rows)
        while not self.stop_event.is_set():
            row = next(row_iter, None)
            if row is None:
                if deadline is None:
                    break
                row_iter = iter(rows)
                row = next(row_iter, None)
                if row is None:
                    break
            if deadline is not None and time.monotonic() >= deadline:
                break

            stan = self._next_stan()
            # Column names are ISO 8583 field numbers; non-matching columns (e.g. expected_39)
            # are silently ignored. Field 11 (STAN) is always overwritten by the sender.
            msg = {k: v for k, v in row.items() if k in self.spec and k not in ("t", "p", "1")}
            msg["t"] = "0100"
            msg["11"] = stan

            with self.pending_lock:
                self.pending[stan] = row
            self.send_times[stan] = time.monotonic()

            # connection can go stale mid-batch: a chaos-style kill/reconnect between rows closes
            # this exact connection and _client_connect_loop/_server_accept_loop hands out a brand
            # new one, whose socket is on Linux very likely to reuse the just-freed fd number.
            # _write_frame's staleness check (against the same _write_lock _run_connection's
            # close() uses) is what prevents a write here from landing on someone else's brand new
            # connection.
            encoded, _ = iso8583.encode(msg, self.spec)
            if not self._write_frame(connection, bytes(encoded)):
                break
            self.run_sent += 1

            # briefs/resilience_v2.md advice_reversal throttle: one queued advice/reversal
            # dispatch for every _advice_ratio 0100 sends, interleaved right here rather than let
            # the advice loops fire independently - see __init__ for why.
            if self._advice_ratio:
                self._advice_slot_counter += 1
                if self._advice_slot_counter >= self._advice_ratio:
                    self._advice_slot_counter = 0
                    stan = None
                    with self.advice_lock:
                        if self.advice_send_queue:
                            stan = self.advice_send_queue.popleft()
                    if stan is not None:
                        with self.advice_lock:
                            entry = self.advice_pending.get(stan)
                        if entry is not None:
                            self._write_advice_entry(connection, stan, entry)

            time.sleep(interval)
        # Marks when active sending stopped, distinct from "now" - /stress_stats is queried
        # after a trailing grace window (letting in-flight responses land), and achieved_tps
        # must reflect the actual send window, not that grace window too.
        self.run_end_time = time.monotonic()

        # The throttle queue only drains on 0100 sends (above) - once those stop, anything still
        # queued has no way to ever get a slot. It gets silently cleared like the rest of
        # advice_pending on the next /start (briefs/resilience_v2.md: "just log how many are on
        # queue" - not drain them, that's this run's own backlog and the next stage starts fresh
        # same as advice_pending always has), so log it now while it's still known.
        if self._advice_ratio:
            with self.advice_lock:
                queued_counts = {"0120": 0, "0420": 0}
                for stan in self.advice_send_queue:
                    entry = self.advice_pending.get(stan)
                    if entry is not None:
                        queued_counts[entry["mti"]] = queued_counts.get(entry["mti"], 0) + 1
            logger.info(
                "run ended: %d 0120 + %d 0420 advice/reversal message(s) still queued for a throttle slot",
                queued_counts["0120"], queued_counts["0420"],
            )

    def _receive_loop(self, connection) -> None:
        while not connection.disc_evt.is_set():
            try:
                data = read_message(connection.sock, self.framing)
            except ConnectionError:
                connection.disc_evt.set()
                break

            try:
                resp, _ = iso8583.decode(data, self.spec)
            except Exception:
                logger.exception("failed to decode router response")
                continue
            self.stats.record_recv()

            mti = resp.get("t")
            if mti == "0810":
                continue
            if mti not in _RESPONSE_MTIS:
                logger.warning("unexpected response MTI: %s", mti)
                continue

            stan = resp.get("11", "")
            with self.pending_lock:
                row = self.pending.pop(stan, None)
            if row is None:
                # Not an ordinary transaction response - might be the ack (0430/0130) for an
                # in-flight advice message instead, which lives in advice_pending, not pending.
                with self.advice_lock:
                    advice_entry = self.advice_pending.pop(stan, None)
                    if advice_entry is not None:
                        self.advice_counts[f"{advice_entry['mti']}_acked"] += 1
                if advice_entry is not None:
                    _throttled.log(
                        logging.INFO,
                        f"advice_ack:{advice_entry['mti']}",
                        "advice %s stan=%s pan=%s acknowledged (%s) after %d retr%s",
                        advice_entry["mti"], stan, advice_entry["pan"], mti,
                        advice_entry["retries_done"], "y" if advice_entry["retries_done"] == 1 else "ies",
                    )
                    self._set_advice_gauge()
                    continue
                _throttled.log(logging.WARNING, "no_pending_stan", "no pending request for STAN %s", stan)
                continue

            send_time = self.send_times.pop(stan, None)
            if self._warmup_active:
                continue  # warmup traffic: matched to keep pending/receive clean, not measured

            if send_time is not None and len(self.latencies) < self._MAX_LATENCY_SAMPLES:
                recv_time = time.monotonic()
                latency = recv_time - send_time
                self.latencies.append(latency)
                sent_offset = (send_time - self.run_start_time) if self.run_start_time else 0.0
                self.latency_records.append((sent_offset, latency))

            merged = dict(row)
            for k, v in resp.items():
                merged[f"resp_{k}"] = v
            with self.results_lock:
                self.results.append(merged)

    def _keepalive_loop(self, connection) -> None:
        while not connection.disc_evt.is_set() and not self.stop_event.is_set():
            if not self._write_frame(connection, build_0800(self.spec)):
                return
            # interruptible wait for the rest of the interval
            elapsed = 0.0
            while elapsed < self.ping_0800_seconds:
                if connection.disc_evt.is_set() or self.stop_event.is_set():
                    return
                time.sleep(min(1.0, self.ping_0800_seconds - elapsed))
                elapsed += 1.0

    def _stip_decision(self, row: dict) -> str:
        """The STIP call upstream_host makes on the cardholder's behalf when downstream never
        answered in time (briefs/resilience_v2.md: "smaller amounts will be approved"). No real
        risk engine here - this is a resilience-test simulator, not a STIP implementation - always
        approves. Its own method so a scenario can override this decision without touching the
        timeout/retry machinery around it."""
        return "00"

    def _set_advice_gauge(self) -> None:
        with self.advice_lock:
            self.stats.set_gauge("advice_pending_count", len(self.advice_pending))

    def _write_advice_entry(self, connection, stan: str, entry: dict) -> None:
        """Writes one advice/reversal message - initial send or a resend - to the wire and
        updates its bookkeeping. The single dispatch path used whether the send happens
        immediately (throttling off, or no live 0100 stream to throttle against - see
        _dispatch_or_queue) or via _send_loop's throttle slot once one opens."""
        self._write_frame(connection, entry["encoded"])
        with self.advice_lock:
            e = self.advice_pending.get(stan)
            if e is None:
                return
            was_initial = not e["dispatched"]
            e["dispatched"] = True
            e["queued"] = False
            if was_initial:
                retries_done = 0
            else:
                # First resend (if no ack) fires advice_timeout_seconds * advice_backoff_multiplier
                # after the initial send; each subsequent resend multiplies that interval again -
                # briefs/resilience_v2.md's own worked example: multiplier 15 gives resend waits of
                # 15s, 225s, 3375s, ... after the initial send at t=advice_timeout_seconds.
                e["retries_done"] += 1
                e["interval"] *= self.advice_backoff_multiplier
                retries_done = e["retries_done"]
            e["next_retry_at"] = time.monotonic() + e["interval"]
            mti = e["mti"]
            pan = e["pan"]
            self.advice_counts[f"{mti}_sent"] += 1
        if was_initial:
            _throttled.log(
                logging.INFO,
                f"advice_sent:{mti}",
                "advice: sent %s stan=%s pan=%s (initial send, up to %d retries)",
                mti, stan, pan, self.advice_max_retries,
            )
        else:
            logger.info(
                "advice: retried %s stan=%s pan=%s (retry %d/%d)",
                mti, stan, pan, retries_done, self.advice_max_retries,
            )

    def _dispatch_or_queue(self, connection, stan: str, entry: dict) -> None:
        """Sends immediately unless advice_reversal_percentage throttling is on for a currently
        live 0100 stream, in which case this just marks the entry queued - _send_loop's own
        interleave logic is what actually pops it and calls _write_advice_entry once its slot
        comes up."""
        if self._advice_ratio and self.run_end_time is None and self.run_start_time is not None:
            with self.advice_lock:
                e = self.advice_pending.get(stan)
                if e is None:
                    return
                e["queued"] = True
                self.advice_send_queue.append(stan)
            return
        self._write_advice_entry(connection, stan, entry)

    def _start_advice(self, connection, mti: str, row: dict, decision: str = None) -> None:
        """Builds and registers one advice message (0420 or 0120) for a 0100 that timed out, then
        dispatches or throttle-queues it (see _dispatch_or_queue). Gets its own fresh STAN - not
        the original 0100's - since it's a genuinely new message needing its own request/response
        pairing on the wire; row's other fields (PAN, amount, ...) carry over unchanged, matching
        how downstream_host's existing 0120/0420 handling just echoes them back with the MTI (and,
        for 0120, the decision in field 39) changed."""
        stan = self._next_stan()
        msg = {k: v for k, v in row.items() if k in self.spec and k not in ("t", "p", "1")}
        msg["t"] = mti
        msg["11"] = stan
        if decision is not None:
            msg["39"] = decision
        encoded, _ = iso8583.encode(msg, self.spec)

        interval = self.advice_timeout_seconds * self.advice_backoff_multiplier
        entry = {
            "mti": mti,
            "ack_mti": _ADVICE_ACK_MTI[mti],
            "encoded": bytes(encoded),
            "pan": row.get("2", ""),
            "retries_done": 0,
            "interval": interval,
            "next_retry_at": time.monotonic() + interval,
            "dispatched": False,
            "queued": False,
        }
        with self.advice_lock:
            self.advice_pending[stan] = entry
        self._set_advice_gauge()
        self._dispatch_or_queue(connection, stan, entry)

    def _advice_timeout_loop(self, connection) -> None:
        """Watches `pending` for 0100s that never got a matching 0110 within
        advice_timeout_seconds - briefs/resilience_v2.md: real-world ISO 8583 doesn't wait
        forever, it moves on to the next authorization. Fires both a 0420 (reversal) and a 0120
        (STIP advice) independently for each one - see _start_advice - rather than picking one;
        the two mean different things (unconditional "forget it" vs. "here's the decision I made
        for the cardholder") and both apply on every timeout per this round's design."""
        poll_interval = min(0.2, self.advice_timeout_seconds / 5)
        while not connection.disc_evt.is_set() and not self.stop_event.is_set():
            now = time.monotonic()
            timed_out = []
            with self.pending_lock:
                for stan, sent_at in list(self.send_times.items()):
                    if now - sent_at >= self.advice_timeout_seconds and stan in self.pending:
                        row = self.pending.pop(stan)
                        self.send_times.pop(stan, None)
                        timed_out.append((stan, row))
            for stan, row in timed_out:
                _throttled.log(
                    logging.WARNING,
                    "0100_timeout",
                    "0100 timed out waiting for 0110 (stan=%s, pan=%s) after %.1fs - sending 0420+0120",
                    stan, row.get("2", ""), self.advice_timeout_seconds,
                )
                self._start_advice(connection, "0420", row)
                self._start_advice(connection, "0120", row, decision=self._stip_decision(row))
            time.sleep(poll_interval)

    def _log_advice_error(self, stan: str, entry: dict) -> None:
        """Store-and-forward give-up: after advice_max_retries resends with no ack, log it as a
        genuine error rather than silently dropping the entry - semicolon/utf-8-sig, matching
        every other CSV this repo writes (see feedback_csv_encoding)."""
        path = self.error_csv_path
        is_new = not os.path.exists(path)
        with open(path, "a", encoding="utf-8-sig" if is_new else "utf-8", newline="") as f:
            if is_new:
                f.write("timestamp;mti;router_stan;pan;retries;reason\n")
            ts = datetime.now().astimezone().isoformat(timespec="seconds")
            f.write(f"{ts};{entry['mti']};{stan};{entry['pan']};{entry['retries_done']};no_ack_after_max_retries\n")
        logger.error(
            "advice %s stan=%s pan=%s exhausted %d retries with no ack - logged to %s",
            entry["mti"], stan, entry["pan"], entry["retries_done"], path,
        )

    def _advice_retry_loop(self, connection) -> None:
        while not connection.disc_evt.is_set() and not self.stop_event.is_set():
            now = time.monotonic()
            due = []
            exhausted = []
            with self.advice_lock:
                for stan, entry in list(self.advice_pending.items()):
                    if entry["queued"]:
                        continue  # already waiting for a throttle slot - not due for another action
                    if now < entry["next_retry_at"]:
                        continue
                    if entry["retries_done"] >= self.advice_max_retries:
                        exhausted.append((stan, entry))
                        del self.advice_pending[stan]
                    else:
                        due.append((stan, entry))
            for stan, entry in exhausted:
                self._log_advice_error(stan, entry)
            for stan, entry in due:
                self._dispatch_or_queue(connection, stan, entry)
            if exhausted or due:
                self._set_advice_gauge()
            time.sleep(0.2)

    def _run_connection(self, sock) -> None:
        connection = _Connection(sock)
        with self._conn_lock:
            self._current = connection
        self.stats.set_connection("router", True)
        logger.info("connection established with router at %s", sock.getpeername())

        recv_thread = threading.Thread(target=self._receive_loop, args=(connection,), daemon=True)
        recv_thread.start()
        keepalive_thread = threading.Thread(target=self._keepalive_loop, args=(connection,), daemon=True)
        keepalive_thread.start()
        advice_timeout_thread = threading.Thread(
            target=self._advice_timeout_loop, args=(connection,), daemon=True
        )
        advice_timeout_thread.start()
        advice_retry_thread = threading.Thread(
            target=self._advice_retry_loop, args=(connection,), daemon=True
        )
        advice_retry_thread.start()

        connection.disc_evt.wait()

        with self._conn_lock:
            if self._current is connection:
                self._current = None
        self.stats.set_connection("router", False)
        logger.info("connection to router lost")
        # Closing under _write_lock, with shutdown() first, closes two races at once: (1) a
        # concurrent _send_loop/_keepalive_loop write that already passed its "is this still the
        # live conn" check can't have this socket - and its fd number - pulled out from under it
        # mid-write, since close() now waits for that write to finish; (2) shutdown() forces
        # _receive_loop's blocked read on this exact socket to return promptly instead of
        # potentially staying stuck for a long time (see router_py's DownstreamConnection.close()
        # and RouterSession._teardown() for the same fix on the router side of this same link).
        with self._write_lock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        recv_thread.join(timeout=2)
        keepalive_thread.join(timeout=2)
        advice_timeout_thread.join(timeout=2)
        advice_retry_thread.join(timeout=2)

    def _client_connect_loop(self) -> None:
        router_cfg = self.cfg["router"]
        retry_seconds = self.cfg.get("retry_seconds", 5)
        while not self.stop_event.is_set():
            try:
                # This timeout stays set on the socket (not just for the raw connect - see
                # settimeout(None) below) through wrap_client_socket's TLS handshake too, so it
                # doubles as the handshake's deadline. router_java's Dispatcher.start() now blocks
                # until every worker/response-worker thread finishes its own crypto_host warmup
                # call before its upstream socket starts accept()ing (see Dispatcher.java) -
                # worst case ~3.5s/thread * 16 threads = ~56s before a connecting client's TLS
                # handshake even begins being serviced. 60s covers that with a little headroom;
                # the old 5s reliably lost this race once that startup blocking landed (TCP
                # connect succeeds into the accept backlog, but the handshake read then times out
                # before router_java's delayed accept() gets to it, and the client backs off and
                # retries into the same losing race next attempt).
                sock = socket.create_connection((router_cfg["host"], router_cfg["port"]), timeout=60)
                sock = wrap_client_socket(
                    sock,
                    ssl_active=self.cfg.get("ssl_active", False),
                    certfile=self.cfg.get("certfile"),
                    keyfile=self.cfg.get("keyfile"),
                    cafile=self.cfg.get("cafile"),
                    server_hostname=router_cfg["host"],
                )
                sock.settimeout(None)  # switch to blocking; timeout above covered connect+handshake only
            except OSError:
                self.stop_event.wait(retry_seconds)
                continue
            self._run_connection(sock)

    def _server_accept_loop(self) -> None:
        router_cfg = self.cfg["router"]
        self._listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen_sock.bind(("0.0.0.0", router_cfg["port"]))
        self._listen_sock.listen(5)
        self._listen_sock.settimeout(1.0)

        while not self.stop_event.is_set():
            try:
                conn, _addr = self._listen_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if self.cfg.get("ssl_active"):
                conn = wrap_server_socket(
                    conn,
                    ssl_active=True,
                    certfile=self.cfg["certfile"],
                    keyfile=self.cfg["keyfile"],
                    cafile=self.cfg.get("cafile"),
                )
            self._run_connection(conn)

    def start(self) -> None:
        self.cmd.start()
        router_cfg = self.cfg["router"]
        if self.mode == "server":
            logger.info("upstream host listening on port %d", router_cfg["port"])
            threading.Thread(target=self._server_accept_loop, daemon=True).start()
        else:
            logger.info("upstream host connecting to %s:%d", router_cfg["host"], router_cfg["port"])
            threading.Thread(target=self._client_connect_loop, daemon=True).start()

    def run_forever(self) -> None:
        self.start()
        self.stop_event.wait()
        if self._listen_sock is not None:
            try:
                self._listen_sock.close()
            except OSError:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--router-host")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.router_host:
        cfg["router"]["host"] = args.router_host
    configure_logging(level=logging.INFO)

    sim = UpstreamHostSim(cfg)
    sim.run_forever()
