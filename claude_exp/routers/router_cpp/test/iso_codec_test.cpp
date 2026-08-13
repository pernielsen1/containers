#include <catch2/catch_test_macros.hpp>

#include "shared/iso_codec.h"

using namespace shared::iso_codec;

TEST_CASE("MTI is encoded as 4 ASCII characters, not 2 binary bytes", "[iso_codec][mti]") {
    // Matches the shared upstream_host Python component's pyiso8583 convention (and router_java's
    // j8583 convention): "0800" on the wire is the literal characters '0','8','0','0', not the
    // 16-bit binary value 0x0800.
    auto wire = encode({{"t", "0800"}, {"24", "100"}});
    REQUIRE(wire.size() >= 4);
    REQUIRE(wire[0] == '0');
    REQUIRE(wire[1] == '8');
    REQUIRE(wire[2] == '0');
    REQUIRE(wire[3] == '0');
}

TEST_CASE("MTI is decoded from its 4 ASCII wire characters", "[iso_codec][mti]") {
    std::vector<uint8_t> wire = {'0', '1', '1', '0', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};
    auto decoded = decode(wire);
    REQUIRE(decoded.at("t") == "0110");
}

TEST_CASE("iso_codec round-trips a representative 0100 message", "[iso_codec]") {
    std::map<std::string, std::string> msg = {
        {"t", "0100"},   {"2", "4111111111111111"}, {"3", "000000"}, {"4", "000000000100"},
        {"11", "000001"}, {"14", "1225"},            {"24", "100"},   {"37", "AUDITNUM0001"},
        {"41", "TERM0001"}, {"42", "MERCHANTID00001"}, {"47", "{\"message_type\":\"0100\"}"},
    };
    auto wire = encode(msg);
    auto decoded = decode(wire);
    REQUIRE(decoded == msg);
}

TEST_CASE("iso_codec round-trips a representative 0110 message with fields 38/39", "[iso_codec]") {
    std::map<std::string, std::string> msg = {
        {"t", "0110"}, {"2", "4222222222222222"}, {"3", "000000"},  {"4", "000000000200"},
        {"11", "000002"}, {"14", "0130"},          {"24", "100"},    {"37", "AUDITNUM0002"},
        {"38", "AUTH01"}, {"39", "00"},            {"41", "TERM0002"}, {"42", "MERCHANTID00002"},
    };
    auto wire = encode(msg);
    auto decoded = decode(wire);
    REQUIRE(decoded == msg);
}

TEST_CASE("iso_codec ALPHA fields are space-padded and truncated to their declared length", "[iso_codec]") {
    auto wire = encode({{"t", "0800"}, {"24", "1"}});  // field 24 is ALPHA length 3
    auto decoded = decode(wire);
    REQUIRE(decoded.at("24") == "1  ");
}

TEST_CASE("iso_codec rejects an unknown field number found on the wire", "[iso_codec]") {
    // 4-byte MTI + an 8-byte primary bitmap with only bit 60 (field 60) set -- field 60 has no
    // entry in FIELD_SPECS, so this must be rejected, not silently skipped.
    std::vector<uint8_t> wire = {'0', '1', '0', '0', 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x10};
    REQUIRE_THROWS_AS(decode(wire), std::runtime_error);
}

TEST_CASE("build_0800 and build_0810 round-trip through decode", "[iso_codec]") {
    auto decoded_0800 = decode(build_0800());
    REQUIRE(decoded_0800.at("t") == "0800");
    REQUIRE(decoded_0800.at("24") == "100");

    auto decoded_0810 = decode(build_0810("00"));
    REQUIRE(decoded_0810.at("t") == "0810");
    REQUIRE(decoded_0810.at("24") == "00 ");
}

TEST_CASE("f47_encode/f47_decode round-trip JSON", "[iso_codec][f47]") {
    nlohmann::json data = {{"message_type", "0100"}, {"response_code", "00"}};
    auto encoded = f47_encode(data);
    auto decoded = f47_decode(encoded);
    REQUIRE(decoded == data);
}

TEST_CASE("f47_decode returns an empty object on blank or malformed input", "[iso_codec][f47]") {
    REQUIRE(f47_decode("").empty());
    REQUIRE(f47_decode("not json").empty());
}

