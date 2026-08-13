#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace shared {

std::vector<uint8_t> hex_decode(const std::string& hex);
std::string hex_encode(const std::vector<uint8_t>& bytes);

}  // namespace shared
