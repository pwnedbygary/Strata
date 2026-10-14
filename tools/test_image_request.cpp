#include "strata/artifact/image_request.hpp"
#include <filesystem>
#include <iostream>
#include <limits>
#include <stdexcept>

using strata::artifact::ImageRequest;
int main() {
    const auto file = std::filesystem::temp_directory_path() / ("strata-image-test-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    auto write = [&](int width, int count, bool nan = false, bool truncate = false) {
        std::ofstream stream(file, std::ios::binary);
        int32_t header[] = {0x31455653, count, 2, 2, width};
        stream.write(reinterpret_cast<char*>(header), sizeof header);
        std::vector<float> values(truncate ? 1 : count*width, 0.25f);
        if (nan) values[0] = std::numeric_limits<float>::quiet_NaN();
        stream.write(reinterpret_cast<char*>(values.data()), values.size()*sizeof(float));
    };
    auto require = [](bool ok) { if (!ok) throw std::runtime_error("image request validation failed"); };
    try {
        ImageRequest request; std::string error;
        const std::vector<int32_t> ids = {7,99,99,99,99,8};
        auto read = [&]() { return strata::artifact::read_image_request(file.string(), ids, 3, 16, 99, request, error); };
        write(3,4); require(read());
        require(request.row_at == std::vector<int32_t>({-1,0,1,2,3,-1}));
        require(request.positions[1] == std::array<int32_t,3>{1,1,1});
        require(request.positions[4] == std::array<int32_t,3>{1,2,2});
        require(request.positions[5] == std::array<int32_t,3>{3,3,3});
        require(request.positions[6] == std::array<int32_t,3>{4,4,4});
        const auto rows = request.rows;
        write(4,4); require(!read() && request.rows == rows);
        write(3,3); require(!read()); // inconsistent grid
        write(3,4,true); require(!read());
        write(3,4,false,true); require(!read());
        write(3,4);
        require(!strata::artifact::read_image_request(file.string(), {7,99,99,8},3,16,99,request,error));
        require(!strata::artifact::read_image_request(file.string(), {7,99,99,99,99},3,16,99,request,error));
        const std::array<int,3> sections{11,11,10};
        require(strata::artifact::image_rope_axis(0,sections)==0);
        require(strata::artifact::image_rope_axis(1,sections)==1);
        require(strata::artifact::image_rope_axis(2,sections)==2);
        require(strata::artifact::image_rope_axis(29,sections)==2);
        require(strata::artifact::image_rope_axis(30,sections)==0);
        require(strata::artifact::image_rope_axis(31,sections)==1);
        std::filesystem::remove(file);
        std::cout << "image request validation passed\n";
    } catch (...) { std::filesystem::remove(file); throw; }
}
