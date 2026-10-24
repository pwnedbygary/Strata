#include "memory_policy.hpp"
#include <cassert>
#include <limits>
using namespace native_memory;
int main() {
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
    s.available=0; assert(!refusal(s,4*GiB,768*MiB).empty());
    assert(snapshot().available>0);
}
