package com.router.shared;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/** Port of router_py's tests/test_framing.py. Java has no direct equivalent of socket.socketpair(), so
 * a loopback ServerSocket/Socket pair stands in for it. */
class FramingTest {

    private static Socket[] socketPair() throws IOException {
        try (ServerSocket server = new ServerSocket(0, 1, java.net.InetAddress.getLoopbackAddress())) {
            Socket client = new Socket();
            client.connect(new InetSocketAddress(server.getInetAddress(), server.getLocalPort()));
            Socket accepted = server.accept();
            return new Socket[]{client, accepted};
        }
    }

    @ParameterizedTest
    @ValueSource(strings = {"BIG_ENDIAN", "LITTLE_ENDIAN", "ASCII", "EBCDIC"})
    void roundtripAllLengthFieldTypes(String lengthFieldType) throws IOException {
        Socket[] pair = socketPair();
        FramingConfig cfg = new FramingConfig("", lengthFieldType, 4, Framing.DEFAULT_MAX_MESSAGE_BYTES);
        byte[] payload = "hello world".getBytes(StandardCharsets.UTF_8);
        try {
            Framing.writeMessage(pair[0], payload, cfg);
            assertArrayEquals(payload, Framing.readMessage(pair[1], cfg));
        } finally {
            pair[0].close();
            pair[1].close();
        }
    }

    @Test
    void roundtripWithFixedHeader() throws IOException {
        Socket[] pair = socketPair();
        FramingConfig cfg = new FramingConfig("DEADBEEF", "ASCII", 4, Framing.DEFAULT_MAX_MESSAGE_BYTES);
        byte[] payload = "abc123".getBytes(StandardCharsets.UTF_8);
        try {
            Framing.writeMessage(pair[0], payload, cfg);
            assertArrayEquals(payload, Framing.readMessage(pair[1], cfg));
        } finally {
            pair[0].close();
            pair[1].close();
        }
    }

    @Test
    void maxMessageBytesRejection() throws IOException {
        Socket[] pair = socketPair();
        FramingConfig cfg = new FramingConfig("", "ASCII", 4, 5);
        byte[] payload = "this payload is too long".getBytes(StandardCharsets.UTF_8);
        try {
            Framing.writeMessage(pair[0], payload, cfg);
            assertThrows(IOException.class, () -> Framing.readMessage(pair[1], cfg));
        } finally {
            pair[0].close();
            pair[1].close();
        }
    }

    @Test
    void disconnectRaisesConnectionError() throws IOException {
        Socket[] pair = socketPair();
        FramingConfig cfg = new FramingConfig("", "ASCII", 4, Framing.DEFAULT_MAX_MESSAGE_BYTES);
        pair[0].close();
        try {
            assertThrows(IOException.class, () -> Framing.readMessage(pair[1], cfg));
        } finally {
            pair[1].close();
        }
    }
}
