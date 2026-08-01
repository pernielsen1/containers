#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace xv6::shared {

std::string base64_encode(const std::vector<uint8_t>& data);
std::vector<uint8_t> base64_decode(const std::string& s);

}  // namespace xv6::shared
