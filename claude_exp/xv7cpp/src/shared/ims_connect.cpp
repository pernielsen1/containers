#include "shared/ims_connect.h"

#include <algorithm>

#include "shared/ebcdic.h"
#include "shared/framing.h"

namespace xv6::shared {

const std::vector<uint8_t> PING_TRANSCODE = to_ebcdic("PING0001", 8);

namespace {

void append_be16(std::vector<uint8_t>& out, uint16_t v) {
    out.push_back(static_cast<uint8_t>(v >> 8));
    out.push_back(static_cast<uint8_t>(v));
}

void append_be32(std::vector<uint8_t>& out, uint32_t v) {
    out.push_back(static_cast<uint8_t>(v >> 24));
    out.push_back(static_cast<uint8_t>(v >> 16));
    out.push_back(static_cast<uint8_t>(v >> 8));
    out.push_back(static_cast<uint8_t>(v));
}

uint32_t read_be32(const uint8_t* p) {
    return (static_cast<uint32_t>(p[0]) << 24) | (static_cast<uint32_t>(p[1]) << 16) |
           (static_cast<uint32_t>(p[2]) << 8) | static_cast<uint32_t>(p[3]);
}

}  // namespace

std::vector<uint8_t> build_frame(int irm_f0, const std::vector<uint8_t>& irm_id,
                                  const std::vector<uint8_t>& client_id, const std::string& mti,
                                  const std::vector<uint8_t>& data, std::vector<uint8_t> transcode) {
    if (transcode.empty() && !data.empty()) {
        transcode = to_ebcdic("TRAN" + mti, 8);
    }

    std::vector<uint8_t> header;
    header.reserve(IRM_HEADER_LEN);
    append_be16(header, static_cast<uint16_t>(IRM_HEADER_LEN));
    header.push_back(0x04);
    header.push_back(static_cast<uint8_t>(irm_f0));
    header.insert(header.end(), irm_id.begin(), irm_id.end());
    header.insert(header.end(), {0x00, 0x00, 0x00, 0x00});  // IRM_NAK_RSNCDE(2) + IRM_RES(2)
    header.insert(header.end(), {0x00, 0x15, 0x10, 0x01});  // IRM_F5, IRM_TIMER, IRM_SOCT, IRM_ES
    header.insert(header.end(), client_id.begin(), client_id.end());

    std::vector<uint8_t> trailer;
    if (!data.empty()) {
        trailer.insert(trailer.end(), transcode.begin(), transcode.end());
        trailer.insert(trailer.end(), data.begin(), data.end());
    }

    std::vector<uint8_t> out;
    out.reserve(4 + header.size() + trailer.size());
    append_be32(out, static_cast<uint32_t>(header.size() + trailer.size()));
    out.insert(out.end(), header.begin(), header.end());
    out.insert(out.end(), trailer.begin(), trailer.end());
    return out;
}

void write_response(int fd, const std::vector<uint8_t>& data) {
    std::vector<uint8_t> out;
    out.reserve(4 + data.size());
    append_be32(out, static_cast<uint32_t>(data.size()));
    out.insert(out.end(), data.begin(), data.end());
    send_exact(fd, out);
}

std::vector<uint8_t> read_response(int fd) {
    auto len_bytes = recv_exact(fd, 4);
    uint32_t len = read_be32(len_bytes.data());
    return recv_exact(fd, len);
}

ImsRequest read_request(int fd) {
    auto len_bytes = recv_exact(fd, 4);
    uint32_t payload_len = read_be32(len_bytes.data());
    auto payload = recv_exact(fd, payload_len);

    ImsRequest req;
    req.irm_f0 = payload.size() > 3 ? payload[3] : 0;
    if (payload.size() >= 28) {
        req.client_id.assign(payload.begin() + 20, payload.begin() + 28);
    }
    if (payload.size() > IRM_HEADER_LEN) {
        size_t trailer_len = payload.size() - IRM_HEADER_LEN;
        size_t transcode_len = std::min<size_t>(8, trailer_len);
        req.transcode.assign(payload.begin() + IRM_HEADER_LEN,
                              payload.begin() + IRM_HEADER_LEN + transcode_len);
        if (trailer_len > 8) {
            req.iso_data.assign(payload.begin() + IRM_HEADER_LEN + 8, payload.end());
        }
    }
    return req;
}

}  // namespace xv6::shared
