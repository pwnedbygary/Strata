# Saluki 27B native development results

October 14, 2026; RX 9070 XT 16 GiB / gfx1201, Ryzen 7800X3D, approximately 31 GiB RAM, ROCm 7.2. Strata development build based on 0.1.44, with the experimental native dense Qwen35 path. Original local file: `Underdog-Saluki-27B-1.0-IQ2-mix.gguf`, architecture `qwen35`. Model weights were not modified.

These records distinguish **configured context capacity** from **filled context**. The short API tests used 30 input tokens and 128/192 output tokens. Greedy, MTP off. They do not establish full-window decode speed or model quality.

- Q8-expanded 4K configuration: 33.4–33.6 decode tokens/s, serial runs.
- Original native weights, optimized kernels, int8 KV, 160K allocated: 32.9–33.4 decode tokens/s, short prompts.
- Fixed 256K allocation and 2.5 GiB GPU weight target: 3.5 decode tokens/s, short prompt. This wastes throughput on small requests by staging weights before the large cache is needed.
- Int8 KV versus FP16 KV at 3,546 input tokens / 17 forced positions: 17 top-token matches, mean KL 0.000117, max KL 0.000895. Internal engine comparison only.
- File-backed staging versus resident weights: all full-logit bytes identical at 17 forced positions. SHA-256 `df946c11ebdf22b87eb1933576eaa5dfea5c25c95fc6c04e50a2b74d259ac92f` for both records.
- Adaptive versus fixed storage with 4,246 input tokens, crossing initial 4K capacity: all 17 logit records byte-identical. Forced full 256K allocation/touch, eviction, reset to 4K, and restoration preserved the same logit bytes.

The maximum-memory cycle touched every allocated K/V byte, evicted more than 300 matrices and restored all 400 cached matrices on reset. That tests storage pressure/lifetimes; it does not run a 256K language prompt.

The interrupted near-full 160K prefill reached 72,704 of 163,610 input tokens in 1,284 seconds with the small attention buffer. It was stopped to improve late-context matrix shapes and memory headroom. No answer or full-window throughput was measured in that attempt.

See [configuration and limitations](../../../docs/DENSE_QWEN35.md). CUDA/SYCL builds and external full-model numerical parity were not performed. The installed Flash-Next executable/configuration remains available separately.

Final adaptive profile, 256K logical limit / 4K initial KV, prefill 512, attention score buffer 128 MiB: three short runs measured 32.9, 33.0 and 32.9 decode tokens/s. Systemd current/peak process-tree accounting after those requests was about 0.36 GiB. This excludes GPU allocations and may exclude global file cache not charged to the scope; it is not a claim about total system RAM.

A 4,086-token prompt plus 17 forced positions crossed KV growth during captured decode; its full logits remained byte-identical to fixed storage.

Practical Snake: 472 prompt tokens, 5,503 output tokens, stop finish reason, 32.3 decode tokens/s. The saved HTML ran with no page errors and passed 10/11 core checks; the paused manual-step behavior failed the benchmark contract. Generated artifacts are preserved unchanged. KV grew to16K during this generation, while all weights remained in VRAM. This is a functional check, not a full code-quality review.

## Generated game

[Unmodified playable HTML](snake.html) · [Generation and browser report](snake-report.json).
Screenshots capture the same output in a fresh browser with external network requests blocked.

![Paused game and controls](snake-paused.png)

![Running game](snake-playing.png)
