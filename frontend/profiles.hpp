#pragma once
#include "common.h"
#include "json.h"
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <unistd.h>
namespace native_profiles {
namespace fs = std::filesystem;
inline fs::path executable_dir() { return fs::canonical("/proc/self/exe").parent_path(); }
inline common_json read(const fs::path &p) {
    std::ifstream file(p);
    if (!file)
        throw std::runtime_error("Cannot read local profile: " + p.string());
    auto j = common_json::parse_no_throw(std::string(std::istreambuf_iterator<char>(file), {}));
    if (!j.is_object())
        throw std::runtime_error("Invalid JSON profile: " + p.string());
    return j;
}
inline std::string path(std::string value, const fs::path &base, bool engine = false) {
    if (value.rfind("@bundle/", 0) == 0)
        return (executable_dir() / (engine ? "engines" : "") / value.substr(8)).string();
    if (value.rfind("~/", 0) == 0)
        value = std::string(std::getenv("HOME") ? std::getenv("HOME") : "") + value.substr(1);
    fs::path p(value);
    return p.is_absolute() ? p.string() : (base / p).lexically_normal().string();
}
inline std::string option(const std::vector<std::string> &args, const std::string &key,
                          const std::string &fallback = "") {
    std::string value = fallback;
    for (size_t i = 0; i + 1 < args.size(); ++i)
        if (args[i] == key)
            value = args[i + 1];
    return value;
}
inline common_json load(const fs::path &file) {
    auto cfg = read(file);
    auto base = file.parent_path();
    if (cfg.contains("cwd"))
        base = path(cfg.at("cwd").get<std::string>(), base);
    cfg["cwd"] = base.string();
    if (!cfg.contains("args") || !cfg.at("args").is_array())
        throw std::runtime_error("Profile needs engine args");
    for (auto &arg : cfg["args"]) {
        auto s = arg.get<std::string>();
        if (s.rfind("@bundle/", 0) == 0)
            arg = path(s, base);
    }
    if (cfg.contains("env"))
        for (auto it = cfg["env"].begin(); it != cfg["env"].end(); ++it) {
            auto value = it.value().get<std::string>();
            if (value.rfind("@bundle/", 0) == 0)
                it.value() = path(value, base);
        }
    // Native frontend defaults are opt-in with this executable; saved legacy profiles are untouched.
    if (cfg.contains("env") && cfg["env"].value("STRATA_Q35_ADAPTIVE_WEIGHTS", "0") == "1") {
        for (const char *key : {"STRATA_Q35_ATTN_HEAD_REUSE", "STRATA_Q35_PREFILL_LOAN",
                                "STRATA_Q35_ATTN_LT", "STRATA_Q35_TOKEN_BUFFER_LOAN"})
            if (!cfg["env"].contains(key)) cfg["env"][key] = "1";
        if (!cfg["env"].contains("STRATA_Q35_PHYSICAL_RESERVE_MIB"))
            cfg["env"]["STRATA_Q35_PHYSICAL_RESERVE_MIB"] = "2048";
    }
    if (cfg.contains("vision"))
        for (const char *key : {"model", "mmproj"})
            if (cfg["vision"].contains(key))
                cfg["vision"][key] = path(cfg["vision"][key].get<std::string>(), base);
    return cfg;
}
inline common_json metadata(const std::string &name, const common_json &cfg) {
    auto args = cfg.at("args").get<std::vector<std::string>>();
    auto r = cfg.value("router", common_json::object());
    long long ctx = std::stoll(option(args, "--max-context", "32768"));
    bool vision = cfg.contains("vision") && cfg["vision"].is_object();
    auto env = cfg.value("env", common_json::object());
    auto mtp = option(args, "--mtp", "off");
    return {
        {"id", name},
        {"object", "model"},
        {"owned_by", "local"},
        {"name", r.value("display_name", name)},
        {"description", r.value("description", std::string())},
        {"context_length", ctx},
        {"meta", {{"n_ctx", ctx}, {"max_output_tokens", ctx - 8}}},
        {"sampling_defaults", cfg.value("sampling", common_json::object())},
        {"model_architecture", cfg.value("arch", "qwen4exp")},
        {"local_files", {{"model", option(args, "--native")}, {"expert_pack", option(args, "--pack")},
                         {"mtp_head", mtp != "off" && mtp.find_first_not_of("0123456789") != std::string::npos ? mtp : ""},
                         {"projector", cfg.contains("vision") ? cfg["vision"].value("mmproj", "") : ""}}},
        {"max_output_tokens", ctx - 8},
        {"available", r.value("enabled", true)},
        {"strata", {{"backend", cfg.value("backend", "native")},
            {"kv_precision", option(args, "--kv", env.value("STRATA_Q35_KV_I8", "0") == "1" ? "int8" : "engine default")},
            {"mtp", mtp == "off" || mtp == "0" ? "off" : mtp == "1" || mtp == "2" || mtp == "3" || mtp == "4" ? mtp : "external head"},
            {"prefill_chunk", option(args, "--prefill", "auto")},
            {"adaptive_weights", env.value("STRATA_Q35_ADAPTIVE_WEIGHTS", "0") == "1"},
            {"vision_encoder", vision ? "CPU" : "off"},
            {"resident_ram_gib", option(args, "--resident-budget-gib", "auto")},
            {"physical_reserve_mib", env.value("STRATA_Q35_PHYSICAL_RESERVE_MIB", "not configured")}}},
        {"architecture",
         {{"input_modalities", vision ? common_json::array({"text", "image"}) : common_json::array({"text"})},
          {"output_modalities", common_json::array({"text"})}}},
        {"capabilities",
         {{"streaming", true}, {"tools", true}, {"vision", vision}, {"image_generation", false}}}};
}
} // namespace native_profiles
