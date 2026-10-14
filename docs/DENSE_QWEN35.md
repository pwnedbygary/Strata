# Experimental native Qwen35 27B support

This is Strata's own CUDA/HIP family driver, extended with dense SwiGLU layers. It is not a llama.cpp server wrapper. The installed Flash-Next executable and its tuned profile are retained.

Local validation hardware: RX 9070 XT 16 GiB (gfx1201), Ryzen 7800X3D, about 31 GiB RAM, ROCm 7.2, October 14, 2026. The development executable is `build-hip/strata`. HIP compiled and the synthetic family/layout, Q8 compatibility conversion and native Q2_K/IQ1_S GPU tests passed. CUDA/SYCL builds and external full-model numerical parity have not been performed.

## Formats and model layout

The local Swift 27B and Underdog-Saluki 27B files declare `qwen35`: 64 main layers, width 5120, dense feed-forward width 17408, 24 query heads / four KV heads, head width 256, and 3:1 Gated DeltaNet / attention layers. Their dense feed-forward path differs from Qwen35 MoE's routed experts. The local 0.8B file was used as an initial smoke test; its tied output embedding is supported.

Native Q2_K and IQ1_S projection kernels preserve those original GGUF weights. An earlier Q8_0 compatibility path expanded Saluki's GPU weights from about 7.41 GiB to 11.36 GiB; it is no longer needed for this file. Q8 compatibility remains a separate, explicit lossy opt-in for other files, leaving the original file untouched. The supplied 27B profile rejects files that would require that conversion.

Dense MTP weights are not loaded when MTP is off. The model's own tokenizer/chat template is exported from its GGUF. The mmproj file remains intact; this profile is text-only and does not claim image-input support.

## Context and memory

FP32 KV is the original family driver's mode. Dense opt-in FP16 and int8 KV reduce persistent cache storage. Int8 uses one FP32 scale per KV head/cell and per K/V vector; attention accumulates in FP32. A 3,546-token internal comparison with 17 teacher-forced positions agreed on every top token, with mean KL 0.000117 against FP16 KV. This compares cache formats within this native engine; it is not external reference parity or proof of long-context quality.

The dense attention score buffer and BLAS workspace are bounded. Prefill still creates temporary compact FP16 K/V operands. A larger score buffer trades VRAM for wider attention products; startup memory alone does not establish peak prefill memory.

Fixed file-backed placement targets a GPU weight budget, spreads misses across layers, and copies needed matrices through two 8 MiB pinned host buffers and one reusable device matrix buffer. The rest stays in the original memory-mapped GGUF. OS page cache may retain source pages and evict them under pressure; the runner does not pin a complete host weight copy. On Linux, mapped pages for GPU-resident tensors are released from the process's working set. File-backed placement disabled decode graphs because the host stages weights during execution.

In a 3,546-token internal comparison, resident and file-backed weight paths produced byte-identical full logits at all 17 positions. This tests transfer correctness, not model quality.

The adaptive variant is opt-in: KV storage starts small and grows with the actual conversation; GPU matrices move to file-backed staging only when memory becomes tight. Resetting a conversation shrinks KV and restores GPU matrices where space permits. The GPU allocator keeps a conservative 2.5 GiB reserve for other clients and runtime peaks; driver-resident reusable HIP blocks are not mistaken for live weights. Do not treat allocated maximum context or a short generation as a completed full-window benchmark.

## Measured trials

| Configuration | Allocated context | Short decode | Notes |
|---|---:|---:|---|
| Q8-expanded Saluki | 4K | 33.4–33.6 tokens/s | Coherent Python; fixed merge task violated its no-import rule |
| Original Saluki, first low-bit kernels, FP16 KV | 96K | 23.8–27.6 tokens/s | 7.41 GiB GPU weights; about 1.26 GiB free at initialization |
| Original Saluki, optimized low-bit kernels, int8 KV | 160K | 32.9–33.4 tokens/s | Short prompts only; initialized with about 1.47 GiB free |
| Fixed placement: about 2.57 GiB GPU weights, 4.84 GiB file-backed | 256K | 3.5 tokens/s | Loaded and generated; slow even on a short prompt |
| Adaptive KV/weights, original Saluki | 256K limit | 32.9–33.0 tokens/s | Short prompts; KV starts at 4K, process-tree RAM accounting about 0.36 GiB after load |

