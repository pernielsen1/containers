package com.router.router;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/** Raw JSON shape of the "downstream" block - irm_id/client_id are plain strings here; see
 * {@link DownstreamConfig#from} for the EBCDIC conversion router_py's RouterConfig.from_file also does
 * explicitly (via shared.ims_connect.to_ebcdic) before this becomes usable at runtime. */
@JsonIgnoreProperties(ignoreUnknown = true)
public record DownstreamConfigJson(
        String host, int port, String irmId, String clientId,
        boolean sslActive, String certfile, String keyfile, String cafile) {
}
