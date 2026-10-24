#pragma once
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>
namespace native_requests {
// Holds request payloads, never extra engine slots or KV caches.
class Queue {
    std::mutex mutex_;
    std::vector<uint64_t> order_;
    uint64_t next_=0, bytes_=0;
    bool active_=false;
public:
    static constexpr size_t max_requests=5;
    static constexpr uint64_t max_bytes=256ULL<<20;
    struct Ticket {
        Queue *queue;uint64_t id,bytes;
        ~Ticket(){queue->release(id,bytes);}
    };
    struct State {size_t waiting;uint64_t bytes;};
    std::shared_ptr<Ticket> admit(uint64_t bytes) {
        std::lock_guard<std::mutex> lock(mutex_);
        if(order_.size()>=max_requests||bytes>max_bytes-bytes_)return {};
        const auto id=++next_;order_.push_back(id);bytes_+=bytes;
        return std::shared_ptr<Ticket>(new Ticket{this,id,bytes});
    }
    void release(uint64_t id,uint64_t bytes) {
        std::lock_guard<std::mutex> lock(mutex_);
        auto it=std::find(order_.begin(),order_.end(),id);
        if(it==order_.end())return;
        if(it==order_.begin())active_=false;
        order_.erase(it);bytes_-=bytes;
    }
    State state() {std::lock_guard<std::mutex> lock(mutex_);return {order_.size()-(active_?1:0),bytes_};}
    bool acquire(const Ticket &ticket,std::unique_lock<std::mutex> &turn,
                 const std::function<bool()> &alive,
                 std::chrono::milliseconds timeout=std::chrono::minutes(10)) {
        const auto end=std::chrono::steady_clock::now()+timeout;
        do {
            if(!alive())return false;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if(!order_.empty()&&order_.front()==ticket.id&&turn.try_lock()) {active_=true;return true;}
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        } while(std::chrono::steady_clock::now()<end);
        return false;
    }
};
}
