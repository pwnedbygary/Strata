#pragma once
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>

namespace native_memory {
inline constexpr uint64_t MiB = 1ULL << 20, GiB = 1ULL << 30;
struct Snapshot {
    uint64_t available = 0, cgroup_used = 0, cgroup_limit = 0;
    int64_t vram_free = -1;
    uint64_t total = 0, swap_total = 0, swap_free = 0, gpu_total = 0, gpu_used = 0;
    uint64_t cpu_total = 0, cpu_idle = 0;
    int gpu_busy = -1, gpu_temperature_millic = 0;
};
inline uint64_t number(const std::filesystem::path &path) {
    std::ifstream f(path);
    uint64_t n = 0;
    return f >> n ? n : 0;
}
inline Snapshot snapshot(const std::string &process = "self") {
    Snapshot s;
    std::ifstream mem("/proc/meminfo");
    std::string line;
    while (std::getline(mem, line)) {
        std::istringstream row(line);
        std::string key;
        uint64_t n = 0;
        if (!(row >> key >> n)) continue;
        if (key == "MemAvailable:") s.available = n * 1024;
        if (key == "MemTotal:") s.total = n * 1024;
        if (key == "SwapTotal:") s.swap_total = n * 1024;
        if (key == "SwapFree:") s.swap_free = n * 1024;
    }
    std::error_code ec;
    uint64_t largest = 0;
    for (const auto &entry : std::filesystem::directory_iterator("/sys/class/drm", ec)) {
        auto device = entry.path() / "device";
        auto total = number(device / "mem_info_vram_total");
        if (total > GiB && total > largest) {
            largest = total;
            const auto used = number(device / "mem_info_vram_used");
            s.vram_free = total > used ? static_cast<int64_t>(total - used) : 0;
            s.gpu_total = total; s.gpu_used = used;
            if (std::filesystem::exists(device / "gpu_busy_percent"))
                s.gpu_busy = static_cast<int>(number(device / "gpu_busy_percent"));
            std::error_code hw_ec;
            for (const auto &hw : std::filesystem::directory_iterator(device / "hwmon", hw_ec)) {
                if (std::filesystem::exists(hw.path() / "temp1_input"))
                    s.gpu_temperature_millic = static_cast<int>(number(hw.path() / "temp1_input"));
            }
        }
    }
    std::ifstream cpu("/proc/stat");
    if (std::getline(cpu, line)) {
        std::istringstream row(line); std::string name; row >> name;
        uint64_t value = 0; int i = 0;
        while (i < 8 && row >> value) {
            s.cpu_total += value;
            if (i == 3 || i == 4) s.cpu_idle += value;
            ++i;
        }
    }
    std::ifstream cg("/proc/" + process + "/cgroup");
    while (std::getline(cg, line)) {
        if (line.rfind("0::/", 0) != 0) continue;
        auto base = std::filesystem::path("/sys/fs/cgroup") / line.substr(4);
        // Enforce the tightest ancestor, including an enclosing user slice.
        while (base.string().rfind("/sys/fs/cgroup", 0) == 0) {
            auto limit = number(base / "memory.max");
            auto used = number(base / "memory.current");
            if (limit && (!s.cgroup_limit || (limit > used ? limit - used : 0) <
                                               (s.cgroup_limit > s.cgroup_used ? s.cgroup_limit - s.cgroup_used : 0))) {
                s.cgroup_limit = limit; s.cgroup_used = used;
            }
            if (base == "/sys/fs/cgroup") break;
            base = base.parent_path();
        }
    }
    return s;
}
inline std::string refusal(const Snapshot &s, uint64_t ram_floor, uint64_t vram_floor,
                           uint64_t additional = 0) {
    if (additional > s.available || s.available - additional < ram_floor)
        return "Insufficient available system RAM; request refused before inference";
    if (s.vram_free >= 0 && static_cast<uint64_t>(s.vram_free) < vram_floor)
        return "Insufficient physical VRAM headroom; request refused before inference";
    if (s.cgroup_limit && (s.cgroup_used >= s.cgroup_limit ||
        additional > s.cgroup_limit - s.cgroup_used ||
        s.cgroup_limit - s.cgroup_used - additional < 512 * MiB))
        return "Insufficient process memory budget; request refused before inference";
    return {};
}
} // namespace native_memory
