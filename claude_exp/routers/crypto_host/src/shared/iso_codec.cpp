#include "shared/iso_codec.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <stdexcept>

#include "shared/hex.h"

namespace xv6::shared::iso_codec {

namespace {

std::string field_key(int field) { return std::to_string(field); }

std::string zero_pad_decimal(size_t value, int width) {
    std::vector<char> buf(width + 1);
    std::snprintf(buf.data(), buf.size(), "%0*zu", width, value);
    return std::string(buf.data(), width);
}

std::vector<uint8_t> encode_field(const FieldSpec& spec, const std::string& value) {
    switch (spec.type) {
        case IsoType::Alpha: {
            std::string s = value;
            if (s.size() < static_cast<size_t>(spec.length)) {
                s += std::string(spec.length - s.size(), ' ');
            } else if (s.size() > static_cast<size_t>(spec.length)) {
                s = s.substr(0, spec.length);
            }
            return std::vector<uint8_t>(s.begin(), s.end());
        }
        case IsoType::Binary: {
            auto raw = hex_decode(value);
            raw.resize(spec.length, 0);
            return raw;
        }
        case IsoType::Llvar: {
            std::vector<uint8_t> out;
            std::string len_str = zero_pad_decimal(value.size(), 2);
            out.insert(out.end(), len_str.begin(), len_str.end());
            out.insert(out.end(), value.begin(), value.end());
            return out;
        }
        case IsoType::Lllvar: {
            std::vector<uint8_t> out;
            std::string len_str = zero_pad_decimal(value.size(), 3);
            out.insert(out.end(), len_str.begin(), len_str.end());
            out.insert(out.end(), value.begin(), value.end());
            return out;
        }
        case IsoType::Lllbin: {
            auto raw = hex_decode(value);
            std::vector<uint8_t> out;
            std::string len_str = zero_pad_decimal(raw.size(), 3);
            out.insert(out.end(), len_str.begin(), len_str.end());
            out.insert(out.end(), raw.begin(), raw.end());
            return out;
        }
    }
    throw std::logic_error("unreachable");
}

std::string decode_field(const FieldSpec& spec, const std::vector<uint8_t>& bytes, size_t& offset) {
    switch (spec.type) {
        case IsoType::Alpha: {
            if (offset + spec.length > bytes.size()) {
                throw std::runtime_error("truncated ALPHA field");
            }
            std::string s(bytes.begin() + static_cast<long>(offset),
                           bytes.begin() + static_cast<long>(offset + spec.length));
            offset += spec.length;
            return s;
        }
        case IsoType::Binary: {
            if (offset + spec.length > bytes.size()) {
                throw std::runtime_error("truncated BINARY field");
            }
            std::vector<uint8_t> raw(bytes.begin() + static_cast<long>(offset),
                                      bytes.begin() + static_cast<long>(offset + spec.length));
            offset += spec.length;
            return hex_encode(raw);
        }
        case IsoType::Llvar: {
            if (offset + 2 > bytes.size()) throw std::runtime_error("truncated LLVAR length prefix");
            std::string len_str(bytes.begin() + static_cast<long>(offset),
                                 bytes.begin() + static_cast<long>(offset + 2));
            int len = std::stoi(len_str);
            offset += 2;
            if (offset + static_cast<size_t>(len) > bytes.size()) {
                throw std::runtime_error("truncated LLVAR value");
            }
            std::string s(bytes.begin() + static_cast<long>(offset),
                           bytes.begin() + static_cast<long>(offset + len));
            offset += len;
            return s;
        }
        case IsoType::Lllvar: {
            if (offset + 3 > bytes.size()) throw std::runtime_error("truncated LLLVAR length prefix");
            std::string len_str(bytes.begin() + static_cast<long>(offset),
                                 bytes.begin() + static_cast<long>(offset + 3));
            int len = std::stoi(len_str);
            offset += 3;
            if (offset + static_cast<size_t>(len) > bytes.size()) {
                throw std::runtime_error("truncated LLLVAR value");
            }
            std::string s(bytes.begin() + static_cast<long>(offset),
                           bytes.begin() + static_cast<long>(offset + len));
            offset += len;
            return s;
        }
        case IsoType::Lllbin: {
            if (offset + 3 > bytes.size()) throw std::runtime_error("truncated LLLBIN length prefix");
            std::string len_str(bytes.begin() + static_cast<long>(offset),
                                 bytes.begin() + static_cast<long>(offset + 3));
            int len = std::stoi(len_str);
            offset += 3;
            if (offset + static_cast<size_t>(len) > bytes.size()) {
                throw std::runtime_error("truncated LLLBIN value");
            }
            std::vector<uint8_t> raw(bytes.begin() + static_cast<long>(offset),
                                      bytes.begin() + static_cast<long>(offset + len));
            offset += len;
            return hex_encode(raw);
        }
    }
    throw std::logic_error("unreachable");
}

}  // namespace

const FieldSpec* find_field_spec(int field) {
    for (const auto& [num, spec] : kFieldSpecs) {
        if (num == field) return &spec;
    }
    return nullptr;
}

bool is_known_field(const std::string& key) {
    if (key.empty() || !std::all_of(key.begin(), key.end(), [](unsigned char c) { return std::isdigit(c); })) {
        return false;
    }
    return find_field_spec(std::stoi(key)) != nullptr;
}

std::vector<uint8_t> encode(const std::map<std::string, std::string>& data) {
    uint16_t mti = static_cast<uint16_t>(std::stoul(data.at("t"), nullptr, 16));

    std::vector<int> fields_present;
    for (const auto& [field, spec] : kFieldSpecs) {
        if (data.find(field_key(field)) != data.end()) {
            fields_present.push_back(field);
        }
    }

    bool need_secondary = std::any_of(fields_present.begin(), fields_present.end(),
                                       [](int f) { return f > 64; });

    std::array<uint8_t, 16> bitmap{};
    for (int f : fields_present) {
        int bit_index = f - 1;  // 0-based
        bitmap[bit_index / 8] |= static_cast<uint8_t>(0x80 >> (bit_index % 8));
    }
    if (need_secondary) {
        bitmap[0] |= 0x80;  // bit 1 = secondary bitmap present
    }

    std::vector<uint8_t> out;
    out.push_back(static_cast<uint8_t>(mti >> 8));
    out.push_back(static_cast<uint8_t>(mti & 0xff));
    out.insert(out.end(), bitmap.begin(), bitmap.begin() + (need_secondary ? 16 : 8));

    for (int f : fields_present) {
        const FieldSpec* spec = find_field_spec(f);
        auto encoded = encode_field(*spec, data.at(field_key(f)));
        out.insert(out.end(), encoded.begin(), encoded.end());
    }
    return out;
}

std::map<std::string, std::string> decode(const std::vector<uint8_t>& bytes) {
    if (bytes.size() < 2) throw std::runtime_error("message too short to contain an MTI");

    std::map<std::string, std::string> data;
    uint16_t mti_val = (static_cast<uint16_t>(bytes[0]) << 8) | bytes[1];
    char mti_buf[8];
    std::snprintf(mti_buf, sizeof(mti_buf), "%04x", mti_val);
    data["t"] = mti_buf;

    size_t offset = 2;
    if (offset + 8 > bytes.size()) throw std::runtime_error("message too short to contain a bitmap");
    std::array<uint8_t, 8> primary{};
    std::copy(bytes.begin() + static_cast<long>(offset), bytes.begin() + static_cast<long>(offset + 8),
              primary.begin());
    offset += 8;

    bool secondary_present = (primary[0] & 0x80) != 0;
    std::array<uint8_t, 8> secondary{};
    if (secondary_present) {
        if (offset + 8 > bytes.size()) throw std::runtime_error("message too short to contain a secondary bitmap");
        std::copy(bytes.begin() + static_cast<long>(offset), bytes.begin() + static_cast<long>(offset + 8),
                  secondary.begin());
        offset += 8;
    }

    int max_bit = secondary_present ? 128 : 64;
    for (int bit = 2; bit <= max_bit; ++bit) {
        int byte_idx = (bit - 1) / 8;
        int bit_in_byte = (bit - 1) % 8;
        uint8_t byte_val = byte_idx < 8 ? primary[byte_idx] : secondary[byte_idx - 8];
        bool set = (byte_val & (0x80 >> bit_in_byte)) != 0;
        if (!set) continue;

        const FieldSpec* spec = find_field_spec(bit);
        if (spec == nullptr) {
            throw std::runtime_error("unknown field " + std::to_string(bit) + " on wire");
        }
        data[field_key(bit)] = decode_field(*spec, bytes, offset);
    }
    return data;
}

std::vector<uint8_t> build_0800() { return encode({{"t", "0800"}, {"24", "100"}}); }

std::vector<uint8_t> build_0810(const std::string& f24) {
    return encode({{"t", "0810"}, {"24", f24}});
}

std::string f47_encode(const nlohmann::json& data) { return data.dump(); }

nlohmann::json f47_decode(const std::string& value) {
    if (value.empty()) return nlohmann::json::object();
    try {
        return nlohmann::json::parse(value);
    } catch (const nlohmann::json::exception&) {
        return nlohmann::json::object();
    }
}

}  // namespace xv6::shared::iso_codec
