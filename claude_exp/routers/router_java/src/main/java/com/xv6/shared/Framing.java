package com.xv6.shared;

import java.io.IOException;
import java.net.Socket;
import java.nio.charset.StandardCharsets;

/**
 * Length-prefixed TCP framing: optional fixed header + length field + payload.
 *
 * Port of router_py's shared/framing.py. Python distinguishes OSError from ConnectionError and wraps
 * the former into the latter so callers only handle one type; java.io.IOException already covers
 * both cases uniformly (closed-socket reads surface as IOException here too), so every method
 * below just declares {@code throws IOException} and there is no separate wrapping step needed.
 */
public final class Framing {

    public static final int DEFAULT_MAX_MESSAGE_BYTES = 65536;

    private Framing() {
    }

    private static byte[] recvExact(Socket sock, int n) throws IOException {
        byte[] buf = new byte[n];
        int off = 0;
        while (off < n) {
            int read = sock.getInputStream().read(buf, off, n - off);
            if (read < 0) {
                throw new IOException("connection closed while reading");
            }
            off += read;
        }
        return buf;
    }

    private static byte[] encodeLength(int length, int lengthFieldBytes, String lengthFieldType) {
        switch (lengthFieldType) {
            case "BIG_ENDIAN":
                return intToBytes(length, lengthFieldBytes, true);
            case "LITTLE_ENDIAN":
                return intToBytes(length, lengthFieldBytes, false);
            case "ASCII":
                return zeroPad(length, lengthFieldBytes).getBytes(StandardCharsets.US_ASCII);
            case "EBCDIC":
                return zeroPad(length, lengthFieldBytes).getBytes(Charset500.CHARSET);
            default:
                throw new IllegalArgumentException("unknown length_field_type: " + lengthFieldType);
        }
    }

    private static int decodeLength(byte[] raw, String lengthFieldType) {
        switch (lengthFieldType) {
            case "BIG_ENDIAN":
                return bytesToInt(raw, true);
            case "LITTLE_ENDIAN":
                return bytesToInt(raw, false);
            case "ASCII":
                return Integer.parseInt(new String(raw, StandardCharsets.US_ASCII).trim());
            case "EBCDIC":
                return Integer.parseInt(new String(raw, Charset500.CHARSET).trim());
            default:
                throw new IllegalArgumentException("unknown length_field_type: " + lengthFieldType);
        }
    }

    private static String zeroPad(int value, int width) {
        String s = Integer.toString(value);
        StringBuilder sb = new StringBuilder();
        for (int i = s.length(); i < width; i++) {
            sb.append('0');
        }
        return sb.append(s).toString();
    }

    private static byte[] intToBytes(int value, int width, boolean bigEndian) {
        byte[] out = new byte[width];
        for (int i = 0; i < width; i++) {
            int shift = bigEndian ? (width - 1 - i) : i;
            out[i] = (byte) ((value >> (8 * shift)) & 0xFF);
        }
        return out;
    }

    private static int bytesToInt(byte[] bytes, boolean bigEndian) {
        int value = 0;
        for (int i = 0; i < bytes.length; i++) {
            int shift = bigEndian ? (bytes.length - 1 - i) : i;
            value |= (bytes[i] & 0xFF) << (8 * shift);
        }
        return value;
    }

    /**
     * cfg keys: headerHex (may be null/empty), lengthFieldBytes, lengthFieldType
     * ("BIG_ENDIAN"|"LITTLE_ENDIAN"|"ASCII"|"EBCDIC"), maxMessageBytes (optional, default 65536).
     * Reads optional fixed header, reads length field, reads payload. Throws immediately if the
     * decoded length exceeds maxMessageBytes, instead of blocking waiting for bytes that may
     * never arrive - a corrupt or hostile length field must fail fast and drop the connection.
     */
    public static byte[] readMessage(Socket sock, FramingConfig cfg) throws IOException {
        if (cfg.headerHex() != null && !cfg.headerHex().isEmpty()) {
            int headerLen = hexToBytes(cfg.headerHex()).length;
            recvExact(sock, headerLen);
        }

        int maxMessageBytes = cfg.maxMessageBytes() > 0 ? cfg.maxMessageBytes() : DEFAULT_MAX_MESSAGE_BYTES;

        byte[] rawLen = recvExact(sock, cfg.lengthFieldBytes());
        int length = decodeLength(rawLen, cfg.lengthFieldType());
        if (length > maxMessageBytes) {
            throw new IOException(
                    "declared message length " + length + " exceeds max_message_bytes " + maxMessageBytes);
        }
        return recvExact(sock, length);
    }

    /** Writes header + encoded length + data in one write. */
    public static void writeMessage(Socket sock, byte[] data, FramingConfig cfg) throws IOException {
        byte[] header = (cfg.headerHex() != null && !cfg.headerHex().isEmpty())
                ? hexToBytes(cfg.headerHex())
                : new byte[0];
        byte[] lengthBytes = encodeLength(data.length, cfg.lengthFieldBytes(), cfg.lengthFieldType());

        byte[] out = new byte[header.length + lengthBytes.length + data.length];
        System.arraycopy(header, 0, out, 0, header.length);
        System.arraycopy(lengthBytes, 0, out, header.length, lengthBytes.length);
        System.arraycopy(data, 0, out, header.length + lengthBytes.length, data.length);

        sock.getOutputStream().write(out);
        sock.getOutputStream().flush();
    }

    private static byte[] hexToBytes(String hex) {
        int len = hex.length();
        byte[] out = new byte[len / 2];
        for (int i = 0; i < len; i += 2) {
            out[i / 2] = (byte) ((Character.digit(hex.charAt(i), 16) << 4)
                    + Character.digit(hex.charAt(i + 1), 16));
        }
        return out;
    }
}
