#include "shared/crypto_utils.h"

#include <openssl/evp.h>
#include <openssl/hmac.h>
#include <openssl/provider.h>

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <stdexcept>

#include "shared/base64.h"
#include "shared/hex.h"

namespace xv6::shared::crypto_utils {

namespace {

// Single-DES (used by the retail-MAC and CVV2 algorithms below) lives in OpenSSL 3's "legacy"
// provider, which is not loaded by default -- only the "default" provider is. Triple-DES stays
// available either way, so this only bites the single-DES call sites specifically. Loaded once,
// lazily, on first use of any cipher in this file.
void ensure_legacy_provider_loaded() {
    static bool loaded = [] {
        OSSL_PROVIDER_load(nullptr, "legacy");
        OSSL_PROVIDER_load(nullptr, "default");
        return true;
    }();
    (void)loaded;
}

class CipherCtx {
public:
    CipherCtx() : ctx_(EVP_CIPHER_CTX_new()) {
        if (ctx_ == nullptr) throw std::runtime_error("EVP_CIPHER_CTX_new failed");
    }
    ~CipherCtx() { EVP_CIPHER_CTX_free(ctx_); }
    CipherCtx(const CipherCtx&) = delete;
    CipherCtx& operator=(const CipherCtx&) = delete;
    EVP_CIPHER_CTX* get() { return ctx_; }

private:
    EVP_CIPHER_CTX* ctx_;
};

std::vector<uint8_t> cipher_ecb(const EVP_CIPHER* cipher, const std::vector<uint8_t>& key,
                                 const std::vector<uint8_t>& data, bool encrypt) {
    ensure_legacy_provider_loaded();
    CipherCtx ctx;
    if (EVP_CipherInit_ex(ctx.get(), cipher, nullptr, key.data(), nullptr, encrypt ? 1 : 0) != 1) {
        throw std::runtime_error("EVP_CipherInit_ex failed");
    }
    EVP_CIPHER_CTX_set_padding(ctx.get(), 0);

    std::vector<uint8_t> out(data.size() + 16);
    int out_len1 = 0;
    int out_len2 = 0;
    if (EVP_CipherUpdate(ctx.get(), out.data(), &out_len1, data.data(), static_cast<int>(data.size())) != 1) {
        throw std::runtime_error("EVP_CipherUpdate failed");
    }
    if (EVP_CipherFinal_ex(ctx.get(), out.data() + out_len1, &out_len2) != 1) {
        throw std::runtime_error("EVP_CipherFinal_ex failed");
    }
    out.resize(static_cast<size_t>(out_len1 + out_len2));
    return out;
}

std::vector<uint8_t> des_ecb(const std::vector<uint8_t>& key8, const std::vector<uint8_t>& data, bool encrypt) {
    return cipher_ecb(EVP_des_ecb(), key8, data, encrypt);
}

std::vector<uint8_t> des3_ecb(const std::vector<uint8_t>& key24, const std::vector<uint8_t>& data, bool encrypt) {
    return cipher_ecb(EVP_des_ede3_ecb(), key24, data, encrypt);
}

// Retail MAC (ISO/IEC 9797-1 Algorithm 3): split the 16-byte session key into two 8-byte DES
// keys K1/K2; for each 8-byte block of ISO/IEC 9797-2-padded data, XOR with the running hash
// then DES-encrypt with K1; the final MAC is DES-encrypt(K1, DES-decrypt(K2, h)) on the last hash
// value. ISO/IEC 9797-2 padding: append 0x80, then zero-pad to the next 8-byte boundary.
std::vector<uint8_t> retail_mac(const std::vector<uint8_t>& session_key16, const std::vector<uint8_t>& data) {
    if (session_key16.size() != 16) throw std::invalid_argument("retail MAC session key must be 16 bytes");
    std::vector<uint8_t> k1(session_key16.begin(), session_key16.begin() + 8);
    std::vector<uint8_t> k2(session_key16.begin() + 8, session_key16.begin() + 16);

    std::vector<uint8_t> padded = data;
    padded.push_back(0x80);
    while (padded.size() % 8 != 0) padded.push_back(0x00);

    std::vector<uint8_t> h(8, 0x00);
    for (size_t i = 0; i < padded.size(); i += 8) {
        std::vector<uint8_t> xored(8);
        for (int j = 0; j < 8; ++j) xored[j] = h[j] ^ padded[i + j];
        h = des_ecb(k1, xored, true);
    }
    auto decrypted = des_ecb(k2, h, false);
    return des_ecb(k1, decrypted, true);
}

std::string one_hex_digit(size_t n) {
    char buf[2];
    std::snprintf(buf, sizeof(buf), "%zx", n % 16);
    return std::string(buf, 1);
}

// PAN field for ISO 9564-1 Format-0: "0000" + rightmost 12 digits of the PAN excluding its
// check digit (left-padded with zeros if the PAN has fewer than 13 digits).
std::vector<uint8_t> pan_field_format0(const std::string& pan) {
    std::string pan_no_check = pan.size() >= 1 ? pan.substr(0, pan.size() - 1) : pan;
    std::string right12;
    if (pan_no_check.size() >= 12) {
        right12 = pan_no_check.substr(pan_no_check.size() - 12);
    } else {
        right12 = std::string(12 - pan_no_check.size(), '0') + pan_no_check;
    }
    return hex_decode("0000" + right12);
}

}  // namespace

std::vector<uint8_t> expand_3des_key(const std::vector<uint8_t>& key) {
    if (key.size() == 24) return key;
    if (key.size() != 16) throw std::invalid_argument("3DES key must be 16 or 24 bytes");
    std::vector<uint8_t> key24 = key;
    key24.insert(key24.end(), key.begin(), key.begin() + 8);
    return key24;
}

std::string derive_udk(const std::string& imk_hex, const std::string& pan, const std::string& pan_seq) {
    std::string combined = pan + pan_seq;
    std::string z_digits;
    if (combined.size() >= 16) {
        z_digits = combined.substr(combined.size() - 16);
    } else {
        z_digits = std::string(16 - combined.size(), '0') + combined;
    }
    auto z = hex_decode(z_digits);

    auto imk24 = expand_3des_key(hex_decode(imk_hex));
    auto left = des3_ecb(imk24, z, true);

    std::vector<uint8_t> z_complement(z.size());
    for (size_t i = 0; i < z.size(); ++i) z_complement[i] = static_cast<uint8_t>(z[i] ^ 0xFF);
    auto right = des3_ecb(imk24, z_complement, true);

    std::vector<uint8_t> udk = left;
    udk.insert(udk.end(), right.begin(), right.end());
    return hex_encode(udk);
}

std::string derive_session_key(const std::string& udk_hex, const std::string& atc_hex) {
    auto atc = hex_decode(atc_hex);
    std::vector<uint8_t> r(8, 0x00);
    if (atc.size() >= 1) r[0] = atc[0];
    if (atc.size() >= 2) r[1] = atc[1];
    r[2] = 0xF0;

    auto udk24 = expand_3des_key(hex_decode(udk_hex));
    auto left = des3_ecb(udk24, r, true);

    std::vector<uint8_t> r_complement(r.size());
    for (size_t i = 0; i < r.size(); ++i) r_complement[i] = static_cast<uint8_t>(r[i] ^ 0xFF);
    auto right = des3_ecb(udk24, r_complement, true);

    std::vector<uint8_t> sk = left;
    sk.insert(sk.end(), right.begin(), right.end());
    return hex_encode(sk);
}

bool verify_arqc(const std::string& pan, const std::string& pan_seq, const std::string& imk_hex,
                  const nlohmann::json& f55) {
    std::string udk_hex = derive_udk(imk_hex, pan, pan_seq);
    std::string atc_hex = f55.value("atc", std::string(""));
    std::string sk_hex = derive_session_key(udk_hex, atc_hex);

    static constexpr const char* kFieldOrder[] = {
        "amount_auth", "amount_other", "terminal_country", "terminal_verification_results",
        "currency_code", "transaction_date", "transaction_type", "unpredictable_number", "aip", "atc",
    };
    std::vector<uint8_t> input;
    for (const char* key : kFieldOrder) {
        std::string hex_val = f55.value(key, std::string(""));
        auto bytes = hex_decode(hex_val);
        input.insert(input.end(), bytes.begin(), bytes.end());
    }

    auto mac = retail_mac(hex_decode(sk_hex), input);
    auto expected = hex_decode(f55.value("cryptogram", std::string("")));
    return mac == expected;
}

std::vector<uint8_t> calculate_arpc_method1(const std::string& arqc_hex, const std::string& arc,
                                             const std::string& sk_hex) {
    auto arqc = hex_decode(arqc_hex);
    std::vector<uint8_t> arc_bytes(arc.begin(), arc.end());
    arc_bytes.resize(4, 0x00);

    std::vector<uint8_t> xored = arqc;
    size_t overlap = std::min(xored.size(), arc_bytes.size());
    for (size_t i = 0; i < overlap; ++i) xored[i] ^= arc_bytes[i];

    auto sk24 = expand_3des_key(hex_decode(sk_hex));
    return des3_ecb(sk24, xored, true);
}

std::vector<uint8_t> encode_pin_block_format0(const std::string& pin, const std::string& pan) {
    std::string pin_field_hex = "0" + one_hex_digit(pin.size()) + pin;
    if (pin_field_hex.size() < 16) {
        pin_field_hex += std::string(16 - pin_field_hex.size(), 'F');
    } else {
        pin_field_hex = pin_field_hex.substr(0, 16);
    }
    auto pin_field = hex_decode(pin_field_hex);
    auto pan_field = pan_field_format0(pan);

    std::vector<uint8_t> clear(8);
    for (int i = 0; i < 8; ++i) clear[i] = pin_field[i] ^ pan_field[i];
    return clear;
}

std::vector<uint8_t> encrypt_pin_block(const std::vector<uint8_t>& plain, const std::string& pek_hex) {
    auto pek24 = expand_3des_key(hex_decode(pek_hex));
    return des3_ecb(pek24, plain, true);
}

bool verify_pin(const std::string& pan, const std::string& f52_base64, const std::string& pek_hex,
                 const std::string& reference_pin) {
    auto encrypted = base64_decode(f52_base64);
    auto pek24 = expand_3des_key(hex_decode(pek_hex));
    auto clear = des3_ecb(pek24, encrypted, false);

    auto pan_field = pan_field_format0(pan);
    std::vector<uint8_t> pin_field(8);
    for (int i = 0; i < 8; ++i) pin_field[i] = clear[i] ^ pan_field[i];

    std::string pin_field_hex = hex_encode(pin_field);
    int len = std::stoi(std::string(1, pin_field_hex[1]), nullptr, 16);
    if (len < 0 || len > 12 || 2 + len > static_cast<int>(pin_field_hex.size())) return false;
    std::string extracted_pin = pin_field_hex.substr(2, static_cast<size_t>(len));
    return extracted_pin == reference_pin;
}

std::string compute_cvv2(const std::string& pan, const std::string& expiry_mmyy, const std::string& cvk_hex) {
    std::string mm = expiry_mmyy.substr(0, 2);
    std::string yy = expiry_mmyy.substr(2, 2);
    std::string yymm = yy + mm;

    std::string data = pan + yymm + "000";
    if (data.size() < 32) {
        data += std::string(32 - data.size(), '0');
    } else {
        data = data.substr(0, 32);
    }
    auto data_bytes = hex_decode(data);
    std::vector<uint8_t> block0(data_bytes.begin(), data_bytes.begin() + 8);
    std::vector<uint8_t> block1(data_bytes.begin() + 8, data_bytes.begin() + 16);

    auto cvk = hex_decode(cvk_hex);
    std::vector<uint8_t> a(cvk.begin(), cvk.begin() + 8);
    std::vector<uint8_t> b(cvk.begin() + 8, cvk.begin() + 16);

    auto r1 = des_ecb(a, block0, true);
    std::vector<uint8_t> r2(8);
    for (int i = 0; i < 8; ++i) r2[i] = r1[i] ^ block1[i];
    auto r3 = des_ecb(a, r2, true);
    auto r4 = des_ecb(b, r3, false);
    auto r5 = des_ecb(a, r4, true);

    std::string hex = hex_encode(r5);
    std::string digits;
    for (char c : hex) {
        if (std::isdigit(static_cast<unsigned char>(c))) {
            digits.push_back(c);
            if (digits.size() == 3) break;
        }
    }
    if (digits.size() < 3) {
        for (char c : hex) {
            if (digits.size() == 3) break;
            if (std::isalpha(static_cast<unsigned char>(c))) {
                int val = std::tolower(static_cast<unsigned char>(c)) - 'a' + 10;
                digits.push_back(static_cast<char>('0' + (val - 10) % 10));
            }
        }
    }
    return digits.substr(0, 3);
}

bool verify_cvv2(const std::string& pan, const std::string& expiry_mmyy, const std::string& cvv2,
                  const std::string& cvk_hex) {
    return compute_cvv2(pan, expiry_mmyy, cvk_hex) == cvv2;
}

std::string compute_aav(const nlohmann::json& f47_data, const std::string& aav_key_hex, const std::string& pan) {
    std::string f14 = f47_data.value("f14", std::string(""));
    std::string message_type = f47_data.value("message_type", std::string(""));
    std::string input = pan + f14 + message_type;

    auto key = hex_decode(aav_key_hex);
    unsigned char mac[EVP_MAX_MD_SIZE];
    unsigned int mac_len = 0;
    HMAC(EVP_sha1(), key.data(), static_cast<int>(key.size()),
         reinterpret_cast<const unsigned char*>(input.data()), input.size(), mac, &mac_len);
    return base64_encode(std::vector<uint8_t>(mac, mac + mac_len));
}

bool verify_aav(const nlohmann::json& f47_data, const std::string& aav_key_hex, const std::string& pan) {
    std::string expected = f47_data.value("aav", std::string(""));
    return compute_aav(f47_data, aav_key_hex, pan) == expected;
}

}  // namespace xv6::shared::crypto_utils
