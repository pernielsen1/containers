package com.xv6.shared;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.solab.iso8583.IsoMessage;
import com.solab.iso8583.IsoType;
import com.solab.iso8583.MessageFactory;
import com.solab.iso8583.parse.ConfigParser;

import java.io.File;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * j8583 glue code. Port of xv5's shared/iso_utils.py, with one structural addition:
 * {@link #toMap}/{@link #fromMap} translate between {@code IsoMessage} and the same
 * {@code Map<String, String>} shape the Python dict-based messages used ("t" for MTI, field
 * numbers as string keys) - this keeps the rest of the port (dispatcher, sessions, simulators)
 * reading close to the original dict-based pseudocode instead of touching j8583 types directly
 * everywhere.
 *
 * j8583 computes the bitmap itself and treats the MTI as {@code IsoMessage.getType()/setType(int)}
 * rather than a field - neither is a "field" the way test_spec.xml's Python ancestor modeled "p"/
 * "1"/"t". Field 47's JSON blob still round-trips through plain {@link #f47Encode}/{@link
 * #f47Decode}, same shape as Python's json.dumps/json.loads.
 *
 * Fields 52/55 are declared in config/test_spec.xml for parity with xv5's test_spec.json (which
 * lists them in its global field vocabulary) but are intentionally absent from FIELD_SPECS below:
 * nothing in this project ever sets them as top-level ISO fields - all PIN/ICC data travels
 * inside field 47's JSON blob instead (see f47.json).
 */
public final class IsoUtils {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private record FieldSpec(IsoType isoType, int length) {
    }

    private static final Map<Integer, FieldSpec> FIELD_SPECS = new LinkedHashMap<>();

    static {
        FIELD_SPECS.put(2, new FieldSpec(IsoType.LLVAR, 0));
        FIELD_SPECS.put(3, new FieldSpec(IsoType.ALPHA, 6));
        FIELD_SPECS.put(4, new FieldSpec(IsoType.ALPHA, 12));
        FIELD_SPECS.put(11, new FieldSpec(IsoType.ALPHA, 6));
        FIELD_SPECS.put(14, new FieldSpec(IsoType.ALPHA, 4));
        FIELD_SPECS.put(24, new FieldSpec(IsoType.ALPHA, 3));
        FIELD_SPECS.put(37, new FieldSpec(IsoType.ALPHA, 12));
        FIELD_SPECS.put(38, new FieldSpec(IsoType.ALPHA, 6));
        FIELD_SPECS.put(39, new FieldSpec(IsoType.ALPHA, 2));
        FIELD_SPECS.put(41, new FieldSpec(IsoType.ALPHA, 8));
        FIELD_SPECS.put(42, new FieldSpec(IsoType.ALPHA, 15));
        FIELD_SPECS.put(47, new FieldSpec(IsoType.LLLVAR, 0));
    }

    private IsoUtils() {
    }

    /** Loads a j8583 MessageFactory from an XML config file path (not a classpath resource). */
    public static MessageFactory<IsoMessage> loadFactory(String specPath) throws IOException {
        return ConfigParser.createFromUrl(new File(specPath).toURI().toURL());
    }

    /** True if the given string field-number key is a recognized message field - used to filter
     * CSV columns to known fields, mirroring xv5's upstream_host.py {@code k in self.spec} check
     * (there, "t"/"p"/"1" additionally had to be excluded since pyiso8583's spec dict includes
     * them; FIELD_SPECS never contains those in the first place, so no separate exclusion is
     * needed here). */
    public static boolean isKnownField(String key) {
        try {
            return FIELD_SPECS.containsKey(Integer.parseInt(key));
        } catch (NumberFormatException e) {
            return false;
        }
    }

    /** Converts a decoded IsoMessage into a dict shape: {"t": "0100", "2": "...", ...}. */
    public static Map<String, String> toMap(IsoMessage msg) {
        Map<String, String> out = new LinkedHashMap<>();
        // j8583 stores/formats the message type as a hex-encoded int matching the MTI's literal
        // digits (e.g. "0100" <-> 0x0100 == 256), not a plain decimal parse of the MTI string.
        out.put("t", String.format("%04x", msg.getType()));
        for (Map.Entry<Integer, FieldSpec> e : FIELD_SPECS.entrySet()) {
            int field = e.getKey();
            if (msg.hasField(field)) {
                Object value = msg.getObjectValue(field);
                out.put(String.valueOf(field), value == null ? "" : String.valueOf(value));
            }
        }
        return out;
    }

    /** Builds an IsoMessage from a dict shape (the reverse of {@link #toMap}). */
    public static IsoMessage fromMap(MessageFactory<IsoMessage> factory, Map<String, String> data) {
        int type = Integer.parseInt(data.get("t"), 16);
        IsoMessage msg = factory.newMessage(type);
        for (Map.Entry<Integer, FieldSpec> e : FIELD_SPECS.entrySet()) {
            String key = String.valueOf(e.getKey());
            if (data.containsKey(key)) {
                msg.setValue(e.getKey(), data.get(key), e.getValue().isoType(), e.getValue().length());
            }
        }
        return msg;
    }

    public static byte[] build0800(MessageFactory<IsoMessage> factory) {
        Map<String, String> data = new LinkedHashMap<>();
        data.put("t", "0800");
        data.put("24", "100");
        return fromMap(factory, data).writeData();
    }

    public static byte[] build0810(String f24, MessageFactory<IsoMessage> factory) {
        Map<String, String> data = new LinkedHashMap<>();
        data.put("t", "0810");
        data.put("24", f24);
        return fromMap(factory, data).writeData();
    }

    public static String f47Encode(Map<String, Object> data) {
        try {
            return MAPPER.writeValueAsString(data);
        } catch (IOException e) {
            throw new IllegalStateException(e);
        }
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> f47Decode(String value) {
        if (value == null || value.isEmpty()) {
            return new LinkedHashMap<>();
        }
        try {
            return MAPPER.readValue(value, Map.class);
        } catch (IOException e) {
            return new LinkedHashMap<>();
        }
    }
}
