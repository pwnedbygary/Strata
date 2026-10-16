#include "profiles.hpp"
#include <cassert>
#include <fstream>
int main() {
    char name[]="/tmp/strata-routing-XXXXXX";auto *tmp=mkdtemp(name);assert(tmp);std::filesystem::path dir(tmp);
    auto make=[&](const std::string &arch,int experts){auto path=dir/(arch+".gguf");auto *g=gguf_init_empty();gguf_set_val_str(g,"general.architecture",arch.c_str());gguf_set_val_u32(g,(arch+".expert_count").c_str(),experts);assert(gguf_write_to_file(g,path.c_str(),true));gguf_free(g);return path;};
    auto dense=make("qwen35",0),moe=make("qwen4exp",512),other=make("othermoe",64);
    common_json cfg={{"args",common_json::array({"--native",dense.string(),"--max-context","131072"})}};
    assert(native_backend::resolve(cfg)["engine"]=="llama");
    cfg["inference"]={{"auto_engine","strata"},{"auto_model",dense.string()},{"auto_size",std::filesystem::file_size(dense)}};
    assert(native_backend::resolve(cfg)["engine"]=="strata");
    cfg["args"][1]=other.string();assert(native_backend::resolve(cfg)["engine"]=="llama");
    cfg.erase("inference");
    cfg["args"][1]=other.string();assert(native_backend::resolve(cfg)["engine"]=="llama");
    cfg["args"][1]=moe.string();assert(native_backend::resolve(cfg)["engine"]=="llama");
    std::ofstream(dir/"index.txt")<<"test";cfg["args"].push_back("--pack");cfg["args"].push_back(dir.string());
    assert(native_backend::resolve(cfg)["engine"]=="strata");
    cfg["inference"]={{"engine","llama"},{"device","ROCm0"}};
    auto route=native_backend::resolve(cfg);assert(route["engine"]=="llama"&&route["device"]=="ROCm0"&&route["build"]=="rocm-only");
    std::filesystem::create_directories(dir/"llama-rocm/bin");std::ofstream(dir/"llama-rocm/bin/llama")<<"test";
    auto command=native_backend::command(cfg,"test",1234,dir);
    auto find=[&](const std::string &key){auto it=std::find(command.begin(),command.end(),key);assert(it!=command.end());return *++it;};
    assert(find("--device")=="ROCm0"&&find("--host")=="127.0.0.1"&&find("--ctx-size")=="131072");
    assert(std::find(command.begin(),command.end(),"--offline")!=command.end());
    assert(std::find(command.begin(),command.end(),"--no-mmproj")!=command.end());
    cfg["vision"]={{"mmproj","/local/mmproj.gguf"}};command=native_backend::command(cfg,"test",1234,dir);
    assert(std::find(command.begin(),command.end(),"--no-mmproj-offload")!=command.end());
    std::filesystem::remove_all(dir);std::puts("PASS: metadata detection, conservative MoE routing, explicit device, offline commands and CPU vision");
}
