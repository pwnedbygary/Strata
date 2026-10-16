#pragma once
#include "profiles.hpp"
#include <algorithm>
#include <set>
namespace native_tuning {
inline bool dense(const common_json &cfg) {
    return cfg.value("env", common_json::object()).value("STRATA_Q35_DENSE", "0") == "1";
}
inline void argument(common_json &cfg, const std::string &key, const std::string &value) {
    auto args = cfg.at("args").get<std::vector<std::string>>();
    std::vector<std::string> next;
    for (size_t i=0; i<args.size(); ++i) {
        if (args[i] == key) { if (i+1 < args.size()) ++i; continue; }
        next.push_back(args[i]);
    }
    if (!value.empty()) { next.push_back(key); next.push_back(value); }
    cfg["args"] = next;
}
inline long long integer(const common_json &value, long long low, long long high, const std::string &key) {
    if (!value.is_number_integer()) throw std::runtime_error(key + " must be an integer");
    const auto n=value.get<long long>();
    if(n<low||n>high) throw std::runtime_error(key + " must be " + std::to_string(low) + ".." + std::to_string(high));
    return n;
}
inline std::string local_path(const common_json &value, bool directory, bool gguf) {
    if(!value.is_string())throw std::runtime_error("File paths must be strings");
    auto text=value.get<std::string>();
    if(text.empty())return text;
    if(text.rfind("~/",0)==0)text=native_profiles::path(text,"/");
    std::filesystem::path path(text);
    if(!path.is_absolute())throw std::runtime_error("Use an absolute local file path");
    if(directory ? !std::filesystem::is_directory(path) : !std::filesystem::is_regular_file(path))
        throw std::runtime_error("Local path does not exist: " + text);
    if(gguf) {
        std::ifstream f(path,std::ios::binary);char magic[4]={};f.read(magic,4);
        if(std::string(magic,4)!="GGUF")throw std::runtime_error("File is not a GGUF: " + text);
    }
    return path.lexically_normal().string();
}
inline common_json apply(common_json cfg, const common_json &settings) {
    if(!settings.is_object()) throw std::runtime_error("Tuning settings must be an object");
    const bool d=dense(cfg);
    auto clean=settings;
    for(const char *key:{"llama_ubatch","llama_fit_target_mib","llama_mtp","llama_kv"})if(clean.contains(key)) {
        auto value=clean[key];
        if(std::string(key)=="llama_kv") {
            if(!value.is_string()||(value!="q8_0"&&value!="q4_0"&&value!="f16"))throw std::runtime_error("Unsupported llama KV type");cfg["inference"]["kv"]=value;
        }else if(std::string(key)=="llama_ubatch") {
            auto n=integer(value,128,4096,key);if(n%128)throw std::runtime_error("Microbatch must be a multiple of 128");cfg["inference"]["ubatch"]=n;
        }else if(std::string(key)=="llama_mtp")cfg["inference"]["mtp"]=integer(value,0,7,key);
        else cfg["inference"]["fit_target_mib"]=integer(value,1024,8192,key);
        clean.erase(key);
    }
    for(const char *key:{"engine_policy","compute_backend"})if(clean.contains(key)) {
        if(!clean[key].is_string())throw std::runtime_error("Engine selection must be text");
        auto value=clean[key].get<std::string>();
        if(std::string(key)=="engine_policy") {
            if(value!="auto"&&value!="strata"&&value!="llama")throw std::runtime_error("Unknown engine policy");
            cfg["inference"]["engine"]=value;
        } else {
            if(value!="vulkan"&&value!="rocm")throw std::runtime_error("Unknown compute backend");
            cfg["inference"]["device"]=value.rfind("rocm",0)==0?"ROCm0":"Vulkan0";
            cfg["inference"]["build"]="auto";
        }
        clean.erase(key);
    }
    if(clean.size()!=settings.size())return apply(cfg,clean);
    const std::set<std::string> shared={"context","prefill_chunk","memory_limit_gib","vision_threads","model_path","projector_path","vision_enabled"};
    const std::set<std::string> dense_keys={"mtp_depth","physical_reserve_mib","runtime_reserve_mib","attention_scratch_mib","vision_threads"};
    const std::set<std::string> moe_keys={"spec_window","cpu_workers","ram_cache_gib","vram_reserve_mib","kv_resident","kv_precision","tail_skip","pack_path","ple_path","mtp_path"};
    for(const char *key:{"model_path","projector_path","pack_path","ple_path","mtp_path"}) {
        if(!settings.contains(key))continue;
        if(d&&(std::string(key)=="pack_path"||std::string(key)=="ple_path"||std::string(key)=="mtp_path"))
            throw std::runtime_error("Expert/shard/head paths are only available for the MoE path");
        auto path=local_path(settings.at(key),std::string(key)=="pack_path"||std::string(key)=="mtp_path",
                             std::string(key)=="model_path"||std::string(key)=="projector_path"||std::string(key)=="ple_path");
        if(path.empty()&&std::string(key)=="model_path")throw std::runtime_error("Model path cannot be empty");
        if(std::string(key)=="projector_path") {
            if(path.empty()) {cfg.erase("vision");cfg.erase("native_vision_config");}
            else {cfg["vision"]["mmproj"]=path;cfg["vision"]["model"]=native_profiles::option(cfg["args"].get<std::vector<std::string>>(),"--native");}
        } else {
            if(std::string(key)=="pack_path"&&!path.empty()&&!std::filesystem::is_regular_file(std::filesystem::path(path)/"index.txt"))
                throw std::runtime_error("Expert pack must contain index.txt");
            if(std::string(key)=="mtp_path"&&!path.empty()&&!std::filesystem::is_regular_file(std::filesystem::path(path)/"dense.bin"))
                throw std::runtime_error("MTP head directory must contain dense.bin");
            argument(cfg,std::string(key)=="model_path"?"--native":std::string(key)=="pack_path"?"--pack":std::string(key)=="ple_path"?"--ple-gguf":"--mtp",path);
        }
    }
    if(cfg.contains("vision"))cfg["vision"]["model"]=native_profiles::option(cfg["args"].get<std::vector<std::string>>(),"--native");
    for(auto it=settings.begin();it!=settings.end();++it) {
        const auto key=it.key(); const auto &v=it.value();
        if(!shared.count(key)&&!(d?dense_keys:moe_keys).count(key))
            throw std::runtime_error("Unsupported setting for this engine: " + key);
        if(key=="model_path"||key=="projector_path"||key=="pack_path"||key=="ple_path"||key=="mtp_path"||key=="vision_enabled")continue;
        if(key=="context") argument(cfg,"--max-context",std::to_string(integer(v,4096,262144,key)));
        else if(key=="prefill_chunk") {
            auto n=integer(v,0,d?4096:8192,key);
            if(n && (n<128 || n%128)) throw std::runtime_error("Prefill chunk must be auto (0) or a multiple of 128");
            argument(cfg,"--prefill",n?std::to_string(n):"auto");
        } else if(key=="memory_limit_gib") cfg["router"]["memory_max_gib"]=integer(v,2,64,key);
        else if(key=="mtp_depth") argument(cfg,"--mtp",std::to_string(integer(v,0,7,key)));
        else if(key=="physical_reserve_mib"||key=="runtime_reserve_mib"||key=="attention_scratch_mib") {
            auto n=integer(v,key=="physical_reserve_mib"?1024:key=="runtime_reserve_mib"?1536:32,
                            key=="attention_scratch_mib"?256:8192,key);
            if(key=="attention_scratch_mib"&&n!=32&&n!=64&&n!=128&&n!=256)
                throw std::runtime_error("Attention scratch must be 32, 64, 128 or 256 MiB");
            cfg["env"][key=="physical_reserve_mib"?"STRATA_Q35_PHYSICAL_RESERVE_MIB":key=="runtime_reserve_mib"?"STRATA_Q35_RESERVE_MIB":"STRATA_Q35_ATTN_SCORE_MIB"]=std::to_string(n);
        } else if(key=="vision_threads") {
            if(!cfg.contains("vision"))throw std::runtime_error("This profile has no vision encoder");
            cfg["vision"]["threads"]=integer(v,1,64,key);
        } else if(key=="spec_window") argument(cfg,"--spec",std::to_string(integer(v,1,8,key)));
        else if(key=="cpu_workers") argument(cfg,"--pool-workers",std::to_string(integer(v,0,64,key)));
        else if(key=="ram_cache_gib") argument(cfg,"--resident-budget-gib",std::to_string(integer(v,0,24,key)));
        else if(key=="vram_reserve_mib") argument(cfg,"--vram-reserve-mib",std::to_string(integer(v,1536,8192,key)));
        else if(key=="kv_resident") argument(cfg,"--kv-resident",std::to_string(integer(v,20480,262144,key)));
        else if(key=="tail_skip") {
            const auto n=integer(v,0,7,key);
            if(n!=0&&n!=7)throw std::runtime_error("Tail skipping is either full routing (0) or rank 7");
            cfg["env"]["STRATA_ROUTE_TAIL_SKIP"]=std::to_string(n);
        } else if(key=="kv_precision") {
            if(!v.is_string())throw std::runtime_error("KV precision must be a string");
            auto kv=v.get<std::string>();
            if(kv!="int8"&&kv!="fp16"&&kv!="q4_0"&&kv!="k8v4")throw std::runtime_error("Unsupported KV precision");
            argument(cfg,"--kv",kv);
        }
    }
    if(settings.contains("vision_enabled")) {
        const auto &v=settings.at("vision_enabled");
        if(!v.is_boolean())throw std::runtime_error("Vision enabled must be true or false");
        if(v.get<bool>()&&!cfg.contains("vision"))throw std::runtime_error("Set a local projector path before enabling vision");
        if(v.get<bool>()) {
            auto args=cfg["args"].get<std::vector<std::string>>();
            if(std::find(args.begin(),args.end(),"--vision")==args.end())args.push_back("--vision");
            cfg["args"]=args;
        }
        if(!v.get<bool>()&&cfg.contains("vision")) {cfg["native_vision_config"]=cfg["vision"];cfg.erase("vision");}
        if(!v.get<bool>()) {
            auto args=cfg["args"].get<std::vector<std::string>>();
            args.erase(std::remove(args.begin(),args.end(),"--vision"),args.end());cfg["args"]=args;
        }
    }
    const auto args=cfg.at("args").get<std::vector<std::string>>();
    if(!d) {
        auto ctx=std::stoll(native_profiles::option(args,"--max-context","32768"));
        auto resident=std::stoll(native_profiles::option(args,"--kv-resident","0"));
        if(resident>ctx) {
            if(settings.contains("kv_resident"))throw std::runtime_error("GPU KV residency cannot exceed context");
            argument(cfg,"--kv-resident",ctx>=20480?std::to_string(ctx):"");
        }
    }
    return cfg;
}
inline common_json files(const common_json &cfg) {
    auto args=cfg.at("args").get<std::vector<std::string>>();
    auto v=cfg.value("vision",cfg.value("native_vision_config",common_json::object()));
    common_json result={{"model_path",native_profiles::option(args,"--native")},
        {"projector_path",v.value("mmproj","")}, {"vision_enabled",cfg.contains("vision")}};
    if(!dense(cfg)) {
        result["pack_path"]=native_profiles::option(args,"--pack");
        result["ple_path"]=native_profiles::option(args,"--ple-gguf");
        result["mtp_path"]=native_profiles::option(args,"--mtp");
    }
    return result;
}
inline common_json values(const common_json &cfg) {
    auto args=cfg.at("args").get<std::vector<std::string>>();
    auto env=cfg.value("env",common_json::object());
    auto numeric=[&](const std::string &key,long long fallback){
        auto v=native_profiles::option(args,key);
        try{return v.empty()||v=="auto"?fallback:std::stoll(v);}catch(...){return fallback;}
    };
    common_json result={{"context",numeric("--max-context",32768)}, {"prefill_chunk",numeric("--prefill",0)},
        {"memory_limit_gib",cfg.value("router",common_json::object()).value("memory_max_gib",20)}};
    if(dense(cfg)) {
        result["mtp_depth"]=numeric("--mtp",0);
        result["physical_reserve_mib"]=std::stoll(env.value("STRATA_Q35_PHYSICAL_RESERVE_MIB","2048"));
        result["runtime_reserve_mib"]=std::stoll(env.value("STRATA_Q35_RESERVE_MIB","1536"));
        result["attention_scratch_mib"]=std::stoll(env.value("STRATA_Q35_ATTN_SCORE_MIB","128"));
        if(cfg.contains("vision"))result["vision_threads"]=cfg["vision"].value("threads",4);
    } else {
        result["spec_window"]=numeric("--spec",4);result["cpu_workers"]=numeric("--pool-workers",0);
        result["ram_cache_gib"]=numeric("--resident-budget-gib",11);
        result["vram_reserve_mib"]=numeric("--vram-reserve-mib",3072);
        result["kv_resident"]=numeric("--kv-resident",32768);
        result["kv_precision"]=native_profiles::option(args,"--kv","int8");
        result["tail_skip"]=std::stoll(env.value("STRATA_ROUTE_TAIL_SKIP","7"));
    }
    auto route=native_backend::resolve(cfg);
    auto inference=cfg.value("inference",common_json::object());
    result["llama_ubatch"]=inference.value("ubatch",512);
    result["llama_fit_target_mib"]=inference.value("fit_target_mib",route["device"]=="ROCm0"?4096:2048);
    result["llama_mtp"]=inference.value("mtp",0);result["llama_kv"]=inference.value("kv","q8_0");
    result["engine_policy"]=route["policy"];
    result["compute_backend"]=route["preferred_compute"];
    return result;
}
} // namespace native_tuning
