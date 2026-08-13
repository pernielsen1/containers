#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace shared {

constexpr int IRM_HEADER_LEN = 28;
extern const std::vector<uint8_t> PING_TRANSCODE;  // to_ebcdic("PING0001", 8)

// irm_f0=0x80 -> resume TPIPE (no data). irm_f0=0x00 -> normal request.
// transcode defaults to to_ebcdic("TRAN" + mti, 8) when data is non-empty and transcode is empty.
std::vector<uint8_t> build_frame(int irm_f0, const std::vector<uint8_t>& irm_id,
                                  const std::vector<uint8_t>& client_id, const std::string& mti,
                                  const std::vector<uint8_t>& data,
                                  std::vector<uint8_t> transcode = {});

// Simple [4-byte BE length][data] framing used on the from-socket direction (downstream_host ->
// router) after the from-connection has been classified via its initial build_frame'd resume
// TPIPE.
void write_response(int fd, const std::vector<uint8_t>& data);
std::vector<uint8_t> read_response(int fd);  // returns ISO data bytes only (length prefix stripped)

struct ImsRequest {
    int irm_f0;
    std::vector<uint8_t> client_id;
    std::vector<uint8_t> transcode;
    std::vector<uint8_t> iso_data;
};
ImsRequest read_request(int fd);

}  // namespace shared
