#include <catch2/catch_test_macros.hpp>

#include "shared/ebcdic.h"

using xv6::shared::from_ebcdic;
using xv6::shared::to_ebcdic;

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
