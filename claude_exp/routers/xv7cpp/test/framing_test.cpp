#include <sys/socket.h>
#include <unistd.h>

#include <catch2/catch_test_macros.hpp>

#include "shared/framing.h"

using namespace xv6::shared;

namespace {

struct SocketPair {
    int a, b;
    SocketPair() {
        int fds[2];
        REQUIRE(::socketpair(AF_UNIX, SOCK_STREAM, 0, fds) == 0);
        a = fds[0];
        b = fds[1];
    }
    ~SocketPair() {
        ::close(a);
        ::close(b);
    }
};

}  // namespace

TEST_CASE("framing round-trips ASCII length field", "[framing]") {
    SocketPair sp;
    FramingConfig cfg;
    cfg.length_field_type = FramingConfig::LengthFieldType::Ascii;
    cfg.length_field_bytes = 4;

    std::vector<uint8_t> payload(37, 'x');
    write_message(sp.a, payload, cfg);
    auto received = read_message(sp.b, cfg);
    REQUIRE(received == payload);
}

TEST_CASE("framing round-trips EBCDIC length field", "[framing]") {
    SocketPair sp;
    FramingConfig cfg;
    cfg.length_field_type = FramingConfig::LengthFieldType::Ebcdic;
    cfg.length_field_bytes = 4;

    std::vector<uint8_t> payload = {0x01, 0x02, 0x03, 0x04, 0x05};
    write_message(sp.a, payload, cfg);
    auto received = read_message(sp.b, cfg);
    REQUIRE(received == payload);
}

TEST_CASE("framing round-trips BIG_ENDIAN length field", "[framing]") {
    SocketPair sp;
    FramingConfig cfg;
    cfg.length_field_type = FramingConfig::LengthFieldType::BigEndian;
    cfg.length_field_bytes = 2;

    std::vector<uint8_t> payload(300, 'y');
    write_message(sp.a, payload, cfg);
    auto received = read_message(sp.b, cfg);
    REQUIRE(received == payload);
}

TEST_CASE("framing round-trips LITTLE_ENDIAN length field", "[framing]") {
    SocketPair sp;
    FramingConfig cfg;
    cfg.length_field_type = FramingConfig::LengthFieldType::LittleEndian;
    cfg.length_field_bytes = 2;

    std::vector<uint8_t> payload(300, 'z');
    write_message(sp.a, payload, cfg);
    auto received = read_message(sp.b, cfg);
    REQUIRE(received == payload);
}

TEST_CASE("framing round-trips a non-empty header_hex", "[framing]") {
    SocketPair sp;
    FramingConfig cfg;
    cfg.header_hex = "cafe";
    cfg.length_field_type = FramingConfig::LengthFieldType::Ascii;
    cfg.length_field_bytes = 4;

    std::vector<uint8_t> payload = {0xAA, 0xBB, 0xCC};
    write_message(sp.a, payload, cfg);
    auto received = read_message(sp.b, cfg);
    REQUIRE(received == payload);
}

TEST_CASE("framing fails fast on a length exceeding max_message_bytes", "[framing]") {
    SocketPair sp;
    FramingConfig cfg;
    cfg.length_field_type = FramingConfig::LengthFieldType::Ascii;
    cfg.length_field_bytes = 4;
    cfg.max_message_bytes = 10;

    // Write only the (oversized) length prefix -- never the payload. If read_message tried to
    // read the payload bytes before checking max_message_bytes, this test would hang forever
    // instead of throwing.
    std::vector<uint8_t> oversized_length_prefix = {'9', '9', '9', '9'};
    send_exact(sp.a, oversized_length_prefix);
    REQUIRE_THROWS_AS(read_message(sp.b, cfg), FramingError);
}
