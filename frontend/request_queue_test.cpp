#include "request_queue.hpp"
#include <cassert>
#include <atomic>
int main(){
 {
  native_requests::Queue fifo;std::mutex mutex;auto a=fifo.admit(1),b=fifo.admit(1);std::unique_lock<std::mutex> lock(mutex,std::defer_lock);
  assert(!fifo.acquire(*b,lock,[]{return false;}));assert(!lock.owns_lock());
  assert(fifo.acquire(*a,lock,[]{return true;}));lock.unlock();a.reset();
  assert(fifo.acquire(*b,lock,[]{return true;}));
 }
 native_requests::Queue q;std::mutex turn;
 auto first=q.admit(8);std::unique_lock<std::mutex> active(turn,std::defer_lock);
 assert(q.acquire(*first,active,[]{return true;}));
 auto second=q.admit(16),third=q.admit(16),fourth=q.admit(16),fifth=q.admit(16);
 assert(!q.admit(1));assert(q.state().waiting==4);
 std::unique_lock<std::mutex> later(turn,std::defer_lock);int beats=0;
 assert(!q.acquire(*third,later,[&]{++beats;return false;}));assert(beats==1);third.reset();
 std::atomic<bool> waiting{false},acquired{false};
 std::thread worker([&]{std::unique_lock<std::mutex> lock(turn,std::defer_lock);assert(q.acquire(*second,lock,[&]{waiting=true;return true;}));acquired=true;});
 while(!waiting)std::this_thread::yield();assert(!acquired);active.unlock();first.reset();worker.join();assert(acquired);second.reset();fourth.reset();fifth.reset();assert(q.state().bytes==0);
 auto huge=q.admit(native_requests::Queue::max_bytes);assert(huge&&!q.admit(1));huge.reset();assert(q.state().waiting==0);
}
