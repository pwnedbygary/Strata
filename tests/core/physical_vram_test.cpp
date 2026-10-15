#include "strata/core/physical_vram.hpp"
#include <chrono>
#include <filesystem>
#include <fstream>
#include <stdexcept>

int main() {
    namespace fs = std::filesystem;
    const auto dir = fs::temp_directory_path() / ("strata-vram-" +
        std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    fs::create_directory(dir);
    struct Cleanup { fs::path dir; ~Cleanup() { fs::remove_all(dir); } } cleanup{dir};
    auto write = [&](const char* name, const char* value) { std::ofstream(dir / name) << value; };
    auto read = [&] { return strata::core::physical_vram_free(dir.string()); };
    auto require = [](bool pass) { if (!pass) throw std::runtime_error("physical VRAM reader regression"); };
    require(!read());
    write("mem_info_vram_total", "17179869184\n");
    write("mem_info_vram_used", "1073741824\n");
    require(read() && *read() == 16106127360ull);
    for (const char* bad : {"-1", "invalid", "0 extra", "18446744073709551616", "17179869185"}) {
        write("mem_info_vram_used", bad); require(!read());
    }
    write("mem_info_vram_used", "0");
    write("mem_info_vram_total", "0"); require(!read());
    write("mem_info_vram_total", "1"); require(read() && *read() == 1);
}
