#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

namespace xv6::shared::crypto_utils {

// Expands a 16-byte two-key triple-DES key (K1|K2) to the 24-byte form (K1|K2|K1) EVP_des_ede3
// requires. A key already 24 bytes long is returned unchanged.
std::vector<uint8_t> expand_3des_key(const std::vector<uint8_t>& key);

std::string derive_udk(const std::string& imk_hex, const std::string& pan, const std::string& pan_seq);
std::string derive_session_key(const std::string& udk_hex, const std::string& atc_hex);

// f55 is the decoded field-47 JSON's "f55" sub-object (cryptogram/atc/aip/... hex strings).
bool verify_arqc(const std::string& pan, const std::string& pan_seq, const std::string& imk_hex,
                  const nlohmann::json& f55);

std::vector<uint8_t> calculate_arpc_method1(const std::string& arqc_hex, const std::string& arc,
                                             const std::string& sk_hex);

std::vector<uint8_t> encode_pin_block_format0(const std::string& pin, const std::string& pan);
std::vector<uint8_t> encrypt_pin_block(const std::vector<uint8_t>& plain, const std::string& pek_hex);
bool verify_pin(const std::string& pan, const std::string& f52_base64, const std::string& pek_hex,
                 const std::string& reference_pin);

std::string compute_cvv2(const std::string& pan, const std::string& expiry_mmyy, const std::string& cvk_hex);
bool verify_cvv2(const std::string& pan, const std::string& expiry_mmyy, const std::string& cvv2,
                  const std::string& cvk_hex);

// f47_data is the decoded field-47 JSON object (needs "f14" and "message_type" for computation;
// "aav" for verification).
std::string compute_aav(const nlohmann::json& f47_data, const std::string& aav_key_hex, const std::string& pan);
bool verify_aav(const nlohmann::json& f47_data, const std::string& aav_key_hex, const std::string& pan);

}  // namespace xv6::shared::crypto_utils
