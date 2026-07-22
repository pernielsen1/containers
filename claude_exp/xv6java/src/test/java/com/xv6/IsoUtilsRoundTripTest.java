package com.xv6;

import com.solab.iso8583.IsoMessage;
import com.solab.iso8583.MessageFactory;
import com.xv6.shared.IsoUtils;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class IsoUtilsRoundTripTest {

    private static final String SPEC_PATH =
            System.getProperty("user.dir") + "/config/test_spec.xml";

    @Test
    void encodesAndParsesA0100Message() throws Exception {
        MessageFactory<IsoMessage> factory = IsoUtils.loadFactory(SPEC_PATH);

        Map<String, String> data = new LinkedHashMap<>();
        data.put("t", "0100");
        data.put("2", "4111111111111111");
        data.put("3", "000000");
        data.put("4", "000000000100");
        data.put("11", "000001");
        data.put("47", "{\"message_type\":\"0100\"}");

        IsoMessage built = IsoUtils.fromMap(factory, data);
        byte[] wire = built.writeData();

        IsoMessage parsed = factory.parseMessage(wire, 0);
        Map<String, String> roundTripped = IsoUtils.toMap(parsed);

        assertEquals(data, roundTripped);
    }

    @Test
    void build0800And0810RoundTrip() throws Exception {
        MessageFactory<IsoMessage> factory = IsoUtils.loadFactory(SPEC_PATH);

        byte[] wire0800 = IsoUtils.build0800(factory);
        IsoMessage parsed0800 = factory.parseMessage(wire0800, 0);
        assertEquals("0800", IsoUtils.toMap(parsed0800).get("t"));
        assertEquals("100", IsoUtils.toMap(parsed0800).get("24"));

        byte[] wire0810 = IsoUtils.build0810("100", factory);
        IsoMessage parsed0810 = factory.parseMessage(wire0810, 0);
        assertEquals("0810", IsoUtils.toMap(parsed0810).get("t"));
        assertEquals("100", IsoUtils.toMap(parsed0810).get("24"));
    }
}
