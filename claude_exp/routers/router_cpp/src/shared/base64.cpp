#include "shared/base64.h"

#include <openssl/evp.h>

#include <stdexcept>

namespace shared {

std::string base64_encode(const std::vector<uint8_t>& data) {
    if (data.empty()) return "";
    std::vector<uint8_t> out(4 * ((data.size() + 2) / 3) + 1);
    int len = EVP_EncodeBlock(out.data(), data.data(), static_cast<int>(data.size()));
    return std::string(out.begin(), out.begin() + len);
}

std::vector<uint8_t> base64_decode(const std::string& s) {
    if (s.empty()) return {};
    std::vector<uint8_t> out(3 * ((s.size() + 3) / 4) + 1);
    int len = EVP_DecodeBlock(out.data(), reinterpret_cast<const unsigned char*>(s.data()),
                               static_cast<int>(s.size()));
    if (len < 0) {
        throw std::runtime_error("base64 decode failed");
    }
    int pad = 0;
    if (s.size() >= 1 && s[s.size() - 1] == '=') ++pad;
    if (s.size() >= 2 && s[s.size() - 2] == '=') ++pad;
    out.resize(static_cast<size_t>(len) - pad);
    return out;
}

}  // namespace shared
