package com.router.router;

import java.net.Socket;
import java.net.SocketAddress;
import java.util.concurrent.locks.ReentrantLock;

/** Port of router_py's router/upstream.py UpstreamConn tuple: a connected socket + its write lock. */
public record UpstreamConn(Socket socket, SocketAddress address, ReentrantLock writeLock) {
}
