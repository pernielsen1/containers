package com.xv6.shared;

import java.io.IOException;
import java.net.Socket;
import java.util.Arrays;

/**
 * IMS Connect wire protocol. Dual-socket model: to-socket sends requests, from-socket receives
 * responses. Port of xv5's shared/ims_connect.py.
 */
public final class ImsConnect {

    public static final int IRM_HEADER_LEN = 28;
    public static final byte[] PING_TRANSCODE = toEbcdic("PING0001", 8);

    private ImsConnect() {
    }

    /** EBCDIC-encode and left-pad/truncate to exactly {@code length} bytes. */
    public static byte[] toEbcdic(String s, int length) {
        byte[] b = s.getBytes(Charset500.CHARSET);
        if (b.length >= length) {
            return Arrays.copyOfRange(b, b.length - length, b.length);
        }
        byte[] out = new byte[length];
        byte space = " ".getBytes(Charset500.CHARSET)[0];
        Arrays.fill(out, 0, length - b.length, space);
        System.arraycopy(b, 0, out, length - b.length, b.length);
        return out;
    }

    /**
     * Build a complete IMS Connect wire frame: 4-byte big-endian length (payload only) + 28-byte
     * IMS header + optional TRANS_CODE (8 bytes EBCDIC) + data. irmF0=0x80 -> resume TPIPE (no
     * data). irmF0=0x00 -> normal request. transcode defaults to TRAN+mti when data is present.
     */
    public static byte[] buildFrame(int irmF0, byte[] irmId, byte[] clientId, String mti, byte[] data,
            byte[] transcode) {
        boolean hasData = data.length > 0;
        byte[] resolvedTranscode = transcode;
        if (hasData && resolvedTranscode == null) {
            resolvedTranscode = toEbcdic("TRAN" + mti, 8);
        }

        byte[] irmHeader = new byte[IRM_HEADER_LEN];
        int p = 0;
        irmHeader[p++] = (byte) ((IRM_HEADER_LEN >> 8) & 0xFF);
        irmHeader[p++] = (byte) (IRM_HEADER_LEN & 0xFF);
        irmHeader[p++] = 0x04;
        irmHeader[p++] = (byte) irmF0;
        System.arraycopy(irmId, 0, irmHeader, p, 8);
        p += 8;
        // IRM_NAK_RSNCDE(2) + IRM_RES(2)
        p += 4;
        // IRM_F5, IRM_TIMER, IRM_SOCT, IRM_ES
        irmHeader[p++] = 0x00;
        irmHeader[p++] = 0x15;
        irmHeader[p++] = 0x10;
        irmHeader[p++] = 0x01;
        System.arraycopy(clientId, 0, irmHeader, p, 8);

        byte[] trailer;
        if (hasData) {
            trailer = new byte[resolvedTranscode.length + data.length];
            System.arraycopy(resolvedTranscode, 0, trailer, 0, resolvedTranscode.length);
            System.arraycopy(data, 0, trailer, resolvedTranscode.length, data.length);
        } else {
            trailer = new byte[0];
        }

        int payloadLen = irmHeader.length + trailer.length;
        byte[] out = new byte[4 + payloadLen];
        out[0] = (byte) ((payloadLen >> 24) & 0xFF);
        out[1] = (byte) ((payloadLen >> 16) & 0xFF);
        out[2] = (byte) ((payloadLen >> 8) & 0xFF);
        out[3] = (byte) (payloadLen & 0xFF);
        System.arraycopy(irmHeader, 0, out, 4, irmHeader.length);
        System.arraycopy(trailer, 0, out, 4 + irmHeader.length, trailer.length);
        return out;
    }

    /** Send downstream response: 4-byte big-endian length + data. */
    public static void writeResponse(Socket sock, byte[] data) throws IOException {
        byte[] out = new byte[4 + data.length];
        int len = data.length;
        out[0] = (byte) ((len >> 24) & 0xFF);
        out[1] = (byte) ((len >> 16) & 0xFF);
        out[2] = (byte) ((len >> 8) & 0xFF);
        out[3] = (byte) (len & 0xFF);
        System.arraycopy(data, 0, out, 4, data.length);
        sock.getOutputStream().write(out);
        sock.getOutputStream().flush();
    }

    /** Read downstream response. Returns ISO data bytes only (strips length prefix). */
    public static byte[] readResponse(Socket sock) throws IOException {
        byte[] lenBytes = recvExact(sock, 4);
        int length = bigEndianToInt(lenBytes);
        return recvExact(sock, length);
    }

    public record ImsRequest(int irmF0, byte[] clientId, byte[] transcode, byte[] isoData) {
    }

    /** Read an IMS Connect request. */
    public static ImsRequest readRequest(Socket sock) throws IOException {
        byte[] lenBytes = recvExact(sock, 4);
        int payloadLen = bigEndianToInt(lenBytes);
        byte[] payload = recvExact(sock, payloadLen);

        int irmF0 = payload[3] & 0xFF;
        byte[] clientId = Arrays.copyOfRange(payload, 20, 28);
        byte[] rest = payload.length > IRM_HEADER_LEN
                ? Arrays.copyOfRange(payload, IRM_HEADER_LEN, payload.length)
                : new byte[0];
        byte[] transcode;
        byte[] isoData;
        if (rest.length > 0) {
            transcode = Arrays.copyOfRange(rest, 0, 8);
            isoData = Arrays.copyOfRange(rest, 8, rest.length);
        } else {
            transcode = new byte[0];
            isoData = new byte[0];
        }
        return new ImsRequest(irmF0, clientId, transcode, isoData);
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

    private static int bigEndianToInt(byte[] b) {
        return ((b[0] & 0xFF) << 24) | ((b[1] & 0xFF) << 16) | ((b[2] & 0xFF) << 8) | (b[3] & 0xFF);
    }
}
