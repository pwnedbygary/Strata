#pragma once
#include <algorithm>
#include <charconv>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

namespace native_memory {
inline constexpr uint64_t MiB = 1ULL << 20, GiB = 1ULL << 30;
struct Snapshot {
    uint64_t available = 0, cgroup_used = 0, cgroup_limit = 0;
    int64_t vram_free = -1, gtt_free = -1;
    uint64_t gtt_total = 0, gtt_used = 0;
    uint64_t total = 0, swap_total = 0, swap_free = 0, gpu_total = 0, gpu_used = 0;
    uint64_t cpu_total = 0, cpu_idle = 0;
    int gpu_busy = -1, gpu_temperature_millic = 0;
    uint64_t cgroup_reclaimable = 0;   // of cgroup_used: clean inactive file cache, which refusal() counts as free
};
inline uint64_t number(const std::filesystem::path &path) {
    std::ifstream f(path);
    uint64_t n = 0;
    return f >> n ? n : 0;
}
// A cgroup's clean inactive file cache, counted as the engine's memory guard counts it
// (src/core/conversation_memory.cpp): memory.stat's inactive_file less file_dirty and file_writeback, never more than
// the charged usage, and 0 when the file is missing or unparsable.  A model file read into the page cache is charged to
// the group that read it; at the group's hard limit the kernel reclaims these pages before it kills a process.
inline uint64_t reclaimable_cache(const std::filesystem::path &dir, uint64_t current) {
    std::ifstream stat(dir / "memory.stat");
    std::optional<uint64_t> inactive;
    uint64_t dirty = 0, writeback = 0;
    std::string line;
    while (std::getline(stat, line)) {
        std::istringstream fields(line);
        std::string key, value, extra;
        if (!(fields >> key >> value) || (fields >> extra)) continue;
        if (key != "inactive_file" && key != "file_dirty" && key != "file_writeback") continue;
        uint64_t n = 0;
        const auto parsed = std::from_chars(value.data(), value.data() + value.size(), n);
        if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size()) return 0;
        if (key == "inactive_file") {
            if (inactive) return 0;
            inactive = n;
        } else {
            (key == "file_dirty" ? dirty : writeback) = n;
        }
    }
    if (!inactive) return 0;
    uint64_t credit = std::min(*inactive, current);
    credit = dirty >= credit ? 0 : credit - dirty;
    return writeback >= credit ? 0 : credit - writeback;
}
inline uint64_t cgroup_headroom(uint64_t limit, uint64_t used, uint64_t reclaimable) {
    const uint64_t charged = used - std::min(reclaimable, used);
    return limit > charged ? limit - charged : 0;
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
            s.gtt_total = number(device / "mem_info_gtt_total");
            s.gtt_used = number(device / "mem_info_gtt_used");
            s.gtt_free = s.gtt_total ? static_cast<int64_t>(s.gtt_total > s.gtt_used ? s.gtt_total - s.gtt_used : 0) : -1;
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
        // Enforce the tightest ancestor, including an enclosing user slice; its clean file cache counts as free.
        while (base.string().rfind("/sys/fs/cgroup", 0) == 0) {
            const auto limit = number(base / "memory.max");
            if (limit) {
                const auto used = number(base / "memory.current");
                const auto reclaimable = reclaimable_cache(base, used);
                if (!s.cgroup_limit || cgroup_headroom(limit, used, reclaimable) <
                                           cgroup_headroom(s.cgroup_limit, s.cgroup_used, s.cgroup_reclaimable)) {
                    s.cgroup_limit = limit; s.cgroup_used = used; s.cgroup_reclaimable = reclaimable;
                }
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
    const uint64_t cgroup_used = s.cgroup_used - std::min(s.cgroup_reclaimable, s.cgroup_used);
    if (s.cgroup_limit && (cgroup_used >= s.cgroup_limit ||
        additional > s.cgroup_limit - cgroup_used ||
        s.cgroup_limit - cgroup_used - additional < 512 * MiB))
        return "Insufficient process memory budget; request refused before inference";
    return {};
}
// MemoryHigh counts the mapped expert-file cache that Strata reads from SSD.
// A soft limit here makes the kernel reclaim those pages before the worker
// reaches its hard bound, which can turn each expert miss into another SSD
// stall. Keep the bounded hard cap, but leave MemoryHigh unset.
inline std::vector<std::string> worker_scope_memory_args(uint64_t budget_mib) {
    return {"-p", "MemoryMax=" + std::to_string(budget_mib) + "M",
            "-p", "MemorySwapMax=0", "-p", "OOMPolicy=kill"};
}
} // namespace native_memory