Short-rate measurements use 30 prompt tokens and 128 or 192 generated tokens, greedy, MTP off. These are not full-context decode rates. A near-full 160K prefill with the small score buffer was stopped after 72,704 of 163,610 input tokens: 1,284 seconds elapsed, 56.7 tokens/s average. It exposed narrow attention products and tight peak VRAM; no answer or full-window rate was measured in that attempt.

## Reproducing a profile

Build using [the HIP instructions](AMD_HIP.md), targeting gfx1201, then build `strata`, `dense_lowbit_test`, `dense_repack_test` and `model_family_test`. Only this development build advertises dense `qwen35` when `STRATA_Q35_DENSE=1` is enabled.

Export the tokenizer into a pack root (the export command adds `tokenizer/` itself):

```sh
.venv/bin/python tools/strata_tokenizer.py \
  --gguf /absolute/path/Underdog-Saluki-27B-1.0-IQ2-mix.gguf \
  --out /absolute/path/packs/saluki27-native
```

Prepare an opt-in profile from your existing HIP configuration:

```sh
.venv/bin/python tools/dense_profile.py prepare \
  --gguf /absolute/path/Underdog-Saluki-27B-1.0-IQ2-mix.gguf \
  --base-config strata-iq3_xxs.json \
  --tokenizer /absolute/path/packs/saluki27-native/tokenizer \
  --output strata-saluki27-adaptive.json \
  --context 262144 --prefill 512 --attention-score-mib 128
systemctl --user stop strata-local.scope
.venv/bin/python tools/dense_profile.py run --config strata-saluki27-adaptive.json
```

The adaptive configuration remains experimental. Its maximum-memory grow/evict/reset cycle touched all cache bytes, evicted more than 300 matrices, and restored all 400 cached matrices after shrinking to 4K. This is a storage-pressure test, not a 256K prompt-quality test. Fixed placement instead uses `--weight-vram-gib 2.5`; `--fixed-cache` retains fixed KV allocation without an explicit weight target. Context must not exceed the GGUF metadata limit. The launcher checks the model's geometry/known sizes and the engine capability, refuses a second active scope, binds to loopback unless an API key is supplied, and uses a 20 GiB scope with no scope swap plus a 1.5 GiB global available-RAM guard. Those controls cannot reserve GPU memory against other applications.

No full 256K prefill/quality result is claimed yet. Functional game results are recorded below; full code-quality review and higher-context language behavior still need separate checks. Keep the measured fast-short-prompt mode and maximum-context mode distinct.

Adaptive storage also passed a 4,246-token internal comparison crossing its initial 4K allocation: all 17 full-logit records were byte-identical to fixed storage. Forcing full 256K storage, touching every cache byte, evicting weights and resetting/restoring all 400 matrices preserved those same logits byte-for-byte. These checks exercise storage transitions; the full-length language-model prefill/quality test remains separate.

Growth during a captured decode graph was also tested: a 4,086-token prompt followed by 17 forced positions crossed the 4K boundary, with full logits byte-identical to fixed storage. [Raw results and limits](../bench/results/2026-10-14-native-saluki27/README.md).

The final adaptive profile finished the practical Snake task at 32.3 tokens/s (5,503 output tokens, 472 input). It passed 10/11 core browser checks with no page errors; its paused manual-step behavior failed. The saved output is preserved unchanged. During generation KV grew to16K while all weights stayed on the GPU. [Generated game and screenshot](../bench/results/2026-10-14-native-saluki27/README.md).
