#include <catch2/catch_test_macros.hpp>

#include "shared/iso_codec.h"

using namespace xv6::shared::iso_codec;

TEST_CASE("MTI is encoded as its hex value on the wire, not its decimal value", "[iso_codec][mti]") {
    // "0800" must appear on the wire as the 16-bit value 0x0800 (2048 decimal), not as the
    // decimal number 800 (0x0320 hex). A buggy base-10 parse would produce {0x03, 0x20} here.
    auto wire = encode({{"t", "0800"}, {"24", "100"}});
    REQUIRE(wire.size() >= 2);
    REQUIRE(wire[0] == 0x08);
    REQUIRE(wire[1] == 0x00);
}

TEST_CASE("MTI is decoded from its hex wire value, not its decimal value", "[iso_codec][mti]") {
    // Wire bytes 0x01 0x10 represent MTI "0110" (hex 0x0110 = 272 decimal). A buggy base-10
    // format would read the integer 272 and print "0272" instead of "0110".
    std::vector<uint8_t> wire = {0x01, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};
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
    // MTI bytes + an 8-byte primary bitmap with only bit 60 (field 60) set -- field 60 has no
    // entry in FIELD_SPECS, so this must be rejected, not silently skipped.
    std::vector<uint8_t> wire = {0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x10};
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

TEST_CASE("is_known_field matches only FIELD_SPECS entries", "[iso_codec]") {
    REQUIRE(is_known_field("47"));
    REQUIRE(is_known_field("11"));
    REQUIRE_FALSE(is_known_field("52"));   // declared absent per spec -- PIN data rides in f47
    REQUIRE_FALSE(is_known_field("expected_39"));
    REQUIRE_FALSE(is_known_field(""));
}
