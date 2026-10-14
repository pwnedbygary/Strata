# Flash Next / Gyro performance investigation

October 14, 2026. The [4070 Super report](https://www.reddit.com/r/Qwen_AI/comments/1x5mr7a/qwen_38_flash_next_running_at_12vram32gb_ram/)
claims roughly 900–1800 prefill tokens/s and 33–42 decode tokens/s with 12 GB VRAM,
32 GB RAM, Gyro-M/S, Q4 streamed KV and a 256K limit. Its author says the exact patches
and recipe will be released later. Raw prompts, outputs and patched commit are not
linked in that post yet. These are reported numbers, not reproduced RX 9070 XT results.

The [publisher's model card](https://huggingface.co/agentionai/Qwen3.8-Flash-Next-Gyro-GGUF)
lists 27.64 GiB of GPU weights for Gyro-S and 34.98 GiB for Gyro-M, compared with 43.80
GiB for GSQ-RCO IQ3_XXS. Its quality measurements are publisher results, not an independent
review. Smaller experts could reduce SSD traffic at our memory budget; this has not
been measured here. Download sizes are larger: 58.5 GB and 92.0 GB respectively because
they include a disk-backed n-gram table.

Gyro uses custom trellis expert types and activation rotations. Its TQ1_0/TQ2_0 filenames
are size classes, not stock llama.cpp compatibility. The [public Strata rc2 fork](https://github.com/agentionai/Strata/blob/rc2/docs/GYRO.md)
requires the matching agentionai llama.cpp dependency. It documents experimental HIP
builds for gfx1201, with end-to-end AMD validation on gfx1151, not our RX 9070 XT.
It is not a drop-in model-file replacement for this fork's existing IQ3_XXS engine.

Our current Flash profile uses IQ3_XXS, an 11 GiB resident expert budget, 3 GiB VRAM reserve,
int8 KV with 32K resident, a 128K ceiling and MTP drafting. The Reddit report instead
uses a 16 GiB RAM expert tier, Q4 KV, MTP off, suffix speculation and different weights.
Each setting needs a matched test; increasing the RAM tier alone can consume the worker's
20 GiB limit. More VRAM on AMD does not imply faster CUDA-specific kernels.

Next comparison: counted fresh coding prompts and cached follow-ups on the existing
IQ3_XXS model, followed by bounded memory/speed trials for prefill chunk sizing, MTP versus
suffix drafting and expert-cache allocation. Keep output correctness and fresh/cached
prompt times separate. Gyro should get an isolated compatibility/parity build before
large downloads or an advertised working profile. No Gyro weights have been downloaded
or performance reproduced on this system yet.
