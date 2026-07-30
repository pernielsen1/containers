package com.xv6.shared;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.io.File;
import java.util.Base64;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** Port of xv5's tests/test_crypto_utils.py. Same package as CryptoUtils so this can reach the
 * package-private padIso9797_2/buildMacInput/retailMac helpers, exactly like the Python test
 * imports the module's underscore-prefixed functions directly. */
class CryptoUtilsTest {

    private static final String PAN = "4111111111111111";
    private static Map<String, String> info;

    @BeforeAll
    static void loadPans() throws Exception {
        String path = System.getProperty("user.dir") + "/config/pans_defined.json";
        ObjectMapper mapper = new ObjectMapper();
        Map<String, Map<String, String>> pans = mapper.readValue(
                new File(path), new com.fasterxml.jackson.core.type.TypeReference<Map<String, Map<String, String>>>() {
                });
        info = pans.get(PAN);
    }

    private static Map<String, Object> f55() {
        Map<String, Object> f55 = new LinkedHashMap<>();
        f55.put("amount_auth", "000000000100");
        f55.put("amount_other", "000000000000");
        f55.put("terminal_country", "0840");
        f55.put("terminal_verification_results", "0000000000");
        f55.put("currency_code", "0840");
        f55.put("transaction_date", "250101");
        f55.put("transaction_type", "00");
        f55.put("unpredictable_number", "12345678");
        f55.put("aip", "3800");
        f55.put("atc", "0001");
        return f55;
    }

    @Test
    void udkAndSessionKeyAreDeterministic() {
        String udk1 = CryptoUtils.deriveUdk(info.get("imk_ac"), PAN, info.get("pan_seq"));
        String udk2 = CryptoUtils.deriveUdk(info.get("imk_ac"), PAN, info.get("pan_seq"));
        assertEquals(udk1, udk2);
        assertEquals(32, udk1.length());

        String sk = CryptoUtils.deriveSessionKey(udk1, "0001");
        assertEquals(32, sk.length());
    }

    @Test
    void verifyArqcAcceptsValidAndRejectsTampered() {
        String udk = CryptoUtils.deriveUdk(info.get("imk_ac"), PAN, info.get("pan_seq"));
        String sk = CryptoUtils.deriveSessionKey(udk, "0001");
        Map<String, Object> f55 = f55();
        byte[] data = CryptoUtils.padIso9797_2(CryptoUtils.buildMacInput(f55));
        byte[] mac = CryptoUtils.retailMac(HexFormat.of().parseHex(sk), data);
        f55.put("cryptogram", HexFormat.of().formatHex(mac).toUpperCase());

        assertTrue(CryptoUtils.verifyArqc(PAN, info.get("pan_seq"), info.get("imk_ac"), f55));

        Map<String, Object> tampered = new LinkedHashMap<>(f55);
        tampered.put("cryptogram", "0000000000000000");
        assertFalse(CryptoUtils.verifyArqc(PAN, info.get("pan_seq"), info.get("imk_ac"), tampered));
    }

    @Test
    void arpcMethod1Produces8Bytes() {
        String udk = CryptoUtils.deriveUdk(info.get("imk_ac"), PAN, info.get("pan_seq"));
        String sk = CryptoUtils.deriveSessionKey(udk, "0001");
        byte[] arpc = CryptoUtils.calculateArpcMethod1("A".repeat(16), "3030", sk);
        assertEquals(8, arpc.length);
    }

    @Test
    void pinBlockRoundtrip() {
        byte[] block = CryptoUtils.encodePinBlockFormat0(info.get("pin"), PAN);
        byte[] encrypted = CryptoUtils.encryptPinBlock(block, info.get("pek"));
        String b64 = Base64.getEncoder().encodeToString(encrypted);

        assertTrue(CryptoUtils.verifyPin(PAN, b64, info.get("pek"), info.get("pin")));
        assertFalse(CryptoUtils.verifyPin(PAN, b64, info.get("pek"), "0000"));
    }

    @Test
    void cvv2Roundtrip() {
        String cvv2 = CryptoUtils.computeCvv2(PAN, "1225", info.get("cvk"));
        assertEquals(3, cvv2.length());
        assertTrue(CryptoUtils.verifyCvv2(PAN, "1225", cvv2, info.get("cvk")));
        assertFalse(CryptoUtils.verifyCvv2(PAN, "1225", "000", info.get("cvk")));
    }

    @Test
    void aavRoundtrip() {
        Map<String, Object> f47Data = new LinkedHashMap<>();
        f47Data.put("f14", "1225");
        f47Data.put("message_type", "0100");
        String aav = CryptoUtils.computeAav(f47Data, info.get("aav_key"), PAN);
        f47Data.put("aav", aav);
        assertTrue(CryptoUtils.verifyAav(f47Data, info.get("aav_key"), PAN));

        f47Data.put("aav", "wrong");
        assertFalse(CryptoUtils.verifyAav(f47Data, info.get("aav_key"), PAN));
    }
}
