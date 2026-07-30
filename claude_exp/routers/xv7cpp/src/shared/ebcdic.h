#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace xv6::shared {

// IBM code page 500 (EBCDIC international). Table generated from Python's built-in `cp500`
// codec, which implements the same IBM standard as Java's Cp500 charset.
std::vector<uint8_t> to_ebcdic(const std::string& s, size_t length);
std::string from_ebcdic(const std::vector<uint8_t>& bytes);

}  // namespace xv6::shared
