"""Regression test for the "Bad file descriptor" reconnect race - see resilience.md's write-up
and router/downstream.py's close(). The root cause: close() alone releases the fd number
immediately, which can race a blocked recv() on that fd against the kernel handing the number to
a brand-new socket before the blocked syscall notices. That exact fd-reuse race isn't
deterministically reproducible in a unit test (it depends on kernel-level fd allocation timing),
so this instead guards the observable contract the shutdown()-before-close() fix guarantees:
close() must promptly and cleanly unblock a thread stuck in recv(), rather than leaving it hung
or silently returning some other connection's data.
"""
import socket
import threading
import time

from router.downstream import DownstreamConnection


def _loopback_pair():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.create_connection(server.getsockname())
    accepted, _ = server.accept()
    server.close()
    return client, accepted


def test_close_promptly_unblocks_pending_recv():
    to_sock, to_peer = _loopback_pair()
    from_sock, from_peer = _loopback_pair()
    conn = DownstreamConnection(to_sock, from_sock)

    result = {}

    def blocked_recv():
        try:
            conn.recv()
        except Exception as e:  # noqa: BLE001 - capturing whatever recv() raises, by design
            result["error"] = e

    t = threading.Thread(target=blocked_recv, daemon=True)
    t.start()
    time.sleep(0.2)  # give the thread time to actually enter the blocking recv() call

    start = time.time()
    conn.close()
    t.join(timeout=2)
    elapsed = time.time() - start

    assert not t.is_alive(), "recv() thread did not wake up after close()"
    assert elapsed < 1.0, f"recv() took {elapsed:.2f}s to unblock after close()"
    assert isinstance(result.get("error"), ConnectionError)

    for s in (to_peer, from_peer):
        s.close()
