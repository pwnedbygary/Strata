# Native dense engine and llama.cpp comparison — October 16, 2026

Work in progress: native results are recorded below; the llama.cpp comparison is
not complete. No claim of a dense-engine speedup over llama.cpp is established.

Hardware: Ryzen 7 7800X3D, RX 9070 XT 16 GiB (gfx1201), 32 GB system RAM running at
4800 MT/s, NVMe/Btrfs, CachyOS and ROCm 7.2. The user explicitly authorized keeping
the −50 mV GPU offset. These tests do not establish hardware stability.

One GPU model runs at a time. Text-only greedy generation uses Q8/int8 KV, a
131072-token context ceiling, 768 output tokens requested, reasoning disabled,
and the exact saved user prompts in `prompts/`. The 128K input contains 130028
rendered tokens; output is reserved within the same context window. Each fresh
request is followed by a review request reusing the existing prefix. All runs
are single trials, not multi-run averages.

The bounded code task repairs three Python functions and checks 13 cases. Three
unique checkpoint strings test retrieval from early, middle and late input.
Passing these checks is not a comprehensive code-quality or model-intelligence
assessment. Generation rates depend on the produced answer and cannot be treated
as guaranteed writing speed for arbitrary prompts.

| Native model | Actual input | Prefill tok/s | Decode tok/s | Cached review tok/s | Code checks |
| --- | ---: | ---: | ---: | ---: | ---: |
| Saluki abliterated IQ2-mix, MTP 2 | 8136 | 917.1 | 51.0 | 45.9 | 13/13 |
| Saluki abliterated IQ2-mix, MTP 2 | 130028 | 301.6 | 17.4 | 15.0 | 13/13 |
| Swift IQ3_S, MTP 1 | 8136 | 812.4 | 53.5 | 50.7 | 13/13 |
| Swift IQ3_S, MTP 1, larger reserve | 130028 | 259.0 | 4.65 | 4.61 | 13/13 |

Native dense settings: 512-token prefill chunks, adaptive low-bit GPU weights and
int8 KV. Saluki uses the existing head-reuse, token-buffer and prefill-loan paths.
Swift required those paths plus a 2048 MiB physical-VRAM reserve / 3072 MiB runtime
reserve for the long retry. Its 8K result used the earlier 1024 / 2048 MiB reserve;
it is not a short-context measurement of the larger-reserve configuration.

## Failed trials count too

The initial Swift native load with its older profile was stopped by the physical
VRAM guard. Enabling head reuse and buffer loans allowed startup and the 8K test,
but the first 128K attempt crossed the 512 MiB physical-VRAM floor (491 MiB sampled)
around the 53K cache capacity and was stopped. Available RAM stayed above 24 GiB.
This was a guard stop, not a completed long-context result or a kernel OOM.
The larger-reserve retry is recorded separately. No guard was lowered.

The workers have a 20 GiB/no-swap process boundary and a 3 GiB available-RAM /
512 MiB physical-VRAM external floor. Later frontend admission and cancellation
changes add softer margins above these floors; their separate refusal tests do
not deliberately exhaust real RAM or VRAM.

## llama.cpp methodology

The installed Vulkan executable is preserved before replacement, version
0.4.0-dev build 10909, commit `a2878d30df0130dde503a7d9ba30d3d21bd71b9f`, built
with Clang 22.1.8. The combined Vulkan/ROCm build uses that same source revision,
GCC 16.2.1 and gfx1201. Compiler/build differences limit conclusions attributing
all differences solely to Vulkan versus ROCm.

The tuning grid checks Q8 KV with ubatch 512 and 2048, then embedded MTP 2 with
ngram speculation. A separate short Q4-KV case is experimental and excluded from
selection of the primary 128K configuration. The fastest passing Q8 case by
fresh-request wall time is selected for each model/backend's 128K run. Reported
settings include model fit/offload, speculation and the memory guard. Vision is
disabled in both engines for the throughput comparison; screenshot compatibility
is tested separately on the native vision profile.

The user's `presets.ini` is preserved byte-for-byte. Its original 1 MiB fit target
is not used for these tests: the comparison reserves 2048 MiB with Vulkan and
4096 MiB with ROCm, whose runtime free-memory report differs from physical DRM
accounting on this machine. The external physical-VRAM floor is the same.
