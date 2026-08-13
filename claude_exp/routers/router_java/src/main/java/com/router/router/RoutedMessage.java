package com.router.router;

import java.net.Socket;
import java.net.SocketAddress;
import java.util.Map;
import java.util.concurrent.locks.ReentrantLock;

/**
 * Port of router_py's router/dispatcher.py RoutedMessage. enqueuedAtNanos is 0 until
 * Dispatcher.submit() stamps it (mirrors router_py's msg.enqueued_at = time.monotonic(), set at
 * submit time rather than construction time - RoutedMessage is a record, so submit() rebuilds a
 * stamped copy via withEnqueuedAt() rather than mutating in place).
 */
public record RoutedMessage(Map<String, String> req, Socket upConn, ReentrantLock upWriteLock, SocketAddress upAddr,
        byte[] raw, long enqueuedAtNanos) {

    /** raw defaults to empty - used by the poison-pill sentinel and by tests that don't exercise
     * trace capture (Phase 4), which reads it via TraceRecorder.start()). */
    public RoutedMessage(Map<String, String> req, Socket upConn, ReentrantLock upWriteLock, SocketAddress upAddr) {
        this(req, upConn, upWriteLock, upAddr, new byte[0], 0L);
    }

    public RoutedMessage(Map<String, String> req, Socket upConn, ReentrantLock upWriteLock, SocketAddress upAddr,
            byte[] raw) {
        this(req, upConn, upWriteLock, upAddr, raw, 0L);
    }

    RoutedMessage withEnqueuedAt(long nanos) {
        return new RoutedMessage(req, upConn, upWriteLock, upAddr, raw, nanos);
    }
}
