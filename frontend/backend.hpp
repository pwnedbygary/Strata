#pragma once
#include "json.h"
#include "gguf.h"
#include "memory_policy.hpp"
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <algorithm>
#include <stdexcept>
#include <mutex>
#include <map>
#include <string>
#include <vector>
namespace native_backend {
namespace fs = std::filesystem;
inline std::string arg(const common_json &cfg,const std::string &key,const std::string &fallback="") {
    auto args=cfg.at("args").get<std::vector<std::string>>();std::string value=fallback;
    for(size_t i=0;i+1<args.size();++i)if(args[i]==key)value=args[i+1];return value;
}
inline common_json inspect(const std::string &file) {
    static std::mutex mutex;static std::map<std::string,std::pair<fs::file_time_type,common_json>> cache;
    std::lock_guard<std::mutex> lock(mutex);std::error_code ec;auto stamp=fs::last_write_time(file,ec);
    if(ec)return {{"architecture","unknown"},{"experts",0},{"detected",false}};
    if(cache.count(file)&&cache[file].first==stamp)return cache[file].second;
    gguf_init_params params{true,nullptr};auto *g=gguf_init_from_file(file.c_str(),params);
    if(!g)return {{"architecture","unknown"},{"experts",0},{"detected",false}};
    auto arch_key=gguf_find_key(g,"general.architecture");std::string arch=arch_key>=0&&gguf_get_kv_type(g,arch_key)==GGUF_TYPE_STRING?gguf_get_val_str(g,arch_key):"unknown";
    auto key=gguf_find_key(g,(arch+".expert_count").c_str());uint64_t count=0;
    if(key>=0) {auto type=gguf_get_kv_type(g,key);if(type==GGUF_TYPE_UINT32)count=gguf_get_val_u32(g,key);else if(type==GGUF_TYPE_UINT64)count=gguf_get_val_u64(g,key);}
    auto integer=[&](const std::string &key,uint64_t fallback=0ULL){auto k=gguf_find_key(g,key.c_str());if(k<0)return fallback;auto t=gguf_get_kv_type(g,k);return t==GGUF_TYPE_UINT16?(uint64_t)gguf_get_val_u16(g,k):t==GGUF_TYPE_UINT32?(uint64_t)gguf_get_val_u32(g,k):t==GGUF_TYPE_UINT64?gguf_get_val_u64(g,k):fallback;};
    const auto blocks=integer(arch+".block_count"),mtp_layers=integer(arch+".nextn_predict_layers");
    const auto layers=blocks>mtp_layers?blocks-mtp_layers:blocks;
    std::vector<uint64_t> experts_by_layer(std::min<uint64_t>(layers,1024),0);
    for(int64_t i=0;i<gguf_get_n_tensors(g);++i){std::string n=gguf_get_tensor_name(g,i);int layer=-1;if(n.find("_exps.")!=std::string::npos&&std::sscanf(n.c_str(),"blk.%d.",&layer)==1&&layer>=0&&(size_t)layer<experts_by_layer.size())experts_by_layer[layer]+=gguf_get_tensor_size(g,i);}
    const auto split_count=integer("split.count",1);
    const auto interval=std::max<uint64_t>(1,integer(arch+".full_attention_interval",1));
    const auto heads=integer(arch+".attention.head_count_kv"),key_dim=integer(arch+".attention.key_length"),value=integer(arch+".attention.value_length",key_dim);
    const uint64_t kv_token=(key_dim+value)*heads*2*((layers+interval-1)/interval);
    gguf_free(g);common_json result={{"architecture",arch},{"experts",count},{"detected",true},{"layers",layers},{"weights_bytes",fs::file_size(file)},{"split_count",split_count},{"expert_layer_bytes",experts_by_layer},{"kv_fp16_bytes_per_token",kv_token}};
    if(cache.size()>128)cache.clear();cache[file]={stamp,result};return result;
}
inline common_json resolve(const common_json &cfg) {
    auto settings=cfg.value("inference",common_json::object());auto policy=settings.value("engine","auto");
    if(policy!="auto"&&policy!="strata"&&policy!="llama")throw std::runtime_error("Unknown engine policy");
    auto info=inspect(arg(cfg,"--native"));auto pack=arg(cfg,"--pack");
    bool tiered=info.value("architecture","")=="qwen4exp"&&info.value("experts",0)>0&&fs::is_regular_file(fs::path(pack)/"index.txt");
    if(tiered&&fs::is_regular_file(fs::path(pack)/"experts.bin.src.json")) {
        std::ifstream f(fs::path(pack)/"experts.bin.src.json");std::string bytes((std::istreambuf_iterator<char>(f)),{});
        auto manifest=common_json::parse_no_throw(bytes);bool match=false;
        if(manifest.is_object()&&manifest.contains("shards"))for(const auto &shard:manifest["shards"])
            if(shard.value("name",std::string())==fs::path(arg(cfg,"--native")).filename().string()&&shard.value("size",0ULL)==fs::file_size(arg(cfg,"--native")))match=true;
        tiered=match;
    }
    std::error_code size_error;auto model_size=fs::file_size(arg(cfg,"--native"),size_error);
    bool measured=!size_error&&settings.value("auto_model",std::string())==arg(cfg,"--native") && settings.value("auto_size",0ULL)==model_size;
    auto automatic=tiered?std::string("strata"):measured?settings.value("auto_engine",std::string("llama")):std::string("llama");
    if(automatic!="strata"&&automatic!="llama")throw std::runtime_error("Invalid automatic engine preference");
    std::string engine=policy=="auto"?automatic:policy;
    auto device=settings.value("device","Vulkan0");
    if(device!="Vulkan0"&&device!="ROCm0")throw std::runtime_error("Unknown compute device");
    return {{"policy",policy},{"engine",engine},{"automatic_engine",automatic},{"preferred_compute",device=="ROCm0"?"rocm":"vulkan"},{"device",engine=="llama"?device:cfg.value("backend","hip")},
        {"build",engine=="llama"?(device=="Vulkan0"?"tuned-vulkan":"rocm-only"):"native"},
        {"reason",policy!="auto"?"Explicit engine selection":tiered?"Compatible Flash-Next GGUF and prepared expert pack":automatic=="strata"?"Measured native preference for this dense profile":"Dense or unverified MoE architecture: llama.cpp"},
        {"model",info}};
}
inline std::vector<std::string> command(const common_json &cfg,const std::string &name,int port,const fs::path &bin) {
    auto r=resolve(cfg);auto settings=cfg.value("inference",common_json::object());
    const auto cpu=settings.value("cpu_moe",0);const bool fit=settings.value("fit",true);
    if(settings.value("mtp",0)>0&&r["model"].value("experts",0)>0)throw std::runtime_error("llama.cpp MoE MTP is disabled after a Vulkan device-loss trial; use MTP off. Native Strata MTP is separate.");
    if(cpu>0&&fit)throw std::runtime_error("Explicit CPU expert placement requires Fit off");
    if(!fit) {
        auto info=r["model"];if(info.value("split_count",1ULL)>1)throw std::runtime_error("Manual placement estimation does not cover multiple GGUF shards; use Fit");if(!info.value("kv_fp16_bytes_per_token",0ULL))throw std::runtime_error("Cannot verify manual placement memory for this architecture; use Fit");
        if(settings.value("mtp",0)>0)throw std::runtime_error("Manual placement with llama.cpp MTP is not memory-validated; disable MTP or use Fit");
        auto weights=info.value("weights_bytes",0ULL);uint64_t cpu_weights=0;auto per_layer=info["expert_layer_bytes"].get<std::vector<uint64_t>>();
        for(int i=0;i<cpu&&i<(int)per_layer.size();++i){auto bytes=std::min<uint64_t>(weights,per_layer[i]);weights-=bytes;cpu_weights+=bytes;}
        const auto kv=settings.value("kv",std::string("q8_0"));double ratio=kv=="f16"?1.0:kv=="q4_0"?.28125:.53125;
        auto needed=weights+(uint64_t)(info["kv_fp16_bytes_per_token"].get<uint64_t>()*std::stoull(arg(cfg,"--max-context","131072"))*ratio)+2*native_memory::GiB;
        auto memory=native_memory::snapshot();if(cpu_weights+4*native_memory::GiB>memory.available||(memory.gtt_free>=0&&cpu_weights+2816*native_memory::MiB>(uint64_t)memory.gtt_free))throw std::runtime_error("Manual CPU experts exceed conservative RAM/GTT budget; reduce CPU expert layers or use Fit");if(memory.vram_free<0||(uint64_t)memory.vram_free<needed)throw std::runtime_error("Manual placement exceeds conservative VRAM budget (weights + KV + 2 GiB workspace/headroom); increase CPU expert layers or enable Fit");
    }
    auto file=r["build"]=="rocm-only"?bin/"llama-rocm/bin/llama":bin/"llama-vulkan";
    if(!fs::is_regular_file(file))throw std::runtime_error("Bundled llama.cpp executable is missing");
    std::vector<std::string> cmd={"env","-u","LLAMA_ARG_MODEL","-u","LLAMA_ARG_MODELS_PRESET","-u","LLAMA_ARG_DEVICE",
        "LD_LIBRARY_PATH="+(r["build"]=="rocm-only"?(bin/"llama-rocm/bin").string()+":/opt/rocm/lib":std::string("/opt/rocm/lib")),file.string(),"serve","--model",arg(cfg,"--native"),"--alias",name,
        "--host","127.0.0.1","--port",std::to_string(port),"--offline","--no-ui","--slots","--metrics","--parallel","1","--threads","8","--threads-batch","8",
        "--ctx-size",arg(cfg,"--max-context","131072"),"--device",r["device"].get<std::string>(),"--flash-attn","on",
        "--cache-type-k",settings.value("kv","q8_0"),"--cache-type-v",settings.value("kv","q8_0"),"--batch-size","2048",
        "--ubatch-size",std::to_string(settings.value("ubatch",512)),"--fit",fit?"on":"off","--fit-target",std::to_string(settings.value("fit_target_mib",r["device"]=="ROCm0"?4096:2048)),
        "--cache-ram","0","--spec-type",settings.value("mtp",0)>0?"draft-mtp":"none","--spec-draft-n-max",std::to_string(std::max(1,settings.value("mtp",0)))};
    if(!fit)cmd.insert(cmd.end(),{"--n-gpu-layers","all"});
    if(cpu>0)cmd.insert(cmd.end(),{"--n-cpu-moe",std::to_string(cpu),"--load-mode","none"});
    if(cfg.contains("vision")){cmd.insert(cmd.end(),{"--mmproj",cfg["vision"].at("mmproj").get<std::string>(),"--no-mmproj-offload"});}
    else cmd.push_back("--no-mmproj");
    return cmd;
}
}
