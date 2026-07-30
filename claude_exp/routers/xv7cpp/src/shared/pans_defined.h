#pragma once

#include <map>
#include <string>

namespace xv6::shared {

// One entry per PAN in config/pans_defined.json. Keys are PAN strings; crypto_host uses every
// field, downstream_host only cares whether a PAN is present at all.
struct PanRecord {
    std::string pin;
    std::string pan_seq;
    std::string imk_ac;
    std::string cvk;
    std::string pek;
    std::string aav_key;
};

std::map<std::string, PanRecord> load_pans_defined(const std::string& path);

}  // namespace xv6::shared
