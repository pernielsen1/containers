package com.xv6;

import com.xv6.router.RouterConfig;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RouterConfigTest {

    @Test
    void loadsRouter1ConfigWithDefaults() throws Exception {
        String path = System.getProperty("user.dir") + "/config/router_1.json";
        RouterConfig cfg = RouterConfig.fromFile(path);

        assertEquals("router_1", cfg.name());
        assertEquals(8080, cfg.commandPort());
        assertEquals("partner_a", cfg.partnerId());
        assertEquals(5000, cfg.upstream().port());
        assertEquals("ASCII", cfg.upstream().framing().lengthFieldType());
        assertEquals(5001, cfg.downstream().port());
        assertEquals(8, cfg.downstream().irmId().length);
        assertEquals(8, cfg.downstream().clientId().length);
        assertEquals(5002, cfg.crypto().port());
        assertTrue(cfg.isoSpec().endsWith("test_spec.xml"));
        assertEquals(8, cfg.workerThreads());
        assertEquals(10, cfg.reestablishSeconds());
        assertEquals(40, cfg.yellowThresholdSeconds());

        // Defaults not present in router_1.json:
        assertEquals(1000, cfg.queueMaxsize());
        assertEquals(30, cfg.pendingTtlSeconds());
        assertEquals(5, cfg.cryptoBreakerThreshold());
        assertEquals(30, cfg.cryptoBreakerCooldownSeconds());
        assertEquals(2.0, cfg.reconnectJitterSeconds());
        assertEquals("127.0.0.1", cfg.commandBindHost());
    }
}
