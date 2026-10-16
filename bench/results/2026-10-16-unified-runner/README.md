# Unified runner validation — October 16, 2026

RX 9070 XT 16 GiB, Ryzen 7 7800X3D, 32 GiB DDR5-4800, Linux. The authorized
−50 mV GPU offset remained in place; these runs do not establish undervolt
stability. One model worker at a time; 20 GiB cgroup ceiling, no scope swap,
physical RAM/VRAM guards. The normal 8096 server was unloaded during QA on 8097.

The unified AppImage contains native Strata plus the existing fast Vulkan
executable, a newly built ROCm-only llama app and the combined ROCm/Vulkan app.
External llama source revision: `a2878d30df0130dde503a7d9ba30d3d21bd71b9f`.
ROCm-only and combined were built with GCC 16.2.1; the retained Vulkan build
reports Clang 22.1.8. This is not a controlled comparison of compiler effects.

## Identical 8K coding prompt through the unified router

Saluki 27B abliterated IQ2-mix, 131,072 configured context, 8,136 actual input
tokens, Q8 KV, Flash Attention, microbatch 512, batch 2,048, 8 threads, one slot,
MTP off. Matching CPU vision projector loaded, but no image in the timed request.
Fit margins: Vulkan 2,048 MiB, ROCm 4,096 MiB. Same 768-token output ceiling;
all generated 333 tokens. Single fresh trials, not averages.

| Selected build | Prefill tok/s | Decode tok/s | Code checks |
|---|---:|---:|---:|
| Dedicated Vulkan | 1,280.9 | 47.44 | 13/13 |
| Dedicated ROCm | 698.6 | 12.60 | 13/13 |
| Combined, ROCm selected | 683.0 | 12.51 | 13/13 |

See `backend-comparison.json`, individual responses and checks. The identical
prompt is archived in the preceding native dense comparison. The compiled
ROCm-only build exposes ROCm0 without a Vulkan device (`rocm-devices.log`).
Splitting the build did not recover Saluki's Vulkan decode speed in this trial.
The router preserves approximately the earlier standalone Vulkan speed;
variation between single runs is not a demonstrated throughput improvement.

## Filled 128K validation

Through the unified router and dedicated Vulkan build, the same Saluki profile
with vision enabled completed 130,028 input tokens plus 339 output tokens in a
131,072-token window: **709.13 prefill / 34.50 decode tok/s**. A cached follow-up
processed 42 new tokens with 130,366 cached and decoded at **34.69 tok/s**.
All 13 coding checks and all three beginning/middle/end retrieval probes passed.
Minimum sampled headroom: 23.347 GiB available RAM and 1,838 MiB dedicated VRAM.
No memory guard stopped the run. The prompt SHA-256 matches the earlier comparison.
See `saluki-vulkan-128k/` for outputs, checks, exact prompt and memory summary.

This was one text-only filled-window trial with the CPU projector loaded. A full
128K window containing images, other quantizations, ROCm at this fill and 256K
were not validated by this run. Earlier native and standalone backend trials
remain separate evidence.

Native Swift and prepared Flash-Next also passed automatic routing and real
short requests after switching away from llama.cpp (`native-routing.json`).

## Compatibility and UI

Chat, streaming chat, Anthropic Messages, stateless Responses, an inline screenshot
and function tool calling passed on the Vulkan path. A JSON-schema type array
was accepted, remote screenshot URLs were refused, and a long request was
cancelled followed by a successful fresh request. No deliberate memory exhaustion
was used. Seven frontend CPU tests and HTTP low-memory refusal/auth/origin tests
passed. CUDA, SYCL and Windows were not built or tested.

The browser checks cover the six curated profiles, engine/device controls,
backend-specific Tune controls, editable paths plus a local file picker, desktop
and mobile layouts, and no JavaScript errors. Live rates are marked estimates
until final backend timings arrive. Streamed prompt-progress counters provide
exact processed/total counts when available; otherwise the total remains pending.

Model files were renamed within the same filesystem; sizes and inodes were
verified unchanged. The original `llama` executable retains its recorded SHA-256 hash. At the user's
request, saved profiles and eight model/projector paths in the external
`presets.ini` were migrated to canonical paths, then compatibility links were
removed. Its other settings were verified unchanged; original copies are backed
up locally. The AppImage does not bundle or read that external presets file.
`model-moves.json` records the individual moves; weights are not included.

The six profile JSON files here record this machine's curated configuration.
They contain local paths and are examples, not portable defaults. Swift's native
preference is bound to the exact model path and size; Flash-Next requires the
prepared matching expert pack. See [runner documentation](../../../docs/NATIVE_SERVER.md)
and [earlier full-context baselines](../2026-10-16-native-dense-comparison/README.md).
