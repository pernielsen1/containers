package com.xv6.router;

import java.net.Socket;
import java.net.SocketAddress;
import java.util.Map;
import java.util.concurrent.locks.ReentrantLock;

/** Port of router_py's router/dispatcher.py RoutedMessage. */
public record RoutedMessage(Map<String, String> req, Socket upConn, ReentrantLock upWriteLock, SocketAddress upAddr) {
}
