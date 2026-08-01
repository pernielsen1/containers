package com.xv6.router;

import com.xv6.shared.ImsConnect;

/** Port of router_py's router/config.py DownstreamConfig dataclass, with irm_id/client_id already
 * EBCDIC-encoded to exactly 8 bytes (see {@link #from}). */
public record DownstreamConfig(String host, int port, byte[] irmId, byte[] clientId) {

    public static DownstreamConfig from(DownstreamConfigJson raw) {
        return new DownstreamConfig(
                raw.host(), raw.port(), ImsConnect.toEbcdic(raw.irmId(), 8), ImsConnect.toEbcdic(raw.clientId(), 8));
    }
}
