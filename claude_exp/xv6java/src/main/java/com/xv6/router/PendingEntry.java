package com.xv6.router;

import java.net.Socket;
import java.util.concurrent.locks.ReentrantLock;

/** Port of xv5's router/dispatcher.py PendingEntry. */
public record PendingEntry(Socket upConn, ReentrantLock upWriteLock, String upstreamStan, long createdAtNanos) {
}
