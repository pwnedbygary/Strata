#include "router.hpp"
#include <cassert>
#include <fstream>
#include <future>
using namespace native_router;
int main(){
 char name[]="/tmp/strata-queue-XXXXXX";auto *tmp=mkdtemp(name);assert(tmp);fs::path dir(tmp);
 std::ofstream(dir/"model.json")<<R"({"args":["--native","/not-a-model.gguf"]})";
 std::ofstream(dir/"router.json")<<common_json({{"queue_requests",true},{"default","fake"},{"profiles",{{"fake",(dir/"model.json").string()}}}}).dump();
 httplib::Server backend;std::atomic<bool> release{false};std::atomic<int> running{0},peak{0};std::vector<int> order;std::mutex order_mutex;
 backend.Post("/v1/chat/completions",[&](const auto &req,auto &res){
  const int active=++running;peak=std::max(peak.load(),active);auto b=common_json::parse(req.body);
  {std::lock_guard<std::mutex> l(order_mutex);order.push_back(b["test_id"].template get<int>());}
  while(!release)std::this_thread::sleep_for(std::chrono::milliseconds(5));
  --running;
  if(b.value("stream",false))res.set_content("data: {\"choices\":[{\"delta\":{\"content\":\"ok\"}}]}\n\ndata: [DONE]\n\n","text/event-stream");
  else res.set_content("{\"choices\":[{\"message\":{\"content\":\"ok\"}}]}","application/json");
 });
 const int backend_port=backend.bind_to_any_port("127.0.0.1");assert(backend_port>0);std::thread bt([&]{backend.listen_after_bind();});
 Router router(dir/"router.json");router.ram_floor=-1;router.vram_floor=-256; // Fixture only: no model or GPU allocation.
 router.active="fake";router.active_metadata={{"inference",{{"engine","llama"}}}};router.port=backend_port;
 std::ofstream(dir/"legacy.json")<<common_json({{"default","fake"},{"profiles",{{"fake",(dir/"model.json").string()}}}}).dump();
 Router legacy(dir/"legacy.json");legacy.ram_floor=-1;legacy.vram_floor=-256;assert(!legacy.queue_enabled);
 httplib::Server http;http.new_task_queue=[] {return new httplib::ThreadPool(4,8,8);};
 http.Post("/v1/chat/completions",[&](const auto &req,auto &res){proxy_request(router,req,res);});
 http.Post("/legacy",[&](const auto &req,auto &res){proxy_request(legacy,req,res);});
 http.Get("/status",[&](const auto &,auto &res){res.set_content("ok","text/plain");});
 int port=http.bind_to_any_port("127.0.0.1");assert(port>0);std::thread ht([&]{http.listen_after_bind();});
 auto send=[&](int id){httplib::Client c("127.0.0.1",port);c.set_read_timeout(10);auto r=c.Post("/v1/chat/completions",common_json({{"model","fake"},{"test_id",id},{"stream",id!=2}}).dump(),"application/json");assert(r);return std::make_pair(r->status,r->body);};
 auto wait=[&](auto predicate){for(int i=0;i<1000;++i){if(predicate())return;std::this_thread::sleep_for(std::chrono::milliseconds(5));}assert(false);};
 std::vector<std::future<std::pair<int,std::string>>> results;
 results.push_back(std::async(std::launch::async,send,0));wait([&]{return running==1;});
 auto cancelled=std::async(std::launch::async,[&]{httplib::Client c("127.0.0.1",port);c.set_read_timeout(5);c.Post("/v1/chat/completions",httplib::Headers{},R"({"model":"fake","test_id":99,"stream":true})","application/json",[](const char *,size_t){return false;});});
 assert(cancelled.wait_for(std::chrono::seconds(5))==std::future_status::ready);cancelled.get();wait([&]{return router.request_queue.state().waiting==0;});
 for(int i=1;i<5;++i){results.push_back(std::async(std::launch::async,send,i));wait([&]{return router.request_queue.state().waiting==(size_t)i;});}
 assert(send(5).first==429);
 httplib::Client monitor("127.0.0.1",port);monitor.set_read_timeout(1);auto status=monitor.Get("/status");assert(status&&status->status==200);
 {std::unique_lock<std::mutex> busy(legacy.turn);httplib::Client c("127.0.0.1",port);auto r=c.Post("/legacy",R"({"model":"fake"})","application/json");assert(r&&r->status==429&&r->body.find("Model is busy; retry after the current request")!=std::string::npos);}
 release=true;
 for(int i=0;i<5;++i){auto r=results[i].get();assert(r.first==200);if(i!=2)assert(r.second.find(": waiting for model\n\n")!=std::string::npos&&r.second.find("[DONE]")!=std::string::npos);}
 assert(peak==1&&order==std::vector<int>({0,1,2,3,4}));wait([&]{return router.request_queue.state().bytes==0;});
 http.stop();ht.join();backend.stop();bt.join();router.active.clear();fs::remove_all(dir);
 std::puts("PASS: real router FIFO proxy, five admitted requests, sixth 429, SSE heartbeats, disconnected waiter removed, non-stream response, responsive monitor, one backend request at a time; no GPU model");
}
