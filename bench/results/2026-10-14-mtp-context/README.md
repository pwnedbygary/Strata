# Adaptive MTP storage checks and stopped full fill

October 14, 2026: RX 9070 XT 16 GiB, Ryzen 7800X3D, 32 GB RAM, ROCm 7.2.
Swift IQ3_XXS with its embedded MTP head, one greedy draft, int8 KV, prefill 512.

`report.json` compares 64 generated IDs and draft decisions after a 4,086-token prompt.
Fixed 16K, adaptive growth across 4K, and a full 256K cache grow/touch/evict/reset cycle
matched. The cycle evicted 380 matrices and restored all 408; logs are preserved.
This is internal storage/speculation validation, not external numerical reference parity.

`stopped-full-fill.json` records the separate 261,120-token retrieval attempt. At the user's
approved pivot to practical tests, it had processed 121,856 tokens in about 30 minutes.
It had not generated an answer. No full-window throughput or retrieval result is claimed.
The final sampled system available RAM was 13.277 GiB and physical free VRAM 1,290 MiB.
