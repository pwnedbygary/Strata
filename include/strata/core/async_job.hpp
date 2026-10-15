#pragma once
#include <condition_variable>
#include <exception>
#include <functional>
#include <mutex>
#include <stdexcept>
#include <thread>

namespace strata::core {
// One persistent worker, one outstanding job. Await before releasing captured data.
class AsyncJob {
    std::mutex mu_;
    std::condition_variable wake_, done_;
    std::function<void()> job_;
    std::exception_ptr error_;
    bool pending_ = false, stopping_ = false;
    std::thread thread_;
public:
    AsyncJob() : thread_([this] {
        std::unique_lock<std::mutex> lk(mu_);
        for (;;) {
            wake_.wait(lk, [&] { return pending_ || stopping_; });
            if (!pending_) return;
            auto job = std::move(job_);
            lk.unlock();
            std::exception_ptr error;
            try { job(); } catch (...) { error = std::current_exception(); }
            lk.lock(); error_ = error; pending_ = false; done_.notify_all();
        }
    }) {}
    ~AsyncJob() {
        { std::lock_guard<std::mutex> lk(mu_); stopping_ = true; }
        wake_.notify_one(); thread_.join();
    }
    void start(std::function<void()> job) {
        std::lock_guard<std::mutex> lk(mu_);
        if (pending_) throw std::logic_error("AsyncJob already pending");
        job_ = std::move(job); error_ = nullptr; pending_ = true; wake_.notify_one();
    }
    void wait() {
        std::unique_lock<std::mutex> lk(mu_);
        done_.wait(lk, [&] { return !pending_; });
        auto error = error_; error_ = nullptr;
        lk.unlock(); if (error) std::rethrow_exception(error);
    }
    struct Await {
        AsyncJob* worker;
        ~Await() { if (worker) try { worker->wait(); } catch (...) {} }
        void finish() { if (worker) { auto* w = worker; worker = nullptr; w->wait(); } }
    };
};
}
