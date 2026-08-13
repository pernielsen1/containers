package com.router.router;

import com.router.shared.ImsConnect;

/** Port of router_py's router/config.py DownstreamConfig dataclass, with irm_id/client_id already
 * EBCDIC-encoded to exactly 8 bytes (see {@link #from}). */
public record DownstreamConfig(
        String host, int port, byte[] irmId, byte[] clientId,
        boolean sslActive, String certfile, String keyfile, String cafile) {

    public static DownstreamConfig from(DownstreamConfigJson raw, String baseDir) {
        return new DownstreamConfig(
                raw.host(), raw.port(), ImsConnect.toEbcdic(raw.irmId(), 8), ImsConnect.toEbcdic(raw.clientId(), 8),
                raw.sslActive(), RouterConfig.resolvePath(baseDir, raw.certfile()),
                RouterConfig.resolvePath(baseDir, raw.keyfile()), RouterConfig.resolvePath(baseDir, raw.cafile()));
    }
}
