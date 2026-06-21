import argparse
import logging
import os
import random
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import jsonify

from router.config import RouterConfig
from router.session import RouterSession
from router.upstream import UpstreamServer
from shared.command_server import CommandServer
from shared.stats import Stats

logger = logging.getLogger(__name__)


def load_config(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "router_1", "config.json")
    cfg = RouterConfig.from_file(path)
    config_base = os.path.dirname(os.path.abspath(path))
    return cfg, config_base


def run(cfg=None, stop_event=None, stats=None, _config_base=None):
    if cfg is None:
        cfg, _config_base = load_config()
    if stop_event is None:
        stop_event = threading.Event()
    if stats is None:
        stats = Stats(yellow_threshold_seconds=cfg.yellow_threshold_seconds)

    logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger().setLevel(cfg.log_level)

    cmd = CommandServer(
        cfg.command_port, stats, stop_event, bind_host=cfg.command_bind_host, auth_token=cfg.command_auth_token
    )

    # Re-pointed at the new Dispatcher on each reconnect, since a fresh one is created per session.
    active_session = {"dispatcher": None}

    @cmd.register("/dispatcher/purge", methods=["POST"], protected=True)
    def purge_route():
        dispatcher = active_session["dispatcher"]
        if dispatcher is None:
            return jsonify({"error": "no active session"}), 503
        return jsonify(dispatcher.purge())

    cmd.start()

    srv_sock = None
    if cfg.upstream.mode == "server":
        srv_sock = UpstreamServer(cfg.upstream)

    try:
        while not stop_event.is_set():
            try:
                session = RouterSession.connect(cfg, stats, stop_event, srv_sock)
            except OSError:
                logger.warning("failed to establish downstream session, retrying", exc_info=True)
                stop_event.wait(cfg.reestablish_seconds + random.uniform(0, cfg.reconnect_jitter_seconds))
                continue

            active_session["dispatcher"] = session.dispatcher
            session.run_until_disconnect(srv_sock)
            active_session["dispatcher"] = None

            if not stop_event.is_set():
                # Jitter avoids multiple routers sharing a downstream/crypto host
                # reconnecting in lockstep.
                stop_event.wait(cfg.reestablish_seconds + random.uniform(0, cfg.reconnect_jitter_seconds))
    finally:
        if srv_sock is not None:
            srv_sock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    args = parser.parse_args()

    cfg, config_base = load_config(args.config)
    run(cfg=cfg, _config_base=config_base)
