import logging
import threading

import iso8583
import iso8583.specs

from router.crypto_client import CryptoClient
from router.dispatcher import Dispatcher, RoutedMessage
from router.downstream import DownstreamConnection
from router.upstream import (
    UpstreamServer, UpstreamClient,
    read_upstream, write_upstream,
)
from shared.ims_connect import build_frame, build_frame
from shared.iso_utils import build_0810, hex_dump

logger = logging.getLogger(__name__)


class _OrEvent:
    def __init__(self, *events):
        self._events = events

    def is_set(self) -> bool:
        return any(e.is_set() for e in self._events)


class RouterSession:
    def __init__(self, cfg, downstream, crypto_client, dispatcher, stats, stop_event, reconnect_event):
        self._cfg = cfg
        self._downstream = downstream
        self._crypto = crypto_client
        self._dispatcher = dispatcher
        self._stats = stats
        self._stop_event = stop_event
        self._reconnect_event = reconnect_event
        self._spec = None
        self._upstream_ref = None
        self._up_ref_lock = threading.Lock()

    @classmethod
    def connect(cls, cfg, stats, stop_event, srv_sock, spec) -> "RouterSession":
        downstream = DownstreamConnection.connect(cfg.downstream)
        stats.set_connection("downstream", True)

        reconnect_event = threading.Event()
        crypto_client = CryptoClient(
            cfg.crypto,
            breaker_threshold=cfg.crypto_breaker_threshold,
            breaker_cooldown_seconds=cfg.crypto_breaker_cooldown_seconds,
        )
        dispatcher = Dispatcher(cfg, downstream, crypto_client, spec, stats, reconnect_event)

        session = cls(cfg, downstream, crypto_client, dispatcher, stats, stop_event, reconnect_event)
        session._spec = spec
        return session

    def run_until_disconnect(self, srv_sock=None) -> None:
        self._dispatcher.start()

        ds_thread = threading.Thread(target=self._downstream_receiver, daemon=True, name="ds-receiver")
        ds_thread.start()

        if self._cfg.upstream.mode == "server":
            up_thread = threading.Thread(
                target=self._server_upstream_loop, args=(srv_sock,), daemon=True, name="up-server"
            )
        else:
            up_thread = threading.Thread(
                target=self._client_upstream_loop, daemon=True, name="up-client"
            )
        up_thread.start()

        while not self._stop_event.is_set() and not self._reconnect_event.is_set():
            self._stop_event.wait(1.0)

        self._teardown(up_thread)
        ds_thread.join(timeout=5)

    def _server_upstream_loop(self, srv_sock):
        or_event = _OrEvent(self._stop_event, self._reconnect_event)
        while not or_event.is_set():
            result = srv_sock.accept(or_event)
            if result is None:
                break
            conn, addr, lock = result
            self._handle_upstream(conn, addr, lock)

    def _client_upstream_loop(self):
        client = UpstreamClient(self._cfg.upstream)
        or_event = _OrEvent(self._stop_event, self._reconnect_event)
        result = client.connect(or_event)
        if result is None:
            return
        conn, addr, lock = result
        self._handle_upstream(conn, addr, lock)

    def _handle_upstream(self, conn, addr, write_lock):
        self._stats.set_connection("upstream", True)
        with self._up_ref_lock:
            self._upstream_ref = (conn, write_lock)
        try:
            while True:
                try:
                    data = read_upstream(conn, self._cfg.upstream)
                except ConnectionError as e:
                    logger.warning("upstream %s disconnected: %s", addr, e)
                    self._reconnect_event.set()
                    break

                try:
                    req, _ = iso8583.decode(data, self._spec)
                except Exception as e:
                    logger.warning("upstream decode error: %s", e)
                    continue

                self._stats.record_recv()
                mti = req.get("t")

                if mti in ("0100", "0120", "0420"):
                    self._dispatcher.submit(RoutedMessage(req=req, up_conn=conn, up_write_lock=write_lock, up_addr=addr))
                elif mti == "0800":
                    try:
                        self._forward_0800(req)
                    except OSError as e:
                        logger.warning("forward 0800 error: %s", e)
                else:
                    logger.warning("upstream sent unhandled mti=%s", mti)
        finally:
            self._stats.set_connection("upstream", False)
            with self._up_ref_lock:
                if self._upstream_ref and self._upstream_ref[0] is conn:
                    self._upstream_ref = None

    def _forward_0800(self, req):
        encoded, _ = iso8583.encode(req, self._spec)
        frame = build_frame(
            0x00,
            self._cfg.downstream.irm_id,
            self._cfg.downstream.client_id,
            req["t"],
            encoded,
        )
        self._downstream.send(frame)
        self._stats.record_sent()

    def _downstream_receiver(self):
        while True:
            try:
                data = self._downstream.recv()
            except ConnectionError as e:
                logger.warning("downstream disconnected: %s", e)
                self._stats.set_connection("downstream", False)
                self._reconnect_event.set()
                break

            # Skip ping responses
            if data[:4] == "PING".encode("cp500"):
                continue

            try:
                resp, _ = iso8583.decode(data, self._spec)
            except Exception as e:
                logger.warning("downstream decode error: %s", e)
                continue

            self._stats.record_recv()

            try:
                if resp.get("t") == "0810":
                    self._forward_0810(resp)
                else:
                    self._dispatcher.handle_response(resp)
            except Exception:
                logger.exception("unexpected error dispatching downstream message mti=%s", resp.get("t"))

    def _forward_0810(self, resp):
        with self._up_ref_lock:
            ref = self._upstream_ref

        if ref is None:
            logger.warning("0810 received but no upstream connected")
            return

        conn, write_lock = ref
        try:
            encoded, _ = iso8583.encode(resp, self._spec)
            frame = self._dispatcher._encode_upstream_frame(encoded)
            with write_lock:
                conn.sendall(frame)
        except OSError as e:
            logger.warning("forward 0810 write error: %s", e)

    def _teardown(self, up_thread):
        self._dispatcher.drain_and_stop()

        with self._up_ref_lock:
            ref = self._upstream_ref
            self._upstream_ref = None

        if ref is not None:
            conn, _ = ref
            try:
                conn.close()
            except OSError:
                pass

        self._downstream.close()
        up_thread.join(timeout=5)
