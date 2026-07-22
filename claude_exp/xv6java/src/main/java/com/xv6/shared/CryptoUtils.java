package com.xv6.shared;

import javax.crypto.Cipher;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.InvalidKeyException;
import java.security.NoSuchAlgorithmException;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Map;

/**
 * MasterCard M/Chip EMV operations. All methods are pure (no I/O). Port of xv5's
 * shared/crypto_utils.py, using standard JCE ({@code DESede/ECB/NoPadding}, {@code
 * DES/ECB/NoPadding}, {@code HmacSHA1}) - all present in the default SunJCE provider on JDK >=
 * 8u162, no BouncyCastle needed.
 */
public final class CryptoUtils {

    private static final HexFormat HEX = HexFormat.of();

    private CryptoUtils() {
    }

    private static Cipher des3Ecb() {
        try {
            return Cipher.getInstance("DESede/ECB/NoPadding");
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static Cipher desEcb() {
        try {
            return Cipher.getInstance("DES/ECB/NoPadding");
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static byte[] des3Encrypt(byte[] key16or24, byte[] data) {
        try {
            Cipher c = des3Ecb();
            c.init(Cipher.ENCRYPT_MODE, desedeKey(key16or24));
            return c.doFinal(data);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static byte[] des3Decrypt(byte[] key16or24, byte[] data) {
        try {
            Cipher c = des3Ecb();
            c.init(Cipher.DECRYPT_MODE, desedeKey(key16or24));
            return c.doFinal(data);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static SecretKeySpec desedeKey(byte[] key) throws InvalidKeyException {
        // Unlike pycryptodome (which accepts a 16-byte key directly for two-key triple-DES),
        // the SunJCE DESede cipher requires exactly 24 bytes - a 16-byte key must be expanded to
        // K1||K2||K1 first (verified: a bare 16-byte SecretKeySpec throws "Wrong key size").
        if (key.length == 16) {
            byte[] expanded = new byte[24];
            System.arraycopy(key, 0, expanded, 0, 16);
            System.arraycopy(key, 0, expanded, 16, 8);
            key = expanded;
        }
        return new SecretKeySpec(key, "DESede");
    }

    private static byte[] desEncrypt(byte[] key8, byte[] data) {
        try {
            Cipher c = desEcb();
            c.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(key8, "DES"));
            return c.doFinal(data);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static byte[] desDecrypt(byte[] key8, byte[] data) {
        try {
            Cipher c = desEcb();
            c.init(Cipher.DECRYPT_MODE, new SecretKeySpec(key8, "DES"));
            return c.doFinal(data);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static byte[] xor(byte[] a, byte[] b) {
        int n = Math.min(a.length, b.length);
        byte[] out = new byte[n];
        for (int i = 0; i < n; i++) {
            out[i] = (byte) (a[i] ^ b[i]);
        }
        return out;
    }

    private static byte[] hex(String s) {
        return HEX.parseHex(s);
    }

    private static String hexUpper(byte[] b) {
        return HEX.formatHex(b).toUpperCase();
    }

    /** EMV Option A UDK derivation. */
    public static String deriveUdk(String imkHex, String pan, String panSeq) {
        byte[] imk = hex(imkHex);
        String panPsn = rightJustify16((pan + panSeq));
        byte[] z = hex(panPsn);
        byte[] udkA = des3Encrypt(imk, z);
        byte[] zComplement = new byte[z.length];
        for (int i = 0; i < z.length; i++) {
            zComplement[i] = (byte) (~z[i] & 0xFF);
        }
        byte[] udkB = des3Encrypt(imk, zComplement);
        byte[] udk = concat(udkA, udkB);
        return hexUpper(udk);
    }

    private static String rightJustify16(String s) {
        String tail = s.length() > 16 ? s.substring(s.length() - 16) : s;
        StringBuilder sb = new StringBuilder();
        for (int i = tail.length(); i < 16; i++) {
            sb.append('0');
        }
        return sb.append(tail).toString();
    }

    /** ATC-based session key (EMV Common Session Key Derivation, Option A). */
    public static String deriveSessionKey(String udkHex, String atcHex) {
        byte[] udk = hex(udkHex);
        // Python: bytes.fromhex(atc_hex.zfill(4))[:2] - first two bytes of the zero-padded,
        // hex-decoded ATC (not the last two).
        byte[] atcFull = hex(zfill(atcHex, 4));
        byte[] atc = {atcFull[0], atcFull.length > 1 ? atcFull[1] : 0};

        byte[] rLeft = concat(atc, new byte[]{(byte) 0xF0}, new byte[5]);
        byte[] rRight = concat(atc, new byte[]{(byte) 0x0F}, new byte[5]);
        byte[] skLeft = des3Encrypt(udk, rLeft);
        byte[] skRight = des3Encrypt(udk, rRight);
        return hexUpper(concat(skLeft, skRight));
    }

    private static byte[] concat(byte[]... parts) {
        int total = 0;
        for (byte[] p : parts) {
            total += p.length;
        }
        byte[] out = new byte[total];
        int off = 0;
        for (byte[] p : parts) {
            System.arraycopy(p, 0, out, off, p.length);
            off += p.length;
        }
        return out;
    }

    // Package-private (not private) so CryptoUtilsTest, in the same package, can build a
    // self-consistent ARQC the same way xv5's white-box test_crypto_utils.py does via direct
    // access to _pad_iso9797_2/_build_mac_input/_retail_mac.
    static byte[] padIso9797_2(byte[] data) {
        int padded = data.length + 1;
        while (padded % 8 != 0) {
            padded++;
        }
        byte[] out = new byte[padded];
        System.arraycopy(data, 0, out, 0, data.length);
        out[data.length] = (byte) 0x80;
        return out;
    }

    /** ISO/IEC 9797-1 MAC Algorithm 3 (Retail MAC). */
    static byte[] retailMac(byte[] key16, byte[] data) {
        byte[] k1 = new byte[8];
        byte[] k2 = new byte[8];
        System.arraycopy(key16, 0, k1, 0, 8);
        System.arraycopy(key16, 8, k2, 0, 8);

        byte[] h = new byte[8];
        for (int i = 0; i < data.length; i += 8) {
            byte[] block = new byte[8];
            System.arraycopy(data, i, block, 0, 8);
            byte[] x = xor(block, h);
            h = desEncrypt(k1, x);
        }
        return desEncrypt(k1, desDecrypt(k2, h));
    }

    private static final String[] MAC_FIELDS = {
            "amount_auth", "amount_other", "terminal_country", "terminal_verification_results",
            "currency_code", "transaction_date", "transaction_type", "unpredictable_number", "aip", "atc",
    };

    static byte[] buildMacInput(Map<String, Object> f55) {
        int total = 0;
        byte[][] parts = new byte[MAC_FIELDS.length][];
        for (int i = 0; i < MAC_FIELDS.length; i++) {
            parts[i] = hex(String.valueOf(f55.get(MAC_FIELDS[i])));
            total += parts[i].length;
        }
        byte[] out = new byte[total];
        int off = 0;
        for (byte[] p : parts) {
            System.arraycopy(p, 0, out, off, p.length);
            off += p.length;
        }
        return out;
    }

    /** Retail MAC ARQC check. */
    public static boolean verifyArqc(String pan, String panSeq, String imkHex, Map<String, Object> f55) {
        String udk = deriveUdk(imkHex, pan, panSeq);
        String sk = deriveSessionKey(udk, String.valueOf(f55.getOrDefault("atc", "0000")));
        byte[] data = padIso9797_2(buildMacInput(f55));
        byte[] mac = retailMac(hex(sk), data);
        Object cryptogram = f55.get("cryptogram");
        String expected = cryptogram == null ? "" : String.valueOf(cryptogram);
        return hexUpper(mac).equals(expected.toUpperCase());
    }

    /** ARPC Method 1: encrypt(ARQC XOR (ARC padded to 8 bytes)) with the session key. */
    public static byte[] calculateArpcMethod1(String arqcHex, String arcHex, String skHex) {
        byte[] arqc = hex(arqcHex).clone();
        byte[] arc = hex(zfill(arcHex, 4));
        int n = Math.min(arc.length, arqc.length);
        for (int i = 0; i < n; i++) {
            arqc[i] ^= arc[i];
        }
        return des3Encrypt(hex(skHex), arqc);
    }

    private static byte[] panBlock(String pan) {
        String withoutCheckDigit = pan.substring(0, pan.length() - 1);
        String tail = withoutCheckDigit.length() > 12
                ? withoutCheckDigit.substring(withoutCheckDigit.length() - 12)
                : withoutCheckDigit;
        String digits = zfill(tail, 12);
        return hex("0000" + digits);
    }

    /** Build cleartext ISO 9564-1 Format-0 PIN block (tests). */
    public static byte[] encodePinBlockFormat0(String pin, String pan) {
        String control = "0";
        String lengthNibble = Integer.toHexString(pin.length()).toUpperCase();
        StringBuilder pinField = new StringBuilder(control).append(lengthNibble).append(pin);
        while (pinField.length() < 16) {
            pinField.append('F');
        }
        byte[] pinBlock = hex(pinField.toString());
        byte[] panBlock = panBlock(pan);
        return xor(pinBlock, panBlock);
    }

    /** 3DES encrypt PIN block. */
    public static byte[] encryptPinBlock(byte[] plain, String pekHex) {
        return des3Encrypt(hex(pekHex), plain);
    }

    /** ISO 9564-1 Format-0 PIN block verification. */
    public static boolean verifyPin(String pan, String f52Base64, String pekHex, String referencePin) {
        byte[] encrypted;
        try {
            encrypted = Base64.getDecoder().decode(f52Base64);
        } catch (Exception e) {
            return false;
        }
        byte[] clearBlock = des3Decrypt(hex(pekHex), encrypted);
        byte[] panBlock = panBlock(pan);
        byte[] pinBlock = xor(clearBlock, panBlock);
        String hexStr = hexUpper(pinBlock);
        int pinLen = Character.digit(hexStr.charAt(1), 16);
        if (pinLen < 0 || 2 + pinLen > hexStr.length()) {
            return false;
        }
        String pinDigits = hexStr.substring(2, 2 + pinLen);
        return pinDigits.equals(referencePin);
    }

    private static byte[][] cvvDataBlocks(String pan, String expiryMmyy, String serviceCode) {
        String mm = expiryMmyy.substring(0, 2);
        String yy = expiryMmyy.substring(2);
        String expiryYymm = yy + mm;
        String data = (pan + expiryYymm + serviceCode);
        data = data.length() > 32 ? data.substring(0, 32) : rightPad(data, 32, '0');
        return new byte[][]{hex(data.substring(0, 16)), hex(data.substring(16, 32))};
    }

    private static String rightPad(String s, int width, char c) {
        StringBuilder sb = new StringBuilder(s);
        while (sb.length() < width) {
            sb.append(c);
        }
        return sb.toString();
    }

    private static String cvvCore(String pan, String expiryMmyy, String cvkHex, String serviceCode) {
        byte[] cvk = hex(cvkHex);
        byte[] cvkA = new byte[8];
        byte[] cvkB = new byte[8];
        System.arraycopy(cvk, 0, cvkA, 0, 8);
        System.arraycopy(cvk, 8, cvkB, 0, 8);

        byte[][] blocks = cvvDataBlocks(pan, expiryMmyy, serviceCode);
        byte[] r1 = desEncrypt(cvkA, blocks[0]);
        byte[] r2 = xor(r1, blocks[1]);
        byte[] r3 = desEncrypt(cvkA, r2);
        byte[] r4 = desDecrypt(cvkB, r3);
        byte[] r5 = desEncrypt(cvkA, r4);

        String hexDigits = HEX.formatHex(r5);
        StringBuilder decimals = new StringBuilder();
        for (char c : hexDigits.toCharArray()) {
            if (Character.isDigit(c)) {
                decimals.append(c);
            }
        }
        if (decimals.length() < 3) {
            for (char c : hexDigits.toCharArray()) {
                if (Character.isLetter(c)) {
                    int v = (Character.digit(c, 16) - 10) % 10;
                    decimals.append(v);
                }
            }
        }
        return decimals.substring(0, Math.min(3, decimals.length()));
    }

    /** Compute CVV2 (tests). */
    public static String computeCvv2(String pan, String expiryMmyy, String cvkHex) {
        return cvvCore(pan, expiryMmyy, cvkHex, "000");
    }

    /** MasterCard CVV2 verification. */
    public static boolean verifyCvv2(String pan, String expiryMmyy, String cvv2, String cvkHex) {
        return computeCvv2(pan, expiryMmyy, cvkHex).equals(cvv2);
    }

    /** Compute AAV (tests). */
    public static String computeAav(Map<String, Object> f47Data, String aavKeyHex, String pan) {
        try {
            byte[] key = hex(aavKeyHex);
            String f14 = String.valueOf(f47Data.getOrDefault("f14", ""));
            String messageType = String.valueOf(f47Data.getOrDefault("message_type", ""));
            byte[] message = (pan + f14 + messageType).getBytes(StandardCharsets.US_ASCII);

            Mac mac = Mac.getInstance("HmacSHA1");
            mac.init(new SecretKeySpec(key, "HmacSHA1"));
            byte[] digest = mac.doFinal(message);
            return Base64.getEncoder().encodeToString(digest);
        } catch (NoSuchAlgorithmException | InvalidKeyException e) {
            throw new IllegalStateException(e);
        }
    }

    /** HMAC-SHA1 AAV verification. */
    public static boolean verifyAav(Map<String, Object> f47Data, String aavKeyHex, String pan) {
        String aav = String.valueOf(f47Data.getOrDefault("aav", ""));
        return aav.equals(computeAav(f47Data, aavKeyHex, pan));
    }

    private static String zfill(String s, int width) {
        StringBuilder sb = new StringBuilder();
        for (int i = s.length(); i < width; i++) {
            sb.append('0');
        }
        return sb.append(s).toString();
    }
}
