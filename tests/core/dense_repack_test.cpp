// Dense compatibility conversion: the exact pinned ggml Q8_0 output, original bytes unchanged.
#include "strata/kernels/cpu/native_expert.hpp"
#include "strata/artifact/gguf_reader.hpp"
#include "ggml.h"
#include <cmath>
#include <cstring>
#include <cstdio>
#include <vector>
int main() {
    constexpr int cols = 256, rows = 3;
    std::vector<float> x(cols * rows);
    for (size_t i = 0; i < x.size(); ++i) x[i] = std::sin((float) i * 0.17f) * 0.8f;
    int failed = 0;
    for (int type : {0, 1, 10, 14, 19, 30}) {
        const auto* traits = ggml_get_type_traits((ggml_type) type);
        const auto* q8 = ggml_get_type_traits(GGML_TYPE_Q8_0);
        const size_t source_row = ggml_row_size((ggml_type) type, cols);
        const size_t target_row = ggml_row_size(GGML_TYPE_Q8_0, cols);
        std::vector<uint8_t> source(source_row * rows), expected(target_row * rows), actual;
        if (type == 0) std::memcpy(source.data(), x.data(), x.size() * 4);
        else if (type == 19) {
            // IQ1_S's quantizer needs an importance matrix; a finite synthetic block tests its dequantizer.
            for (int r = 0; r < rows; ++r) {
                source[r * source_row] = 0; source[r * source_row + 1] = 0x3c; // fp16 scale 1
            }
        } else traits->from_float_ref(x.data(), source.data(), cols * rows);
        const auto before = source;
        std::vector<float> row(cols);
        for (int r = 0; r < rows; ++r) {
            if (type == 0) std::memcpy(row.data(), source.data() + r * source_row, cols * 4);
            else traits->to_float(source.data() + r * source_row, row.data(), cols);
            q8->from_float_ref(row.data(), expected.data() + r * target_row, cols);
        }
        std::string err;
        const bool ok = strata::kernels::cpu::dense_repack_q8(type, source.data(), cols, rows, actual, err);
        if (!ok || actual != expected || source != before) { ++failed; std::printf("type %d failed: %s\n", type, err.c_str()); }
    }
    std::vector<uint8_t> out;
    std::string err;
    if (strata::kernels::cpu::dense_repack_q8(0, nullptr, cols, rows, out, err)) ++failed;
    if (strata::kernels::cpu::dense_repack_q8(0, (const uint8_t*) x.data(), 255, rows, out, err)) ++failed;
    if (strata::kernels::cpu::dense_repack_q8(99, (const uint8_t*) x.data(), cols, rows, out, err)) ++failed;
    int elems = 0, bytes = 0;
    if (!strata::block_geometry(19, elems, bytes) || elems != 256 || bytes != 50) ++failed;
    std::printf("dense compatibility: %s\n", failed ? "FAILED" : "passed");
    return failed ? 1 : 0;
}
