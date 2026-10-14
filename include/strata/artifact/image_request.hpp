#pragma once
// CPU validation of strata-vision SVE1 records and Qwen interleaved M-RoPE positions.
#include <array>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <string>
#include <vector>
#include <utility>

namespace strata::artifact {
struct ImageRequest {
    std::vector<float> rows;
    std::vector<int32_t> row_at;
    std::vector<std::array<int32_t, 3>> positions;
};
inline bool read_image_request(const std::string& file, const std::vector<int32_t>& ids,
                               int width, int context, int image_token, ImageRequest& out, std::string& err) {
    struct Image { int32_t n, nx, ny; size_t first; };
    constexpr size_t max_bytes = 512u << 20;
    std::ifstream in(file, std::ios::binary);
    if (!in) { err = "cannot open projected-image file"; return false; }
    if (width <= 0 || context <= 0 || ids.empty() || ids.size() > (size_t) context) {
        err = "invalid image request dimensions"; return false;
    }
    ImageRequest result;
    std::vector<Image> images;
    while (in.peek() != std::char_traits<char>::eof()) {
        int32_t h[5];
        if (!in.read(reinterpret_cast<char*>(h), sizeof h) || h[0] != 0x31455653 || h[1] <= 0 ||
            h[2] <= 0 || h[3] <= 0 || (int64_t)h[2]*h[3] != h[1] || h[4] != width ||
            h[1] > context || images.size() >= 64) {
            err = "invalid SVE1 header, grid or projected width"; return false;
        }
        const size_t count = (size_t)h[1] * (size_t)width;
        if (count > max_bytes / sizeof(float) || result.rows.size() > max_bytes / sizeof(float) - count) {
            err = "projected images exceed the 512 MiB request limit"; return false;
        }
        const size_t first = result.rows.size() / (size_t)width, old = result.rows.size();
        result.rows.resize(old + count);
        if (!in.read(reinterpret_cast<char*>(result.rows.data()+old), count*sizeof(float))) {
            err = "truncated projected-image rows"; return false;
        }
        for (size_t k=old; k<result.rows.size(); ++k) if (!std::isfinite(result.rows[k])) {
            err = "nonfinite projected-image value"; return false;
        }
        images.push_back({h[1],h[2],h[3],first});
    }
    if (images.empty()) { err = "empty projected-image file"; return false; }
    result.row_at.assign(ids.size(), -1);
    result.positions.resize((size_t)context);
    int32_t position=0;
    size_t i=0, image=0;
    while (i<ids.size()) {
        if (ids[i] != image_token) {
            result.positions[i++]={position,position,position}; ++position; continue;
        }
        if (image>=images.size()) { err = "more image placeholders than projected images"; return false; }
        const Image& im=images[image++];
        if ((size_t)im.n > ids.size()-i) { err = "too few image placeholders"; return false; }
        for (int j=0; j<im.n; ++j) {
            if (ids[i+j] != image_token) { err = "image placeholder run does not match its grid"; return false; }
            result.row_at[i+j]=(int32_t)(im.first+(size_t)j);
            result.positions[i+j]={position,position+j/im.nx,position+j%im.nx};
        }
        i+=(size_t)im.n; position+=std::max(im.nx,im.ny);
    }
    if (image!=images.size() || ids.back()==image_token) {
        err = "unused projected images or prompt ends inside an image"; return false;
    }
    for (; i<(size_t)context; ++i,++position) result.positions[i]={position,position,position};
    out=std::move(result);
    return true;
}
inline int image_rope_axis(int pair, const std::array<int,3>& sections) {
    const int sector=pair%(sections[0]+sections[1]+sections[2]);
    if (sector%3==1 && sector<3*sections[1]) return 1;
    if (sector%3==2 && sector<3*sections[2]) return 2;
    return 0;
}
} // namespace strata::artifact
