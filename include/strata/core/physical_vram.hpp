#pragma once

#include <cstdint>
#include <fstream>
#include <optional>
#include <string>

namespace strata::core {
// The caller supplies the selected device's sysfs directory, never a card-order guess.
inline std::optional<uint64_t> physical_vram_free(const std::string& directory) {
    auto read = [](const std::string& path) -> std::optional<uint64_t> {
        std::ifstream file(path);
        std::string value, extra;
        if (!(file >> value) || file >> extra || value.empty()) return {};
        for (char c : value) if (c < '0' || c > '9') return {};
        try { return std::stoull(value); } catch (...) { return {}; }
    };
    const auto total = read(directory + "/mem_info_vram_total");
    const auto used = read(directory + "/mem_info_vram_used");
    if (!total || !used || *total == 0 || *used > *total) return {};
    return *total - *used;
}
} // namespace strata::core
