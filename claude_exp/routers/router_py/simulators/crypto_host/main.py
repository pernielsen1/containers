import argparse
import base64
import json
import logging
import os
import random
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from flask import Flask, request  # noqa: E402

from shared.command_server import CommandServer  # noqa: E402
from shared.iso_utils import f47_decode, f47_encode  # noqa: E402
from shared.json_log import configure_logging  # noqa: E402
from shared.stats import Stats  # noqa: E402

logger = logging.getLogger(__name__)


def load_config(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    with open(path) as f:
        cfg = json.load(f)
    base_dir = os.path.dirname(os.path.abspath(path))
    cfg["pans_defined"] = os.path.normpath(os.path.join(base_dir, cfg["pans_defined"]))
    for key in ("certfile", "keyfile", "cafile"):
        if key in cfg and cfg[key]:
            cfg[key] = os.path.normpath(os.path.join(base_dir, cfg[key]))
    return cfg


class CryptoHostSim:
    """Stub crypto host: no OpenSSL, no PIN/ARQC/CVV2/AAV math - just reports whether the PAN
    is provisioned. Real cryptographic validation lives in routers/crypto_host/ (the shared
    container). Wire contract (Fortanix-shaped: POST /sys/v1/plugins/{plugin_id}, bearer auth,
    base64 PluginOutput response) matches that container and the Java/C++ stubs, so a router can
    point at either one via config alone."""

    def __init__(self, cfg):
        self.cfg = cfg
        with open(cfg["pans_defined"]) as f:
            self.pans = json.load(f)
        # Chaos hook (briefs/resilience_v2.md "build up a queue"): {pan: [operation, ...]}.
        # Matching (pan, operation) requests never get a response at all - not an HTTP error,
        # a real hang - to simulate a card whose crypto data makes validation itself get stuck
        # rather than fail fast. Empty by default; no real PAN in pans_defined.json is ever
        # listed here, so normal traffic is unaffected.
        self.no_response_pans = cfg.get("no_response_pans", {})
        # Second, PAN-independent chaos hook (briefs/resilience_v2.md's "OK let's make
        # resilience_soak.sh scripts" round): a flat percentage of validate_0110 (response-leg)
        # requests, any PAN, get the same no-response treatment - run_soak_resilience_light.sh's
        # --fail_percentage. Response leg only, not validate_0100 too - see the request-handler's
        # own comment on why. Kept as a plain 0-100 float rather than reusing no_response_pans'
        # PAN-keyed shape because the light soak scenario wants "some realistic slice of ordinary
        # traffic fails" (brief: "10% ... a very high number"), not "this one card never works" -
        # a soak run shouldn't need a bespoke bad-card CSV mix just to dial the failure rate.
        # CLI-overridable (see __main__) so a soak script can set it per run without editing
        # config.json; 0 by default, so normal traffic (including every other scenario/test in
        # this file) is unaffected unless a caller opts in.
        self.fail_percentage = float(cfg.get("fail_percentage", 0.0))

        self.stats = Stats(yellow_threshold_seconds=cfg.get("yellow_threshold_seconds"))
        self.stop_event = threading.Event()

        # Command/stats API on command_port; the plugin-execution API below is a separate
        # listener on `port` (this is what router/crypto_client.py's CryptoConfig.port dials).
        self.cmd = CommandServer(cfg["command_port"], self.stats, self.stop_event)

        self.app = Flask(__name__)
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        self._register_routes()

    def _validate(self, pan: str, f47_str: str) -> str:
        data = f47_decode(f47_str)
        data["response_code"] = "14" if pan not in self.pans else "00"
        return f47_encode(data)

    def _register_routes(self) -> None:
        plugin_id = self.cfg["plugin_id"]
        bearer_token = self.cfg["bearer_token"]

        @self.app.route(f"/sys/v1/plugins/{plugin_id}", methods=["POST"])
        def invoke_plugin():
            auth_header = request.headers.get("Authorization")
            if auth_header != f"Bearer {bearer_token}":
                return {"error": "unauthorized"}, 401

            self.stats.record_recv()
            body = request.json or {}
            operation = body.get("operation", "")
            router_stan = body.get("router_stan", "")
            pan = body.get("f2", "")
            if operation not in ("validate_0100", "validate_0110"):
                return {"error": f"unknown operation: {operation}"}, 400

            chaos_reason = None
            if operation in self.no_response_pans.get(pan, []):
                chaos_reason = "no_response_pans"
            elif (
                operation == "validate_0110"
                and self.fail_percentage > 0
                and random.random() * 100 < self.fail_percentage
            ):
                # Response leg (validate_0110) only, deliberately - the request leg
                # (validate_0100) blocks router/dispatcher.py's forwarding decision on
                # CryptoClient's full (slow, non-fire-and-forget) default timeout, so failing it
                # at any real percentage reproduces Round 6's queue-buildup collapse instead of
                # Round 7's "fire and forget, TPS still met" result the brief is actually asking
                # for here (brief itself frames it this way too - "crypto_host is Ok on the
                # request... fails on handling the response"). Confirmed by hitting exactly that
                # collapse (received stuck at 0, queues pinned at max) with an earlier version of
                # this hook that applied to both legs - see resilience.md's Round 9 write-up.
                chaos_reason = f"fail_percentage={self.fail_percentage}"
            if chaos_reason:
                logger.warning(
                    "chaos: simulating no response for pan=%s operation=%s router_stan=%s "
                    "reason=%s (request will just hang - caller's own timeout decides what "
                    "happens next)",
                    pan, operation, router_stan, chaos_reason, extra={"router_stan": router_stan},
                )
                # Bounded, not forever: the caller's own timeout (CryptoClient's 5s request-leg
                # / crypto_response_timeout_seconds response-leg default) always decides the
                # caller-visible outcome well before this fires - this bound only reclaims the
                # server-side thread/socket instead of leaking it permanently. Short (2s, not the
                # original 10s) on purpose: at sustained real-traffic volume a longer bound lets
                # stuck server threads/sockets pile up faster than they clear (measured directly:
                # 10s let ~100 concurrent stuck threads accumulate under 10 hangs/sec, which then
                # starved the dev server's own accept queue - see resilience.md).
                threading.Event().wait(timeout=2)
                return {"error": "chaos: no response"}, 504

            logger.debug("validate pan=%s router_stan=%s", pan, router_stan)
            result = self._validate(pan, body.get("f47", ""))
            envelope = json.dumps({"f47": result})
            b64 = base64.b64encode(envelope.encode("utf-8")).decode("ascii")
            self.stats.record_sent()
            return json.dumps(b64), 200, {"Content-Type": "application/json"}

    def start(self) -> None:
        self.cmd.start()
        logger.info("crypto host listening on port %d", self.cfg["port"])
        ssl_context = None
        if self.cfg.get("ssl_active"):
            ssl_context = (self.cfg["certfile"], self.cfg["keyfile"])
        threading.Thread(
            target=lambda: self.app.run(
                host="127.0.0.1",
                port=self.cfg["port"],
                use_reloader=False,
                ssl_context=ssl_context,
                # threaded=True: Flask's dev server defaults to handling one request at a
                # time. A chaos no_response_pans hang (above) would otherwise stall every
                # request - including unrelated PANs/operations - not just the targeted one.
                threaded=True,
            ),
            daemon=True,
        ).start()

    def run_forever(self) -> None:
        self.start()
        self.stop_event.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument(
        "--fail-percentage", type=float, default=None,
        help="Overrides config.json's fail_percentage - percent (0-100) of all requests, any "
             "PAN, that get no response at all. Used by run_soak_resilience_light.sh.",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.fail_percentage is not None:
        cfg["fail_percentage"] = args.fail_percentage
    configure_logging(level=logging.INFO)

    sim = CryptoHostSim(cfg)
    sim.run_forever()
