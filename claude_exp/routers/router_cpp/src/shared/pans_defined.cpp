#include "shared/pans_defined.h"

#include <fstream>
#include <stdexcept>

#include <nlohmann/json.hpp>

namespace shared {

std::map<std::string, PanRecord> load_pans_defined(const std::string& path) {
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error("failed to open pans_defined file: " + path);
    }
    nlohmann::json j;
    in >> j;

    std::map<std::string, PanRecord> result;
    for (const auto& [pan, rec] : j.items()) {
        PanRecord r;
        r.pin = rec.value("pin", std::string(""));
        r.pan_seq = rec.value("pan_seq", std::string("00"));
        r.imk_ac = rec.value("imk_ac", std::string(""));
        r.cvk = rec.value("cvk", std::string(""));
        r.pek = rec.value("pek", std::string(""));
        r.aav_key = rec.value("aav_key", std::string(""));
        result.emplace(pan, std::move(r));
    }
    return result;
}

}  // namespace shared
