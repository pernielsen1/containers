import argparse
import logging
import os
import random
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from router.config import RouterConfig
from router.session import RouterSession
from router.upstream import UpstreamServer
from shared.command_server import CommandServer
from shared.iso_utils import load_spec
from shared.stats import Stats

logger = logging.getLogger(__name__)


def load_config(path=None):
    if path is None:
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, "router_1", "config.json")
    config_base = os.path.dirname(os.path.abspath(path))
    return RouterConfig.from_file(path), config_base


def run(cfg=None, stop_event=None, stats=None, _config_base=None):
    if stop_event is None:
        stop_event = threading.Event()
    if stats is None:
        stats = Stats(yellow_threshold_seconds=cfg.yellow_threshold_seconds)

    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    cmd = CommandServer(
        port=cfg.command_port,
        stats=stats,
        stop_event=stop_event,
        bind_host=cfg.command_bind_host,
        auth_token=cfg.command_auth_token,
    )

    current_session = [None]

    @cmd.register("/dispatcher/purge", methods=("POST",), protected=True)
    def dispatcher_purge():
        from flask import jsonify
        if current_session[0] is not None:
            result = current_session[0]._dispatcher.purge()
            return jsonify(result)
        return jsonify({"dropped_pending": 0, "dropped_queue": 0})

    cmd.start()

    spec = load_spec(cfg.iso_spec)

    srv_sock = None
    if cfg.upstream.mode == "server":
        srv_sock = UpstreamServer(cfg.upstream)

    while not stop_event.is_set():
        try:
            session = RouterSession.connect(cfg, stats, stop_event, srv_sock, spec)
            current_session[0] = session
        except OSError as e:
            logger.warning("connect failed: %s — retrying in %ds", e, cfg.reestablish_seconds)
            delay = cfg.reestablish_seconds + random.uniform(0, cfg.reconnect_jitter_seconds)
            stop_event.wait(delay)
            continue

        session.run_until_disconnect(srv_sock)
        current_session[0] = None

        if not stop_event.is_set():
            delay = cfg.reestablish_seconds + random.uniform(0, cfg.reconnect_jitter_seconds)
            logger.info("session ended — reconnecting in %.1fs", delay)
            stop_event.wait(delay)

    if srv_sock:
        srv_sock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    cfg, config_base = load_config(args.config)
    run(cfg=cfg, _config_base=config_base)
