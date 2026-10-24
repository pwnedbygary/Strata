// Native dense Q2_K / IQ1_S: dequantization and row dots against pinned ggml.
#include "strata/kernels/iq_kernels.hpp"
#include "strata/kernels/native_mmvq.hpp"
#include "ggml.h"
#include <cuda_runtime.h>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>
#define CK(call) do { if ((call) != cudaSuccess) return 1; } while (0)
int main() {
    int count=0; if (cudaGetDeviceCount(&count)!=cudaSuccess || !count) return 77;
    cudaStream_t stream=nullptr; CK(cudaStreamCreate(&stream));
    int failed=0;
    for (int type : {10,19}) for (int cols : {256,512,2048}) for (int nt : {1,3,8}) {
        constexpr int rows=13;
        const auto* traits=ggml_get_type_traits((ggml_type)type);
        std::vector<float> orig(cols*rows), input(cols*nt), ref(cols*rows), decoded(cols*rows), output(rows*nt);
        for (size_t i=0;i<orig.size();++i) orig[i]=std::sin(i*.071f)*.7f;
        for (size_t i=0;i<input.size();++i) input[i]=std::cos(i*.11f)*.4f;
        size_t rb=ggml_row_size((ggml_type)type,cols);
        std::vector<uint8_t> packed(rb*rows);
        if (type==10) traits->from_float_ref(orig.data(),packed.data(),orig.size());
        else {
            for (size_t b=0;b<packed.size()/50;++b) {
                auto* p=packed.data()+50*b;
                p[0]=0; p[1]=0x30; // fp16 0.125
                for (int i=2;i<50;++i) p[i]=(uint8_t)(i*37+b*11);
            }
        }
        traits->to_float(packed.data(),ref.data(),ref.size());
        uint8_t* dw=nullptr; float *dx=nullptr,*dy=nullptr,*dd=nullptr; void* dq=nullptr;
        const size_t qb=strata::kernels::native_q8_1_bytes(cols,1);
        CK(cudaMalloc(&dw,packed.size())); CK(cudaMalloc(&dx,input.size()*4));
        CK(cudaMalloc(&dy,output.size()*4)); CK(cudaMalloc(&dd,decoded.size()*4)); CK(cudaMalloc(&dq,qb*nt));
        CK(cudaMemcpy(dw,packed.data(),packed.size(),cudaMemcpyHostToDevice));
        CK(cudaMemcpy(dx,input.data(),input.size()*4,cudaMemcpyHostToDevice));
        strata::kernels::native_quantize_q8_1(dx,dq,cols*nt,1,stream);
        strata::kernels::iq_dequant_f32(type,dw,ref.size(),dd,stream);
        strata::kernels::dense_lowbit_mmvq(type,dw,dq,dy,cols,rows,nt,stream);
        CK(cudaDeviceSynchronize());
        CK(cudaMemcpy(decoded.data(),dd,decoded.size()*4,cudaMemcpyDeviceToHost));
        CK(cudaMemcpy(output.data(),dy,output.size()*4,cudaMemcpyDeviceToHost));
        std::vector<uint8_t> q(qb*nt); CK(cudaMemcpy(q.data(),dq,q.size(),cudaMemcpyDeviceToHost));
        for (size_t i=0;i<ref.size();++i) if (std::abs(ref[i]-decoded[i])>1e-5f) { ++failed; break; }
        for (int t=0;t<nt;++t) for (int r=0;r<rows;++r) {
            double expected=0;
            for (int j=0;j<cols;++j) {
                const uint8_t* b=q.data()+t*qb+(j/32)*36; uint16_t bits;std::memcpy(&bits,b,2);
                const float act=ggml_fp16_to_fp32(bits)*(int8_t)b[4+j%32];
                expected+=(double)ref[r*cols+j]*act;
            }
            if (std::abs(expected-output[t*rows+r])>2e-4*(1+std::abs(expected))) ++failed;
        }
        CK(cudaFree(dw)); CK(cudaFree(dx)); CK(cudaFree(dy)); CK(cudaFree(dd)); CK(cudaFree(dq));
    }
    std::printf("dense low-bit parity: %s (%d failures)\n", failed?"FAILED":"passed",failed);
    CK(cudaStreamDestroy(stream));
    return failed?1:0;
}
