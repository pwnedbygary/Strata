#include "tuning.hpp"
#include "config_store.hpp"
#include <cassert>
#include <sys/stat.h>
int main() {
    auto dense=common_json::parse(R"({"args":["--native","model.gguf","--max-context","131072","--mtp","2"],"env":{"STRATA_Q35_DENSE":"1"},"router":{}})");
    auto original=dense.dump_safe();
    auto next=native_tuning::apply(dense,common_json::parse(R"({"context":196608,"mtp_depth":1,"prefill_chunk":1024,"physical_reserve_mib":2048})"));
    auto values=native_tuning::values(next);
    assert(values["context"].get<int>()==196608&&values["mtp_depth"].get<int>()==1);
    assert(dense.dump_safe()==original);
    for(const char* bad:{R"({"physical_reserve_mib":0})",R"({"context":999999})",R"({"prefill_chunk":123})",R"({"memory_limit_gib":1})",R"({"kv_precision":"q4_0"})",R"({"context":true})",R"({"vision_threads":8})",R"({"unknown":3})"}) {
        bool refused=false;try{native_tuning::apply(dense,common_json::parse(bad));}catch(...){refused=true;}assert(refused);
    }
    auto moe=common_json::parse(R"({"args":["--native","model.gguf","--max-context","131072","--kv-resident","32768","--mtp","/local/head"],"env":{},"router":{}})");
    auto tuned=native_tuning::apply(moe,common_json::parse(R"({"context":16384,"kv_precision":"int8","cpu_workers":0})"));
    assert(native_profiles::option(tuned["args"].get<std::vector<std::string>>(),"--mtp")=="/local/head");
    assert(native_profiles::option(tuned["args"].get<std::vector<std::string>>(),"--kv-resident").empty());
    bool refused=false;try{native_tuning::apply(moe,common_json::parse(R"({"context":32768,"kv_resident":65536})"));}catch(...){refused=true;}assert(refused);
    char tmp[]="/tmp/strata-tuning-test-XXXXXX";auto dir=::mkdtemp(tmp);assert(dir);
    auto model=std::filesystem::path(dir)/"test.gguf";
    {std::ofstream f(model,std::ios::binary);f.write("GGUF",4);f << std::string(20, '\0');}
    auto paths=common_json::object();paths["model_path"]=model.string();paths["projector_path"]=model.string();paths["vision_enabled"]=true;
    auto with_paths=native_tuning::apply(dense,paths);
    assert(with_paths.contains("vision"));
    paths["vision_enabled"]=false;
    assert(!native_tuning::apply(dense,paths).contains("vision"));
    paths["model_path"]="https://example.invalid/model.gguf";
    refused=false;try{native_tuning::apply(dense,paths);}catch(...){refused=true;}assert(refused);
    auto path=std::filesystem::path(dir)/"saved.json";
    native_config::save(next,path);assert(native_profiles::read(path).dump_safe()==next.dump_safe());
    struct stat st{};assert(::stat(path.c_str(),&st)==0&&(st.st_mode&0777)==0600);
    native_config::save(dense,path);assert(native_profiles::read(path).dump_safe()==original);
    std::filesystem::remove_all(dir);
    std::puts("PASS: validated per-engine tuning, source preservation, KV bounds and atomic private storage");
}
