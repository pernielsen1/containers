#include <catch2/catch_test_macros.hpp>

#include "shared/ebcdic.h"

using shared::ascii_to_ebcdic_bytes;
using shared::ebcdic_to_ascii_bytes;
using shared::from_ebcdic;
using shared::to_ebcdic;

TEST_CASE("ebcdic round-trips ASCII text", "[ebcdic]") {
    std::string s = "PING0001 clean the pipes ABCxyz0123";
    auto encoded = to_ebcdic(s, s.size());
    REQUIRE(from_ebcdic(encoded) == s);
}

TEST_CASE("ebcdic left-pads shorter values with EBCDIC space", "[ebcdic]") {
    auto encoded = to_ebcdic("AB", 4);
    REQUIRE(encoded.size() == 4);
    REQUIRE(encoded[0] == 0x40);
    REQUIRE(encoded[1] == 0x40);
    REQUIRE(from_ebcdic(encoded) == "  AB");
}

TEST_CASE("ebcdic right-truncates longer values, keeping the tail", "[ebcdic]") {
    auto encoded = to_ebcdic("ABCDE", 3);
    REQUIRE(encoded.size() == 3);
    REQUIRE(from_ebcdic(encoded) == "CDE");
}

TEST_CASE("PING marker only matches when both sides are EBCDIC", "[ebcdic]") {
    auto marker = to_ebcdic("PING", 4);
    std::vector<uint8_t> ascii_ping = {'P', 'I', 'N', 'G'};
    REQUIRE(marker != ascii_ping);
}

TEST_CASE("ascii_to_ebcdic_bytes/ebcdic_to_ascii_bytes translate byte-for-byte, no padding or "
          "truncation",
          "[ebcdic]") {
    // Unlike to_ebcdic/from_ebcdic above, these must preserve length exactly - iso_codec relies
    // on this to translate already-shaped bytes (LLVAR length-prefix digits + value) in place.
    std::vector<uint8_t> ascii = {'1', '6', '4', '1', '1', '1'};
    auto ebcdic = ascii_to_ebcdic_bytes(ascii);
    REQUIRE(ebcdic.size() == ascii.size());
    REQUIRE(ebcdic[0] == 0xf1);  // '1'
    REQUIRE(ebcdic[1] == 0xf6);  // '6'
    REQUIRE(ebcdic[2] == 0xf4);  // '4'
    REQUIRE(ebcdic_to_ascii_bytes(ebcdic) == ascii);
}
