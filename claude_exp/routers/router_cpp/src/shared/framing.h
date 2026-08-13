#pragma once

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace shared {

struct FramingConfig {
    enum class LengthFieldType { BigEndian, LittleEndian, Ascii, Ebcdic };

    std::string header_hex;  // may be empty
    LengthFieldType length_field_type = LengthFieldType::Ascii;
    int length_field_bytes = 4;
    int max_message_bytes = 65536;
};

FramingConfig::LengthFieldType parse_length_field_type(const std::string& name);

class FramingError : public std::runtime_error {
public:
    explicit FramingError(const std::string& what) : std::runtime_error(what) {}
};

// Reads the optional fixed header (hex-decoded, discarded), reads the length field, decodes it
// per length_field_type, then reads exactly that many payload bytes. Throws FramingError
// immediately if the decoded length exceeds max_message_bytes, instead of blocking waiting for
// bytes that may never arrive.
std::vector<uint8_t> read_message(int fd, const FramingConfig& cfg);

// Writes header + encoded length + data in one send() call (looping internally over partial
// writes).
void write_message(int fd, const std::vector<uint8_t>& data, const FramingConfig& cfg);

// Loops on ::recv() until exactly n bytes are collected. A 0-byte read (remote EOF) or a
// negative return with errno != EINTR throws FramingError -- this covers both a genuine remote
// disconnect and a local socket close racing a blocked read from another thread.
std::vector<uint8_t> recv_exact(int fd, size_t n);
void send_exact(int fd, const std::vector<uint8_t>& data);

}  // namespace shared
