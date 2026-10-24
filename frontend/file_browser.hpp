#pragma once
#include "profiles.hpp"
#include <algorithm>
#include <cctype>
#include <filesystem>
#include <stdexcept>
#include <vector>
namespace native_files {
inline common_json list(const std::string &requested, bool folders_only) {
    namespace fs = std::filesystem;
    const char *home_env = getenv("HOME");
    const fs::path home = home_env ? home_env : "/";
    fs::path path = requested.empty() ? home : fs::path(requested);
    if (!path.is_absolute()) throw std::runtime_error("Choose an absolute folder path");
    std::error_code ec;
    if (fs::is_regular_file(path, ec)) path = path.parent_path();
    path = fs::canonical(path, ec);
    if (ec || !fs::is_directory(path)) throw std::runtime_error("That folder is not available");
    fs::directory_iterator it(path, ec);
    if (ec) throw std::runtime_error("Cannot read that folder");
    std::vector<common_json> entries;
    bool truncated = false;
    size_t scanned = 0;
    const fs::directory_iterator end;
    for (; it != end; it.increment(ec)) {
        if (ec) throw std::runtime_error("Cannot finish reading that folder");
        if (++scanned > 20000 || entries.size() >= 1000) { truncated = true; break; }
        const auto &entry = *it;
        const auto name = entry.path().filename().string();
        if (name.empty() || name.front() == '.') continue;
        std::error_code type_error;
        const bool directory = entry.is_directory(type_error);
        if (type_error) continue;
        if (!directory) {
            if (folders_only || !entry.is_regular_file(type_error) || type_error) continue;
            auto ext = entry.path().extension().string();
            std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c) { return std::tolower(c); });
            if (ext != ".gguf") continue;
        }
        const auto bytes = directory ? 0 : entry.file_size(type_error);
        entries.push_back({{"name", name}, {"path", entry.path().string()},
            {"directory", directory}, {"bytes", type_error ? 0 : bytes}});
    }
    std::sort(entries.begin(), entries.end(), [](const auto &a, const auto &b) {
        if (a.at("directory") != b.at("directory")) return a.at("directory").template get<bool>();
        return a.at("name").template get<std::string>() < b.at("name").template get<std::string>();
    });
    return {{"path", path.string()}, {"parent", path.parent_path().string()},
        {"home", home.string()}, {"entries", entries}, {"truncated", truncated}};
}
} // namespace native_files
