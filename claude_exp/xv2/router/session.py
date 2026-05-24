"""RouterSession — one fully-connected session (upstream + downstream + dispatcher).

Owns threads and sockets for a single connected session.
Handles graceful teardown in correct order when any component disconnects.

C++ equivalent: RAII class; destructor joins threads and closes sockets.
std::atomic<bool> reconnect_flag shared across Dispatcher and receivers.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import iso8583

from shared.iso_utils import load_spec, hex_dump
from shared.stats import Stats
from .config import RouterConfig
from .crypto_client import CryptoClient
from .dispatcher import Dispatcher, RoutedMessage
from .downstream import DownstreamConnection
from .upstream import (
    UpstreamServer, UpstreamClient, UpstreamConn,
    read_upstream, write_upstream,
)

log = logging.getLogger(__name__)


class RouterSession:
    """One live session. Call run_until_disconnect(); it blocks until something breaks."""

    def __init__(
        self,
        cfg: RouterConfig,
        downstream: DownstreamConnection,
        dispatcher: Dispatcher,
        stats: Stats,
        stop_event: threading.Event,
        reconnect_event: threading.Event,
    ) -> None:
        self._cfg         = cfg
        self._downstream  = downstream
        self._dispatcher  = dispatcher
        self._stats       = stats
        self._stop        = stop_event
        self._reconnect   = reconnect_event
        self._spec        = load_spec(cfg.iso_spec)

        # current upstream connection (set by _handle_upstream)
        self._upstream_ref: dict = {"conn": None, "lock": None}
        self._up_ref_lock  = threading.Lock()

    # ── factory ───────────────────────────────────────────────────────────────

    @classmethod
    def connect(
        cls,
        cfg: RouterConfig,
        stats: Stats,
        stop_event: threading.Event,
        srv_sock: Optional[UpstreamServer],
    ) -> RouterSession:
        """Connect downstream and build a RouterSession. Raises OSError if unreachable."""
        reconnect_event = threading.Event()
        downstream = DownstreamConnection.connect(cfg.downstream)  # raises OSError if unreachable
        stats.set_connection("downstream", True)
        spec       = load_spec(cfg.iso_spec)
        crypto     = CryptoClient(cfg.crypto)
        dispatcher = Dispatcher(cfg, downstream, crypto, spec, stats, reconnect_event)
        return cls(cfg, downstream, dispatcher, stats, stop_event, reconnect_event)

    # ── main blocking call ─────────────────────────────────────────────────────

    def run_until_disconnect(self, srv_sock: Optional[UpstreamServer] = None) -> None:
        """Start all threads and block until a disconnect is detected.

        C++ equivalent: blocking method that returns when reconnect_flag is set;
        RAII destructors handle cleanup on scope exit.
        """
        self._dispatcher.start()

        # downstream receiver thread
        ds_thread = threading.Thread(
            target=self._downstream_receiver,
            name="ds-receiver",
            daemon=True,
        )
        ds_thread.start()

        # upstream connection thread (server or client mode)
        if self._cfg.upstream.mode == "client":
            up_thread = threading.Thread(
                target=self._client_upstream_loop,
                name="up-client",
                daemon=True,
            )
        else:
            up_thread = threading.Thread(
                target=self._server_upstream_loop,
                args=(srv_sock,),
                name="up-server",
                daemon=True,
            )
        up_thread.start()

        # wait for disconnect or stop
        while not self._reconnect.is_set() and not self._stop.is_set():
            self._stop.wait(timeout=1)

        self._teardown(up_thread)

    # ── upstream loops ─────────────────────────────────────────────────────────

    def _server_upstream_loop(self, srv_sock: UpstreamServer) -> None:
        """Accept one upstream connection at a time (server mode)."""
        conn_tuple = srv_sock.accept(self._stop)
        if conn_tuple:
            self._handle_upstream(*conn_tuple)

    def _client_upstream_loop(self) -> None:
        """Connect out to upstream (client mode)."""
        client = UpstreamClient(self._cfg.upstream)
        conn_tuple = client.connect(self._stop)
        if conn_tuple:
            self._handle_upstream(*conn_tuple)
            # disconnect already set reconnect_event

    def _handle_upstream(
        self,
        conn: object,
        addr: tuple,
        write_lock: object,
    ) -> None:
        """Read loop for one upstream connection. Feeds 0100 to Dispatcher, forwards 0800."""
        log.info("router: upstream connected %s", addr)
        with self._up_ref_lock:
            self._upstream_ref["conn"] = conn
            self._upstream_ref["lock"] = write_lock
        self._stats.set_connection("upstream", True)

        try:
            while not self._reconnect.is_set() and not self._stop.is_set():
                try:
                    data = read_upstream(conn, self._cfg.upstream)
                except ConnectionError:
                    log.info("router: upstream %s disconnected", addr)
                    self._reconnect.set()
                    return

                self._stats.record_recv()
                hex_dump(f"RECV upstream {addr}", data, log)
                try:
                    req, _ = iso8583.decode(data, spec=load_spec(self._cfg.iso_spec))
                except Exception as e:
                    log.warning("router: decode error from %s: %s", addr, e)
                    continue

                mti = req.get("t")
                if mti == "0100":
                    self._dispatcher.submit(
                        RoutedMessage(req=req, up_conn=conn,
                                      up_write_lock=write_lock, up_addr=addr)
                    )
                elif mti == "0800":
                    self._forward_0800(req, conn, write_lock, addr)
                else:
                    log.warning("router: unexpected MTI %s from %s", mti, addr)
        finally:
            self._stats.set_connection("upstream", False)
            with self._up_ref_lock:
                self._upstream_ref["conn"] = None
                self._upstream_ref["lock"] = None

    def _forward_0800(self, req: dict, up_conn, write_lock, addr) -> None:
        """Forward a keepalive ping from upstream to downstream."""
        try:
            encoded, _ = iso8583.encode(req, spec=load_spec(self._cfg.iso_spec))
            from shared import ims_connect
            frame = ims_connect.build_frame(
                0x00,
                self._cfg.downstream.irm_id,
                self._cfg.downstream.client_id,
                req["t"],
                encoded,
            )
            self._downstream.send(frame)
            log.debug("router: forwarded 0800 to downstream")
        except OSError as e:
            log.warning("router: failed to forward 0800: %s", e)
            self._reconnect.set()

    # ── downstream receiver ────────────────────────────────────────────────────

    def _downstream_receiver(self) -> None:
        """Read responses from downstream and dispatch to Dispatcher or upstream."""
        log.info("router: downstream receiver started")
        while not self._reconnect.is_set() and not self._stop.is_set():
            try:
                data = self._downstream.recv()
            except ConnectionError:
                log.info("router: downstream disconnected")
                self._stats.set_connection("downstream", False)
                self._reconnect.set()
                return

            self._stats.record_recv()
            hex_dump("RECV downstream", data, log)

            from shared import ims_connect
            if data[:4] == "PING".encode("cp500"):
                log.info("router: pipe-cleaner response: %s", data.hex())
                continue

            try:
                resp, _ = iso8583.decode(data, spec=load_spec(self._cfg.iso_spec))
            except Exception as e:
                log.warning("router: decode error from downstream: %s", e)
                continue

            mti = resp.get("t")
            if mti == "0810":
                self._forward_0810(resp)
            else:
                self._dispatcher.handle_response(resp)

    def _forward_0810(self, resp: dict) -> None:
        """Forward a keepalive response from downstream back to upstream."""
        with self._up_ref_lock:
            up_conn = self._upstream_ref["conn"]
            up_lock = self._upstream_ref["lock"]
        if up_conn is None:
            log.warning("router: received 0810 but no upstream connected")
            return
        try:
            encoded, _ = iso8583.encode(resp, spec=load_spec(self._cfg.iso_spec))
            with up_lock:
                write_upstream(up_conn, encoded, self._cfg.upstream)
            log.debug("router: forwarded 0810 to upstream")
        except Exception as e:
            log.warning("router: failed to forward 0810: %s", e)

    # ── teardown ──────────────────────────────────────────────────────────────

    def _teardown(self, up_thread: threading.Thread) -> None:
        """Drain workers, close sockets, join upstream thread.

        Order matters: workers must drain before downstream closes.
        C++ equivalent: explicit scope-ordered RAII or manual destructor order.
        """
        self._dispatcher.drain_and_stop()

        with self._up_ref_lock:
            up_conn = self._upstream_ref.get("conn")
        if up_conn:
            try:
                up_conn.close()
            except OSError:
                pass

        self._downstream.close()
        up_thread.join(timeout=5)
