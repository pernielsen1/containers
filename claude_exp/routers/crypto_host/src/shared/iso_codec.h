#pragma once

#include <array>
#include <cstdint>
#include <map>
#include <string>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

namespace xv6::shared::iso_codec {

enum class IsoType { Alpha, Llvar, Lllvar, Binary, Lllbin };

struct FieldSpec {
    IsoType type;
    int length;  // 0 for LLVAR/LLLVAR/LLLBIN (variable length)
};

// Sole source of truth for field shape -- there is no per-MTI declaration file (no
// test_spec.xml equivalent). ISO 8583's own bitmap already says which fields are present on
// the wire, so decoding only ever needs "field N -> (type, length)". Fields 52/55 are
// intentionally absent: all PIN/ICC data travels inside field 47's JSON blob instead.
inline constexpr std::array<std::pair<int, FieldSpec>, 12> kFieldSpecs = {{
    {2, {IsoType::Llvar, 0}},
    {3, {IsoType::Alpha, 6}},
    {4, {IsoType::Alpha, 12}},
    {11, {IsoType::Alpha, 6}},
    {14, {IsoType::Alpha, 4}},
    {24, {IsoType::Alpha, 3}},
    {37, {IsoType::Alpha, 12}},
    {38, {IsoType::Alpha, 6}},
    {39, {IsoType::Alpha, 2}},
    {41, {IsoType::Alpha, 8}},
    {42, {IsoType::Alpha, 15}},
    {47, {IsoType::Lllvar, 0}},
}};

const FieldSpec* find_field_spec(int field);
bool is_known_field(const std::string& key);

// data["t"] is the 4-hex-digit MTI string (e.g. "0100"); other keys are decimal field numbers.
// Critical pitfall: the MTI is hex, not decimal -- "0100" is the 16-bit wire value 0x0100 (256
// decimal). encode() parses data["t"] with base 16; decode() formats it back with "%04x".
std::vector<uint8_t> encode(const std::map<std::string, std::string>& data);
std::map<std::string, std::string> decode(const std::vector<uint8_t>& bytes);

std::vector<uint8_t> build_0800();
std::vector<uint8_t> build_0810(const std::string& f24);

std::string f47_encode(const nlohmann::json& data);
nlohmann::json f47_decode(const std::string& value);  // {} on parse error or blank input

}  // namespace xv6::shared::iso_codec
