#include "memory_policy.hpp"
#include <cassert>
#include <limits>
using namespace native_memory;
int main() {
    const auto scope = worker_scope_memory_args(17451);
    assert(scope == std::vector<std::string>({"-p", "MemoryMax=17451M", "-p", "MemorySwapMax=0", "-p", "OOMPolicy=kill"}));
    for (const auto &arg : scope) assert(arg.rfind("MemoryHigh=", 0) != 0);
    Snapshot s{8*GiB, 2*GiB, 20*GiB, 2*static_cast<int64_t>(GiB)};
    assert(refusal(s,4*GiB,768*MiB,MiB).empty());
    assert(!refusal(s,4*GiB,768*MiB,5*GiB).empty());
    assert(!refusal(s,4*GiB,768*MiB,std::numeric_limits<uint64_t>::max()).empty());
    s.vram_free=700*MiB; assert(!refusal(s,4*GiB,768*MiB).empty());
    s.vram_free=-1; assert(refusal(s,4*GiB,768*MiB).empty());
    s.cgroup_used=20*GiB; assert(!refusal(s,4*GiB,768*MiB).empty());
    s.cgroup_used=21*GiB; assert(!refusal(s,4*GiB,768*MiB).empty());
    s.cgroup_used=20*GiB-512*MiB; assert(refusal(s,4*GiB,768*MiB).empty());
    assert(!refusal(s,4*GiB,768*MiB,1).empty());
    // the group's clean file cache counts as free, up to its usage
    auto budget = [](const std::string &r) { return r.find("process memory budget") != std::string::npos; };
    s.cgroup_used=20*GiB; assert(budget(refusal(s,4*GiB,768*MiB)));
    s.cgroup_reclaimable=GiB; assert(refusal(s,4*GiB,768*MiB).empty());
    assert(budget(refusal(s,4*GiB,768*MiB,513*MiB)));
    s.cgroup_reclaimable=511*MiB; assert(budget(refusal(s,4*GiB,768*MiB)));
    s.cgroup_reclaimable=40*GiB; assert(refusal(s,4*GiB,768*MiB,4*GiB).empty());
    s.cgroup_reclaimable=0;
    s.available=0; assert(!refusal(s,4*GiB,768*MiB).empty());
    assert(snapshot().available>0);
    // memory.stat: inactive_file less file_dirty and file_writeback, capped by the usage; nothing when unreadable
    const auto dir = std::filesystem::current_path() / "native_memory_policy_test.cgroup";
    std::filesystem::create_directories(dir);
    auto credit = [&](const std::string &text, uint64_t current) {
        std::ofstream(dir / "memory.stat") << text;
        return reclaimable_cache(dir, current);
    };
    assert(credit("anon 5\nfile 9000\nactive_file 4000\ninactive_file 5000\nfile_dirty 300\nfile_writeback 200\n",
                  1 << 20) == 4500);
    assert(credit("inactive_file 5000\nfile_dirty 300\n", 1000) == 700);
    assert(credit("inactive_file 100\nfile_dirty 60\nfile_writeback 60\n", 1000) == 0);
    assert(credit("active_file 5000\n", 1000) == 0);
    assert(credit("inactive_file 5000\ninactive_file 5000\n", 10000) == 0);
    assert(credit("inactive_file 5x\n", 10000) == 0);
    std::filesystem::remove_all(dir);
    assert(reclaimable_cache(dir, 10000) == 0);
}
