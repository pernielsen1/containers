#include "shared/iso_codec.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <stdexcept>

#include "shared/ebcdic.h"
#include "shared/hex.h"

namespace shared::iso_codec {

namespace {

std::string field_key(int field) { return std::to_string(field); }

std::string zero_pad_decimal(size_t value, int width) {
    std::vector<char> buf(width + 1);
    std::snprintf(buf.data(), buf.size(), "%0*zu", width, value);
    return std::string(buf.data(), width);
}

std::vector<uint8_t> encode_field(const FieldSpec& spec, const std::string& value, Encoding encoding) {
    switch (spec.type) {
        case IsoType::Alpha: {
            std::string s = value;
            if (s.size() < static_cast<size_t>(spec.length)) {
                s += std::string(spec.length - s.size(), ' ');
            } else if (s.size() > static_cast<size_t>(spec.length)) {
                s = s.substr(0, spec.length);
            }
            std::vector<uint8_t> out(s.begin(), s.end());
            return encoding == Encoding::Ebcdic ? shared::ascii_to_ebcdic_bytes(out) : out;
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
            return encoding == Encoding::Ebcdic ? shared::ascii_to_ebcdic_bytes(out) : out;
        }
        case IsoType::Lllvar: {
            std::vector<uint8_t> out;
            std::string len_str = zero_pad_decimal(value.size(), 3);
            out.insert(out.end(), len_str.begin(), len_str.end());
            out.insert(out.end(), value.begin(), value.end());
            return encoding == Encoding::Ebcdic ? shared::ascii_to_ebcdic_bytes(out) : out;
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

// Reads `count` raw bytes at `offset`, decodes them to ASCII text if `encoding` is Ebcdic
// (leaves them alone otherwise), and advances `offset` past them.
std::string read_text(const std::vector<uint8_t>& bytes, size_t& offset, size_t count, Encoding encoding,
                       const char* what) {
    if (offset + count > bytes.size()) {
        throw std::runtime_error(std::string("truncated ") + what);
    }
    std::vector<uint8_t> raw(bytes.begin() + static_cast<long>(offset),
                              bytes.begin() + static_cast<long>(offset + count));
    offset += count;
    if (encoding == Encoding::Ebcdic) {
        raw = shared::ebcdic_to_ascii_bytes(raw);
    }
    return std::string(raw.begin(), raw.end());
}

std::string decode_field(const FieldSpec& spec, const std::vector<uint8_t>& bytes, size_t& offset,
                          Encoding encoding) {
    switch (spec.type) {
        case IsoType::Alpha:
            return read_text(bytes, offset, static_cast<size_t>(spec.length), encoding, "ALPHA field");
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
            int len = std::stoi(read_text(bytes, offset, 2, encoding, "LLVAR length prefix"));
            return read_text(bytes, offset, static_cast<size_t>(len), encoding, "LLVAR value");
        }
        case IsoType::Lllvar: {
            int len = std::stoi(read_text(bytes, offset, 3, encoding, "LLLVAR length prefix"));
            return read_text(bytes, offset, static_cast<size_t>(len), encoding, "LLLVAR value");
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

std::vector<uint8_t> encode(const std::map<std::string, std::string>& data, Encoding encoding) {
    const std::string& mti = data.at("t");

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
    std::vector<uint8_t> mti_bytes(mti.begin(), mti.end());
    if (encoding == Encoding::Ebcdic) {
        mti_bytes = shared::ascii_to_ebcdic_bytes(mti_bytes);
    }
    out.insert(out.end(), mti_bytes.begin(), mti_bytes.end());
    // Bitmap is raw binary either way, never text-encoded - matches the shared upstream_host
    // Python component's pyiso8583 spec, where the bitmap fields keep "data_enc": "b" even in
    // the EBCDIC spec variant (test_spec_ebcdic.json).
    out.insert(out.end(), bitmap.begin(), bitmap.begin() + (need_secondary ? 16 : 8));

    for (int f : fields_present) {
        const FieldSpec* spec = find_field_spec(f);
        auto encoded = encode_field(*spec, data.at(field_key(f)), encoding);
        out.insert(out.end(), encoded.begin(), encoded.end());
    }
    return out;
}

std::map<std::string, std::string> decode(const std::vector<uint8_t>& bytes, Encoding encoding) {
    if (bytes.size() < 4) throw std::runtime_error("message too short to contain an MTI");

    std::map<std::string, std::string> data;
    // MTI is 4 characters ("0100"), not 2 binary bytes - matches the shared routers/upstream_host
    // Python component's pyiso8583 convention (and router_java's j8583 convention), which this
    // hand-rolled codec must speak now that upstream_host is no longer a per-language
    // reimplementation using this same codec on both ends. EBCDIC-translated like every other
    // text field when encoding == Ebcdic (it's not in kFieldSpecs, so handled directly here).
    std::vector<uint8_t> mti_bytes(bytes.begin(), bytes.begin() + 4);
    if (encoding == Encoding::Ebcdic) {
        mti_bytes = shared::ebcdic_to_ascii_bytes(mti_bytes);
    }
    data["t"] = std::string(mti_bytes.begin(), mti_bytes.end());

    size_t offset = 4;
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
        data[field_key(bit)] = decode_field(*spec, bytes, offset, encoding);
    }
    return data;
}

std::vector<uint8_t> build_0800(Encoding encoding) {
    return encode({{"t", "0800"}, {"24", "100"}}, encoding);
}

std::vector<uint8_t> build_0810(const std::string& f24, Encoding encoding) {
    return encode({{"t", "0810"}, {"24", f24}}, encoding);
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

}  // namespace shared::iso_codec