TEST_CASE("Encoding::Ebcdic translates the MTI, and both LLVAR length-prefix digits and value",
          "[iso_codec][ebcdic]") {
    // Cross-checked against a real pyiso8583 encode of the same message with cp500 data_enc/
    // len_enc (routers/upstream_host/test_spec_ebcdic.json) and against router_java's j8583
    // MessageFactory with setCharacterEncoding("Cp500") + setForceStringEncoding(true) - all
    // three must agree on the exact wire bytes for router_2/upstream_2 to interoperate.
    auto wire = encode({{"t", "0100"}, {"2", "4111111111111111"}, {"11", "000001"}}, Encoding::Ebcdic);
    // MTI "0100" in cp500: 0xf0 0xf1 0xf0 0xf0
    REQUIRE(wire[0] == 0xf0);
    REQUIRE(wire[1] == 0xf1);
    REQUIRE(wire[2] == 0xf0);
    REQUIRE(wire[3] == 0xf0);
    // Bitmap (bytes 4-11) stays raw binary, never EBCDIC-translated. Field 2 -> bit 2 -> bitmap
    // byte 0 (bit index 1 within it, 0x80>>1); field 11 -> bit 11 -> bitmap byte 1 (bit index 2
    // within it, 0x80>>2).
    REQUIRE(wire[4] == 0x40);  // bitmap byte 0: field 2's bit
    REQUIRE(wire[5] == 0x20);  // bitmap byte 1: field 11's bit
    // LLVAR length prefix "16" in cp500: 0xf1 0xf6
    REQUIRE(wire[12] == 0xf1);
    REQUIRE(wire[13] == 0xf6);
    // First PAN digit '4' in cp500: 0xf4
    REQUIRE(wire[14] == 0xf4);

    auto decoded = decode(wire, Encoding::Ebcdic);
    REQUIRE(decoded.at("t") == "0100");
    REQUIRE(decoded.at("2") == "4111111111111111");
    REQUIRE(decoded.at("11") == "000001");
}

TEST_CASE("Encoding::Ebcdic round-trips a representative 0100 message end to end", "[iso_codec][ebcdic]") {
    std::map<std::string, std::string> msg = {
        {"t", "0100"},   {"2", "4111111111111111"}, {"3", "000000"}, {"4", "000000000100"},
        {"11", "000001"}, {"14", "1225"},            {"24", "100"},   {"37", "AUDITNUM0001"},
        {"41", "TERM0001"}, {"42", "MERCHANTID00001"}, {"47", "{\"message_type\":\"0100\"}"},
    };
    auto wire = encode(msg, Encoding::Ebcdic);
    auto decoded = decode(wire, Encoding::Ebcdic);
    REQUIRE(decoded == msg);
    // Decoding the same bytes as plain ASCII must fail outright (the LLVAR length-prefix bytes
    // are EBCDIC digits, not valid ASCII decimal digits) - confirms the bytes are genuinely
    // EBCDIC on the wire, not silently misreadable as ASCII.
    REQUIRE_THROWS(decode(wire, Encoding::Ascii));
}

TEST_CASE("build_0800/build_0810 respect Encoding::Ebcdic", "[iso_codec][ebcdic]") {
    auto decoded_0800 = decode(build_0800(Encoding::Ebcdic), Encoding::Ebcdic);
    REQUIRE(decoded_0800.at("t") == "0800");
    REQUIRE(decoded_0800.at("24") == "100");

    auto decoded_0810 = decode(build_0810("00", Encoding::Ebcdic), Encoding::Ebcdic);
    REQUIRE(decoded_0810.at("t") == "0810");
    REQUIRE(decoded_0810.at("24") == "00 ");
}

TEST_CASE("is_known_field matches only FIELD_SPECS entries", "[iso_codec]") {
    REQUIRE(is_known_field("47"));
    REQUIRE(is_known_field("11"));
    REQUIRE_FALSE(is_known_field("52"));   // declared absent per spec -- PIN data rides in f47
    REQUIRE_FALSE(is_known_field("expected_39"));
    REQUIRE_FALSE(is_known_field(""));
}
