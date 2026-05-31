"""Dispatcher — STAN generator, pending map, worker pool, core routing logic.

C++ equivalent: class owning std::thread pool, std::queue<RoutedMessage>,
std::unordered_map<string, PendingEntry>, std::atomic<int> stan_counter.
All shared state accessed only through the class interface.
"""
from __future__ import annotations

import logging
import queue
import socket
import threading
from dataclasses import dataclass
from typing import Optional

import iso8583

from shared import ims_connect
from shared.stats import Stats
from .config import RouterConfig
from .crypto_client import CryptoClient
from .downstream import DownstreamConnection

log = logging.getLogger(__name__)


@dataclass
class PendingEntry:
    """In-flight 0100 waiting for a 0110 response.
    C++ equivalent: struct PendingEntry { int up_fd; std::mutex& up_mutex; std::string upstream_stan; };
    """
    up_conn: socket.socket
    up_write_lock: threading.Lock
    upstream_stan: str


@dataclass
class RoutedMessage:
    """A decoded 0100 plus the upstream connection it arrived on.
    C++ equivalent: struct RoutedMessage { Iso8583Message req; int up_fd; ... };
    """
    req: dict
    up_conn: socket.socket
    up_write_lock: threading.Lock
    up_addr: tuple


class Dispatcher:
    """Routes 0100 requests through crypto → downstream, and 0110 responses back upstream.

    Thread-safe: submit() and handle_response() may be called from different threads.
    C++ equivalent: class with std::thread pool, bounded blocking queue, mutex-protected maps.
    """

    def __init__(
        self,
        cfg: RouterConfig,
        downstream: DownstreamConnection,
        crypto: CryptoClient,
        spec: dict,
        stats: Stats,
        reconnect_event: threading.Event,
    ) -> None:
        self._cfg         = cfg
        self._downstream  = downstream
        self._crypto      = crypto
        self._spec        = spec
        self._stats       = stats
        self._reconnect   = reconnect_event

        self._stan_counter = 0
        self._stan_lock    = threading.Lock()

        self._pending: dict[str, PendingEntry] = {}
        self._pending_lock = threading.Lock()

        self._queue: queue.Queue[Optional[RoutedMessage]] = queue.Queue()
        self._workers: list[threading.Thread] = []

    # ── STAN ──────────────────────────────────────────────────────────────────

    def _next_stan(self) -> str:
        with self._stan_lock:
            self._stan_counter += 1
            return str(self._stan_counter % 1_000_000).zfill(6)

    # ── public interface ──────────────────────────────────────────────────────

    def start(self) -> None:
        """Spawn worker threads. Call once after construction."""
        for i in range(self._cfg.worker_threads):
            t = threading.Thread(target=self._worker, name=f"worker-{i}", daemon=True)
            t.start()
            self._workers.append(t)
        log.info("router: started %d worker threads", self._cfg.worker_threads)

    def submit(self, msg: RoutedMessage) -> None:
        """Enqueue a 0100 message for processing. Non-blocking."""
        self._queue.put(msg)

    def handle_response(self, resp: dict) -> None:
        """Route a 0110/0130/0430 response from downstream back to the correct upstream.

        Called from the downstream-receiver thread.
        C++ equivalent: method called from ds_receiver std::thread.
        """
        mti = resp.get("t")

        if mti == "0810":
            # keepalive response — find upstream via pending or broadcast not needed,
            # the router just needs to forward it on the same upstream connection
            # (upstream_ref is passed separately via handle_keepalive)
            return  # handled by session's ds-receiver directly

        if mti not in ("0110", "0130", "0430"):
            log.warning("router: unexpected MTI %s from downstream", mti)
            return

        router_stan = resp.get("11", "")
        with self._pending_lock:
            entry = self._pending.pop(router_stan, None)

        if entry is None:
            log.warning("router: no pending entry for STAN=%s", router_stan)
            return

        fwd = dict(resp)
        fwd["11"] = entry.upstream_stan

        if mti == "0110":
            pan = resp.get("2", "")
            f47 = self._crypto.validate("validate_0110", pan, resp.get("47", ""))
            if f47:
                fwd["47"] = f47

        try:
            encoded, _ = iso8583.encode(fwd, spec=self._spec)
            with entry.up_write_lock:
                from shared.framing import write_message
                write_message(entry.up_conn, encoded, self._cfg.upstream.framing.to_dict())
            self._stats.record_sent()
            log.debug("router: forwarded %s STAN %s→%s rc=%s",
                      mti, router_stan, entry.upstream_stan, resp.get("39"))
        except Exception as e:
            log.warning("router: upstream reply error: %s", e)

    def drain_and_stop(self) -> None:
        """Signal workers to exit and wait for them to finish."""
        for _ in self._workers:
            self._queue.put(None)
        for t in self._workers:
            t.join(timeout=5)
        self._workers.clear()

    # ── internals ─────────────────────────────────────────────────────────────

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                break
            try:
                self._process(item)
            except OSError as e:
                log.warning("router: downstream write failed for %s: %s", item.up_addr, e)
                self._reconnect.set()
            except Exception as e:
                log.warning("router: worker error for %s: %s", item.up_addr, e)
            finally:
                self._queue.task_done()

    def _process(self, msg: RoutedMessage) -> None:
        """Core routing logic for 0100/0120/0420 messages.

        0100: crypto → STAN rewrite → pending insert → downstream send.
        0120/0420: STAN rewrite → pending insert → downstream send (no crypto).
        OSError on downstream send propagates to _worker → reconnect_event.
        C++ equivalent: method on Dispatcher called from thread pool.
        """
        mti          = msg.req.get("t", "")
        pan          = msg.req.get("2", "")
        upstream_stan = msg.req.get("11", "")
        router_stan  = self._next_stan()

        fwd = dict(msg.req)
        fwd["11"] = router_stan

        if mti == "0100":
            f47 = self._crypto.validate("validate_0100", pan, msg.req.get("47", ""))
            if f47:
                fwd["47"] = f47

        try:
            encoded, _ = iso8583.encode(fwd, spec=self._spec)
        except Exception as e:
            log.warning("router: encode error: %s", e)
            return

        with self._pending_lock:
            self._pending[router_stan] = PendingEntry(
                up_conn=msg.up_conn,
                up_write_lock=msg.up_write_lock,
                upstream_stan=upstream_stan,
            )

        frame = ims_connect.build_frame(
            0x00,
            self._cfg.downstream.irm_id,
            self._cfg.downstream.client_id,
            fwd["t"],
            encoded,
        )
        self._downstream.send(frame)   # OSError → propagates → reconnect
        self._stats.record_sent()
        log.debug("router: forwarded %s STAN %s→%s pan=%s",
                  mti, upstream_stan, router_stan, pan)
