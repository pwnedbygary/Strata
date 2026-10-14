# Native Qwen35 GSQ trial, October 14, 2026

RX 9070 XT 16 GiB, Ryzen 7800X3D, approximately 31 GiB RAM, ROCm 7.2. Development build from Strata 0.1.44 with the opt-in singleton shared-gate allowance and Qwen35 Q2_0 CPU activation-pointer fix. HIP compiled; CUDA/SYCL builds and reference-logit parity were not performed.

Model: chtisgit/Qwen3.6-35B-A3B-2Bit-GSQ-hybrid-GGUF, revision `526e747844ac1bc2ae1ce5f771a0af366eeb13ef`, metadata-only copy declaring no MTP. Context 8192, prompt chunk 256, expert VRAM budget 6 GiB, MTP off, CPU threads argument 7 (engine logs eight threads including caller), hipBLASLt tuning inherited from the existing hardware profile. Loopback API, 20 GiB scope limit, no scope swap, 1.5 GiB global available-RAM guard.

| Task | Prompt tokens | Output tokens | Decode tokens/s | Result |
|---|---:|---:|---:|---|
| Short sorted-list prompt, trial 0 | 30 | 192 | 84.1 | Truncated at requested limit |
| Short sorted-list prompt, trial 1 | 30 | 192 | 93.9 | Truncated at requested limit |
| Short sorted-list prompt, trial 2 | 30 | 192 | 92.5 | Truncated at requested limit |
| Fixed merge-intervals coding task | 308 | 376 | 89.7 | Finished; all 11 supplied checks passed |

Short prompts differ by trial index; this is not an identical-prompt reproducibility test. Median short decode rate: 92.5 tokens/s. The practical prompt comes from `bench/practical/merge_intervals.txt`, suite v1, seed 20261013, temperature zero. API timings exclude non-generation overhead. These figures do not establish quality beyond the supplied checks, full-context performance, or a fair comparison with the much larger Flash-Next model.

Engine allocation logs: 4.77 GiB GPU dense weights, 5.57 GiB GPU expert cache, 8.44 GiB pinned host expert weights, 0.42 GiB prompt staging. Systemd reported approximately 12.1 GiB current memory and 15.6 GiB startup peak after the short/merge tests; these are process-tree accounting, not total system usage.

The installed Flash-Next executable and its configuration were not replaced. This development server uses `build-hip/strata`.

Snake task: 472 prompt tokens, 3,089 generated tokens, stop finish reason, 87.7 decode tokens/s. Initial browser launch failed because the tool used the default Playwright cache path. Rechecking the saved artifact with this workspace's existing browser installation passed all 11 core checks, with no page errors (see `snake-browser-recheck.json`). The original report retains the launch failure for transparency. These checks do not constitute a full code-quality review or the later targeted revision checks used for Flash-Next.
