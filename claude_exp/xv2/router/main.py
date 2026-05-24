#!/usr/bin/env python3
"""Router entry point — argument parsing, command server, reconnect loop.

C++ equivalent: main() with identical while-loop;
std::atomic<bool> stop_flag set by SIGTERM handler.
"""
import argparse
import logging
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.stats import Stats
from shared.command_server import CommandServer
from shared.iso_utils import load_spec

from router.config import RouterConfig
from router.session import RouterSession
from router.upstream import UpstreamServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def load_config(path=None):
    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "router_1", "config.json")
    config_base = os.path.dirname(os.path.abspath(path))
    return RouterConfig.from_file(path), config_base


def run(cfg: RouterConfig = None, stop_event=None, stats=None, _config_base=None):
    if cfg is None:
        cfg, _config_base = load_config()
    if stop_event is None:
        stop_event = threading.Event()
    if stats is None:
        stats = Stats(yellow_threshold_seconds=cfg.yellow_threshold_seconds)

    logging.getLogger().setLevel(
        getattr(logging, cfg.log_level.upper(), logging.INFO)
    )

    cmd = CommandServer(cfg.command_port, stats, stop_event)
    cmd.start()

    # server-mode upstream socket lives outside the session loop
    srv_sock = None
    if cfg.upstream.mode == "server":
        srv_sock = UpstreamServer(cfg.upstream)
        log.info("router: upstream server on :%d  command on :%d",
                 cfg.upstream.port, cfg.command_port)
    else:
        log.info("router: upstream client → %s:%d  command on :%d",
                 cfg.upstream.host, cfg.upstream.port, cfg.command_port)

    try:
        while not stop_event.is_set():
            try:
                session = RouterSession.connect(cfg, stats, stop_event, srv_sock)
            except OSError as e:
                log.warning("router: downstream unavailable (%s), retrying in %ds",
                            e, cfg.reestablish_seconds)
                stop_event.wait(timeout=cfg.reestablish_seconds)
                continue

            session.run_until_disconnect(srv_sock)

            if stop_event.is_set():
                break

            log.info("router: session ended, reconnecting in %ds", cfg.reestablish_seconds)
            stop_event.wait(timeout=cfg.reestablish_seconds)
    finally:
        if srv_sock:
            srv_sock.close()
        log.info("router stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None, help="Path to config.json")
    args = parser.parse_args()
    cfg, config_base = load_config(args.config)
    run(cfg=cfg, _config_base=config_base)
