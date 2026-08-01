#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace xv6::shared {

// IBM code page 500 (EBCDIC international). Table generated from Python's built-in `cp500`
// codec, which implements the same IBM standard as Java's Cp500 charset.
std::vector<uint8_t> to_ebcdic(const std::string& s, size_t length);
std::string from_ebcdic(const std::vector<uint8_t>& bytes);

// Byte-for-byte translation, no padding/truncation (unlike to_ebcdic/from_ebcdic above, which pad
// with EBCDIC space and truncate keeping the tail - the wrong semantics for already-shaped ISO
// 8583 field bytes, e.g. iso_codec's LLVAR length-prefix digits and pre-padded ALPHA values).
std::vector<uint8_t> ascii_to_ebcdic_bytes(const std::vector<uint8_t>& ascii);
std::vector<uint8_t> ebcdic_to_ascii_bytes(const std::vector<uint8_t>& ebcdic);

}  // namespace xv6::shared
