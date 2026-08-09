package com.xv6.router;

import java.net.Socket;
import java.util.concurrent.locks.ReentrantLock;

/**
 * Port of router_py's router/dispatcher.py PendingEntry. startedAtNanos is distinct from
 * createdAtNanos (set once this entry is added to `pending`, i.e. after crypto + right before
 * the downstream send - used for the TTL reaper and downstream_rtt): startedAtNanos is the true
 * transaction start (RoutedMessage.enqueuedAtNanos, before queue wait and the upstream-leg
 * crypto call) - used for the end-to-end "total" latency bucket.
 */
public record PendingEntry(
        Socket upConn, ReentrantLock upWriteLock, String upstreamStan, long createdAtNanos, long startedAtNanos) {

    public PendingEntry(Socket upConn, ReentrantLock upWriteLock, String upstreamStan, long createdAtNanos) {
        this(upConn, upWriteLock, upstreamStan, createdAtNanos, createdAtNanos);
    }
}
