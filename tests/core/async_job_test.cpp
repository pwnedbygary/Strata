#include "strata/core/async_job.hpp"
#include <atomic>
#include <cstdio>
#include <future>
#include <stdexcept>
int main() {
    strata::core::AsyncJob worker;
    std::atomic<int> counter{0};
    std::promise<void> go; auto gate = go.get_future();
    worker.start([&] { gate.wait(); ++counter; });
    bool refused = false;
    try { worker.start([] {}); } catch (const std::logic_error&) { refused = true; }
    const bool correctly_blocked = refused && counter == 0;
    go.set_value(); worker.wait();
    if (!correctly_blocked) return 1;
    if (counter != 1) return 2;
    worker.start([] { throw std::runtime_error("read failed"); });
    bool failed = false;
    try { worker.wait(); } catch (const std::runtime_error&) { failed = true; }
    if (!failed) return 3;
    for (int i = 0; i < 1000; ++i) { worker.start([&] { ++counter; }); worker.wait(); }
    if (counter != 1001) return 4;
    { worker.start([&] { ++counter; }); strata::core::AsyncJob::Await await{&worker}; }
    if (counter != 1002) return 5;
    std::puts("async_job_test: PASS"); return 0;
}
