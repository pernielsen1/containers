#include "shared/framing.h"

#include <sys/socket.h>

#include <cerrno>
#include <cstdio>
#include <cstring>
#include <stdexcept>

#include "shared/ebcdic.h"
#include "shared/hex.h"

namespace xv6::shared {

FramingConfig::LengthFieldType parse_length_field_type(const std::string& name) {
    if (name == "BIG_ENDIAN") return FramingConfig::LengthFieldType::BigEndian;
    if (name == "LITTLE_ENDIAN") return FramingConfig::LengthFieldType::LittleEndian;
    if (name == "ASCII") return FramingConfig::LengthFieldType::Ascii;
    if (name == "EBCDIC") return FramingConfig::LengthFieldType::Ebcdic;
    throw std::invalid_argument("unknown length_field_type: " + name);
}

std::vector<uint8_t> recv_exact(int fd, size_t n) {
    std::vector<uint8_t> buf(n);
    size_t off = 0;
    while (off < n) {
        ssize_t got = ::recv(fd, buf.data() + off, n - off, 0);
        if (got == 0) {
            throw FramingError("connection closed while reading");
        }
        if (got < 0) {
            if (errno == EINTR) continue;
            throw FramingError(std::string("recv failed: ") + std::strerror(errno));
        }
        off += static_cast<size_t>(got);
    }
    return buf;
}

void send_exact(int fd, const std::vector<uint8_t>& data) {
    size_t off = 0;
    while (off < data.size()) {
        ssize_t sent = ::send(fd, data.data() + off, data.size() - off, MSG_NOSIGNAL);
        if (sent < 0) {
            if (errno == EINTR) continue;
            throw FramingError(std::string("send failed: ") + std::strerror(errno));
        }
        off += static_cast<size_t>(sent);
    }
}

namespace {

int64_t decode_length_field(const std::vector<uint8_t>& bytes, FramingConfig::LengthFieldType type) {
    switch (type) {
        case FramingConfig::LengthFieldType::BigEndian: {
            int64_t v = 0;
            for (uint8_t b : bytes) v = (v << 8) | b;
            return v;
        }
        case FramingConfig::LengthFieldType::LittleEndian: {
            int64_t v = 0;
            for (auto it = bytes.rbegin(); it != bytes.rend(); ++it) v = (v << 8) | *it;
            return v;
        }
        case FramingConfig::LengthFieldType::Ascii: {
            std::string s(bytes.begin(), bytes.end());
            return std::stoll(s);
        }
        case FramingConfig::LengthFieldType::Ebcdic: {
            std::string s = from_ebcdic(bytes);
            return std::stoll(s);
        }
    }
    throw std::logic_error("unreachable");
}

std::vector<uint8_t> encode_length_field(size_t length, FramingConfig::LengthFieldType type, int width) {
    switch (type) {
        case FramingConfig::LengthFieldType::BigEndian: {
            std::vector<uint8_t> out(width);
            uint64_t v = length;
            for (int i = width - 1; i >= 0; --i) {
                out[i] = static_cast<uint8_t>(v & 0xff);
                v >>= 8;
            }
            return out;
        }
        case FramingConfig::LengthFieldType::LittleEndian: {
            std::vector<uint8_t> out(width);
            uint64_t v = length;
            for (int i = 0; i < width; ++i) {
                out[i] = static_cast<uint8_t>(v & 0xff);
                v >>= 8;
            }
            return out;
        }
        case FramingConfig::LengthFieldType::Ascii: {
            std::vector<char> buf(width + 1);
            std::snprintf(buf.data(), buf.size(), "%0*zu", width, length);
            return std::vector<uint8_t>(buf.begin(), buf.begin() + width);
        }
        case FramingConfig::LengthFieldType::Ebcdic: {
            std::vector<char> buf(width + 1);
            std::snprintf(buf.data(), buf.size(), "%0*zu", width, length);
            std::string ascii(buf.data(), width);
            return to_ebcdic(ascii, width);
        }
    }
    throw std::logic_error("unreachable");
}

}  // namespace

std::vector<uint8_t> read_message(int fd, const FramingConfig& cfg) {
    if (!cfg.header_hex.empty()) {
        auto header = hex_decode(cfg.header_hex);
        recv_exact(fd, header.size());  // header content is not validated, only its length matters
    }

    auto length_bytes = recv_exact(fd, static_cast<size_t>(cfg.length_field_bytes));
    int64_t length = decode_length_field(length_bytes, cfg.length_field_type);
    if (length < 0 || length > cfg.max_message_bytes) {
        throw FramingError("decoded message length " + std::to_string(length) +
                            " exceeds max_message_bytes " + std::to_string(cfg.max_message_bytes));
    }

    return recv_exact(fd, static_cast<size_t>(length));
}

void write_message(int fd, const std::vector<uint8_t>& data, const FramingConfig& cfg) {
    std::vector<uint8_t> out;
    if (!cfg.header_hex.empty()) {
        auto header = hex_decode(cfg.header_hex);
        out.insert(out.end(), header.begin(), header.end());
    }
    auto length_bytes = encode_length_field(data.size(), cfg.length_field_type, cfg.length_field_bytes);
    out.insert(out.end(), length_bytes.begin(), length_bytes.end());
    out.insert(out.end(), data.begin(), data.end());

    send_exact(fd, out);
}

}  // namespace xv6::shared
