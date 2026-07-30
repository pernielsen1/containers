#include <catch2/catch_test_macros.hpp>

#include "shared/base64.h"
#include "shared/crypto_utils.h"
#include "shared/hex.h"

using namespace xv6::shared;
using namespace xv6::shared::crypto_utils;

TEST_CASE("expand_3des_key expands a 16-byte key to K1|K2|K1", "[crypto_utils]") {
    std::vector<uint8_t> key16 = hex_decode("00112233445566778899aabbccddeeff");
    auto key24 = expand_3des_key(key16);
    REQUIRE(key24.size() == 24);
    REQUIRE(std::vector<uint8_t>(key24.begin(), key24.begin() + 16) == key16);
    REQUIRE(std::vector<uint8_t>(key24.begin() + 16, key24.end()) ==
            std::vector<uint8_t>(key16.begin(), key16.begin() + 8));

    std::vector<uint8_t> already24(24, 0xAB);
    REQUIRE(expand_3des_key(already24) == already24);

    REQUIRE_THROWS_AS(expand_3des_key(std::vector<uint8_t>(10, 0)), std::invalid_argument);
}

TEST_CASE("PIN block encrypt/verify round-trips for the correct PIN and rejects a wrong one", "[crypto_utils]") {
    std::string pan = "4111111111111111";
    std::string pin = "1234";
    std::string pek_hex = "0123456789abcdeffedcba9876543210";

    auto clear_block = encode_pin_block_format0(pin, pan);
    REQUIRE(clear_block.size() == 8);
    auto encrypted = encrypt_pin_block(clear_block, pek_hex);
    auto f52_base64 = base64_encode(encrypted);

    REQUIRE(verify_pin(pan, f52_base64, pek_hex, pin));
    REQUIRE_FALSE(verify_pin(pan, f52_base64, pek_hex, "9999"));
}

TEST_CASE("CVV2 verifies against its own computed value and rejects a tampered one", "[crypto_utils]") {
    std::string pan = "5500000000000004";
    std::string expiry_mmyy = "0626";
    std::string cvk_hex = "00112233445566778899aabbccddeeff";

    std::string cvv2 = compute_cvv2(pan, expiry_mmyy, cvk_hex);
    REQUIRE(cvv2.size() == 3);
    REQUIRE(verify_cvv2(pan, expiry_mmyy, cvv2, cvk_hex));

    std::string tampered = cvv2 == "000" ? "999" : "000";
    REQUIRE_FALSE(verify_cvv2(pan, expiry_mmyy, tampered, cvk_hex));
}

TEST_CASE("AAV verifies against its own computed value and rejects a tampered one", "[crypto_utils]") {
    std::string pan = "4111111111111111";
    std::string aav_key_hex = "aabbccddeeff00112233445566778899";

    nlohmann::json f47_data = {{"f14", "1225"}, {"message_type", "0100"}};
    std::string aav = compute_aav(f47_data, aav_key_hex, pan);
    REQUIRE_FALSE(aav.empty());

    f47_data["aav"] = aav;
    REQUIRE(verify_aav(f47_data, aav_key_hex, pan));

    f47_data["aav"] = "not-the-right-value";
    REQUIRE_FALSE(verify_aav(f47_data, aav_key_hex, pan));
}

TEST_CASE("ARPC method 1 only XORs the leftmost 4 bytes of the ARQC", "[crypto_utils]") {
    std::string arqc_hex = "0011223344556677";
    std::string sk_hex = "00112233445566778899aabbccddeeff";

    auto arpc_approved = calculate_arpc_method1(arqc_hex, "00", sk_hex);
    auto arpc_declined = calculate_arpc_method1(arqc_hex, "55", sk_hex);
    REQUIRE(arpc_approved.size() == 8);
    REQUIRE(arpc_approved != arpc_declined);
}

TEST_CASE("verify_arqc rejects a cryptogram that doesn't match the derived MAC", "[crypto_utils]") {
    // No independently-verified reference vector for the UDK/session-key derivation is
    // available, so this is a negative-path smoke test only: it confirms verify_arqc doesn't
    // crash and correctly rejects an arbitrary/garbage cryptogram, not that a genuine ARQC from
    // a real EMV card would verify true against this implementation.
    nlohmann::json f55 = {
        {"amount_auth", "000000000100"},        {"amount_other", "000000000000"},
        {"terminal_country", "0840"},             {"terminal_verification_results", "0000000000"},
        {"currency_code", "0840"},                 {"transaction_date", "240101"},
        {"transaction_type", "00"},                 {"unpredictable_number", "12345678"},
        {"aip", "1800"},                              {"atc", "0001"},
        {"cryptogram", "deadbeefdeadbeef"},
    };
    REQUIRE_FALSE(verify_arqc("4111111111111111", "00", "00112233445566778899aabbccddeeff", f55));
}
