import logging
import threading

import iso8583

from router.crypto_client import CryptoClient
from router.dispatcher import Dispatcher, RoutedMessage
from router.downstream import DownstreamConnection
from router.upstream import UpstreamClient, read_upstream, write_upstream
from shared.iso_utils import load_spec
from shared.ims_connect import build_frame

logger = logging.getLogger(__name__)


class _OrEvent:
    """Duck-typed event exposing only is_set(), true if any wrapped event is set.

    UpstreamServer.accept()/UpstreamClient.connect() only ever call .is_set() on the
    event they're given, so this lets the upstream accept/connect loop wake up on
    either stop_event or reconnect_event without those APIs needing to know about both.
    """

    def __init__(self, *events):
        self._events = events

    def is_set(self) -> bool:
        return any(e.is_set() for e in self._events)


class RouterSession:
    """One live connection session. Owns ds-receiver thread and up-server/client thread."""

    def __init__(self, cfg, stats, stop_event, downstream, crypto, dispatcher, spec, reconnect_event):
        self.cfg = cfg
        self.stats = stats
        self.stop_event = stop_event
        self.downstream = downstream
        self.crypto = crypto
        self.dispatcher = dispatcher
        self.spec = spec
        self.reconnect_event = reconnect_event

        self.upstream_client = UpstreamClient(cfg.upstream) if cfg.upstream.mode == "client" else None

        self._upstream_ref = None
        self._up_ref_lock = threading.Lock()

    @classmethod
    def connect(cls, cfg, stats, stop_event, srv_sock=None) -> "RouterSession":
        downstream = DownstreamConnection.connect(cfg.downstream)  # raises OSError -> caller retries
        stats.set_connection("downstream", True)

        spec = load_spec(cfg.iso_spec)
        crypto = CryptoClient(
            cfg.crypto,
            breaker_threshold=cfg.crypto_breaker_threshold,
            breaker_cooldown_seconds=cfg.crypto_breaker_cooldown_seconds,
        )
        reconnect_event = threading.Event()
        dispatcher = Dispatcher(cfg, downstream, crypto, spec, stats, reconnect_event)

        return cls(cfg, stats, stop_event, downstream, crypto, dispatcher, spec, reconnect_event)

    def run_until_disconnect(self, srv_sock=None) -> None:
        self.dispatcher.start()

        ds_thread = threading.Thread(target=self._downstream_receiver, name="ds-receiver", daemon=True)
        ds_thread.start()

        if self.cfg.upstream.mode == "server":
            up_thread = threading.Thread(
                target=self._server_upstream_loop, args=(srv_sock,), name="up-server", daemon=True
            )
        else:
            up_thread = threading.Thread(target=self._client_upstream_loop, name="up-client", daemon=True)
        up_thread.start()

        while True:
            if self.stop_event.wait(1.0):
                break
            if self.reconnect_event.is_set():
                break

        self._teardown(up_thread)
        ds_thread.join(timeout=5)

    def _combined_event(self):
        return _OrEvent(self.stop_event, self.reconnect_event)

    def _server_upstream_loop(self, srv_sock):
        conn_info = srv_sock.accept(self._combined_event())
        if conn_info is None:
            return
        conn, addr, lock = conn_info
        self._handle_upstream(conn, addr, lock)

    def _client_upstream_loop(self):
        conn_info = self.upstream_client.connect(self._combined_event())
        if conn_info is None:
            return
        conn, addr, lock = conn_info
        self._handle_upstream(conn, addr, lock)

    def _handle_upstream(self, conn, addr, write_lock):
        self.stats.set_connection("upstream", True)
        with self._up_ref_lock:
            self._upstream_ref = (conn, write_lock)

        try:
            while True:
                try:
                    data = read_upstream(conn, self.cfg.upstream)
                except ConnectionError as e:
                    # Covers both a remote disconnect and a local close racing this
                    # blocked read during teardown — _recv_exact normalizes any OSError
                    # (e.g. EBADF) from the latter into ConnectionError too.
                    logger.warning("upstream connection lost: %s", e)
                    self.reconnect_event.set()
                    break

                try:
                    req, _ = iso8583.decode(data, self.spec)
                except Exception:
                    logger.exception("failed to decode upstream message")
                    continue
                self.stats.record_recv()

                mti = req.get("t")
                if mti in ("0100", "0120", "0420"):
                    self.dispatcher.submit(
                        RoutedMessage(req=req, up_conn=conn, up_write_lock=write_lock, up_addr=addr)
                    )
                elif mti == "0800":
                    self._forward_0800(req)
                else:
                    logger.warning("unexpected upstream MTI: %s", mti)
        finally:
            self.stats.set_connection("upstream", False)
            with self._up_ref_lock:
                self._upstream_ref = None

    def _forward_0800(self, req: dict) -> None:
        encoded, _ = iso8583.encode(req, self.spec)
        frame = build_frame(
            0x00, self.cfg.downstream.irm_id, self.cfg.downstream.client_id, mti="0800", data=bytes(encoded)
        )
        try:
            self.downstream.send(frame)
            self.stats.record_sent()
        except OSError:
            # downstream can be closed by session teardown out from under this write
            # (called from the up-server/up-client read thread); reconnect_event will
            # already be set by the thread that's tearing the session down.
            logger.warning("failed to forward 0800 keepalive to downstream")

    def _forward_0810(self, resp: dict) -> None:
        with self._up_ref_lock:
            ref = self._upstream_ref
        if ref is None:
            logger.warning("0810 received but no live upstream connection to forward to")
            return

        conn, write_lock = ref
        encoded, _ = iso8583.encode(resp, self.spec)
        try:
            with write_lock:
                write_upstream(conn, bytes(encoded), self.cfg.upstream)
            self.stats.record_sent()
            logger.debug("0810 forwarded to upstream")
        except OSError:
            # The upstream connection can be closed by session teardown out from under
            # this write (called from the ds-receiver thread).
            logger.warning("failed to forward 0810 keepalive response to upstream")

    def _downstream_receiver(self):
        while True:
            try:
                data = self.downstream.recv()
            except ConnectionError as e:
                # Covers both a remote disconnect and a local close racing this blocked
                # read during teardown — _recv_exact normalizes any OSError from the
                # latter into ConnectionError too.
                logger.warning("downstream connection lost: %s", e)
                self.stats.set_connection("downstream", False)
                self.reconnect_event.set()
                break

            if data[:4] == "PING".encode("cp500"):
                continue

            try:
                resp, _ = iso8583.decode(data, self.spec)
            except Exception:
                logger.exception("failed to decode downstream message")
                continue
            self.stats.record_recv()

            try:
                if resp.get("t") == "0810":
                    self._forward_0810(resp)
                else:
                    self.dispatcher.handle_response(resp)
            except Exception:
                logger.exception("unexpected error dispatching downstream message mti=%s", resp.get("t"))

    def _teardown(self, up_thread):
        self.dispatcher.drain_and_stop()

        with self._up_ref_lock:
            ref = self._upstream_ref
            self._upstream_ref = None
        if ref is not None:
            conn, _ = ref
            try:
                conn.close()
            except OSError:
                pass

        self.downstream.close()
        up_thread.join(timeout=5)
