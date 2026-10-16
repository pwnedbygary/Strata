# Native dense engine and llama.cpp comparison — October 16, 2026

The completed comparison favors different engines for different models. Regular
llama.cpp Vulkan is fastest for Saluki at 128K. Native Strata decodes Swift faster
at 128K, while llama.cpp prefills it faster. These are single-machine, single-trial
configuration comparisons, not a claim that one engine is universally faster.

Hardware: Ryzen 7 7800X3D, RX 9070 XT 16 GiB (gfx1201), 32 GB system RAM running at
4800 MT/s, NVMe/Btrfs, CachyOS and ROCm 7.2. The user explicitly authorized keeping
the −50 mV GPU offset. These tests do not establish hardware stability.

One GPU model runs at a time. Text-only greedy generation uses Q8/int8 KV, a
131072-token context ceiling, 768 output tokens requested, reasoning disabled,
and the exact saved user prompts in `prompts/`. The 128K input contains 130028
rendered tokens; output is reserved within the same context window. Each fresh
request is followed by a review request reusing the existing prefix. All runs
are single trials, not multi-run averages. Two short ROCm MTP attempts interrupted
for UI work were discarded and rerun; their partial timings are not reported.

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

## Regular llama.cpp results

The following server is **llama.cpp on port 8098**, not Strata. Both use the same
GGUF and canonical prompts as the native runs above. Q8 KV is the primary comparison.

| Model / backend | Actual input | Prefill tok/s | Decode tok/s | Cached review tok/s | Code / retrieval |
| --- | ---: | ---: | ---: | ---: | --- |
| Saluki / original Vulkan | 8136 | 1246.2 | 49.68 | — | 13/13 · not probed |
| Saluki / original Vulkan | 130028 | 709.8 | 33.91 | 33.74 | 13/13 · 3/3 |
| Saluki / new ROCm | 8136 | 661.1 | 12.15 | — | 13/13 · not probed |
| Saluki / new ROCm | 130028 | 469.8 | 5.41 | 5.41 | 13/13 · 3/3 |
| Swift IQ3_S / original Vulkan | 8136 | 648.4 | 8.34 | — | 13/13 · not probed |
| Swift IQ3_S / original Vulkan | 130028 | 449.4 | 2.05 | 2.06 | 13/13 · 3/3 |
| Swift IQ3_S / new ROCm | 8136 | 850.1 | 6.45 | — | 13/13 · not probed |
| Swift IQ3_S / new ROCm | 130028 | 440.1 | 1.55 | 1.55 | 13/13 · 3/3 |

All four full-context llama.cpp runs completed without an external memory-guard
abort. Their minimum available system RAM was 19.876 GiB or higher; minimum free
dedicated VRAM ranged from 951 to 1541 MiB. Per-case commands, outputs, checks and
memory summaries are saved beside this document. The complete 8K tuning grid,
including explicitly experimental Q4 KV, is in `llama-tuning-summary.json`.

The grid is limited, not an exhaustive hardware optimum. Saluki and Swift Vulkan
selected Q8 / ubatch 512 / no speculation. Saluki ROCm selected the same; Swift
ROCm selected Q8 / ubatch 2048 / no speculation. Neither MTP nor Q4 is silently
enabled in the primary comparison. No 256K filled-window result is established.

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

## Interpreting the engine differences

“Native” describes the C++ server/runtime, not a guarantee of faster inference.
Both native Strata and llama.cpp execute compiled inference code. The native
server embeds this fork's dense engine; it does not send dense requests to
llama.cpp. The comparison llama.cpp server runs separately on port 8098.

These runs use the same GGUF and prompts but different internal kernels, KV
layouts and selected speculation settings. Strata grows its dense KV cache as
needed and evicts cached weight matrices to their file-backed source. llama.cpp
plans its cache/offload against the configured 128K ceiling at load time. This
can strongly favor native Strata on short Swift prompts while reducing its
advantage as the window fills. File-backed does not necessarily mean a physical
SSD read: Linux may already cache the mapped source in RAM.

The native dense prefill implementation in `attention_per_head()` expands int8
KV into FP16 scratch, computes attention scores, applies softmax and multiplies
values in separate operations. The llama.cpp runs explicitly enable Flash
Attention. This is a source-level reason to investigate the long-context prefill
gap; it is not a profiler measurement assigning a percentage of time to attention.
Weight movement, quantized matrix kernels and MTP verification also differ. The
winning llama.cpp Q8 cases may disable MTP while the recorded native profiles
use it. These are tuned-configuration comparisons, not isolated kernel A/B tests.

## Combined-build validation and installation

The additional combined-build Vulkan check used the same 8136-token prompt, Q8,
ubatch 512 and no speculation. Saluki measured 973.8 prefill / 23.83 decode tok/s,
versus the original executable's 1246.2 / 49.68. Swift measured 632.3 / 8.43, versus
648.4 / 8.34. Both passed 13/13 code checks. This regression is recorded rather
than replacing the faster original Saluki Vulkan path. The exact cause has not
been isolated; both compiler/build and runtime placement differ.

The original `~/.local/bin/llama` is retained byte-for-byte. The combined executable
is installed separately as `~/.local/bin/llama-dual`:

```sh
llama-dual serve --offline --model /absolute/path/model.gguf --device ROCm0
llama-dual serve --offline --model /absolute/path/model.gguf --device Vulkan0
```

Both devices and the embedded web UI were verified. `presets.ini` is unchanged,
SHA-256 `2980de050f88b6b5916ba0c4326a3dce0ab4c49b5966dc104cf406e2885bda6d`.
The installation does not replace the old preset paths or make the new combined
build faster than the original.

The exact native configurations are archived as `native-saluki-configuration.json`
and `native-swift-configuration.json`. Copies were added to the local registry as
`saluki27-128k-text` and `swift27-iq3-s-128k-text`, keeping every existing profile
and the vision default. Their filled-window measurements are text-only.
