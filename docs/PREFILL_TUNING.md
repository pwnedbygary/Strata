# RX 9070 XT dense prefill tuning

Measured October 14, 2026 on an RX 9070 XT 16 GiB, Ryzen 7800X3D, 32 GB RAM
at JEDEC 4800 MT/s, ROCm 7.2 / hipBLASLt version 100202. These are local trials,
not a guarantee for another GPU, library version or model.

The Flash Next calibration table contains 2560-wide projections. Saluki 27B has
5120-wide projections and a 17408-wide feed-forward layer. Its shapes were missing
from that table, so prefill fell back to rocBLAS. Calibrating those shapes selected
much faster hipBLASLt kernels without retaining expanded FP16 model weights.
The existing 32 MiB BLAS workspace and quantized weight storage stay in use.

| Saluki abliterated IQ2-mix, MTP on | Original table | Dense table |
| --- | ---: | ---: |
| Synthetic 4096-token native prefill | 167.9 tokens/s | 939.4–960.4 tokens/s, three runs |
| Counted 30,692-token coding prompt | 221.0 s / 138.9 tokens/s | 67.2 s / 456.9 tokens/s |
| Counted 63,428-token coding prompt | 534.6 s / 118.6 tokens/s | 258.9 s / 245.0 tokens/s |
| Coding answer decode | 32.8 tokens/s | 32.7 tokens/s |
| Cached review decode | 30.4 tokens/s | 31.3 tokens/s |

The 32K and 64K first answers were byte-identical to their saved baselines and passed the same
13 boundary checks. The follow-up wording differed; this is a different floating-point
GEMM implementation, not a promise of identical text for every prompt. The native
4K test uses synthetic token IDs and establishes speed only. The calibration tool
checked each selected kernel against rocBLAS using relative L2 <= 1e-4, max absolute
error <= 1e-2, finite outputs and output-padding canaries.

The tuned 32K run sampled at least 20.653 GiB available RAM and 2192 MiB physical free
VRAM. CPU Tctl peaked at 55.125 C, GPU junction at 72 C. Samples are one second apart
and can miss brief peaks. Earlier unexplained platform resets remain unresolved.
The configured 256K ceiling has not been fully filled and validated.

## Enable for the measured Saluki profile

Set this in the profile JSON's `env` object, then restart the router:

```json
"STRATA_HIPBLASLT_TUNING": "@bundle/tools/hip/gfx1201-qwen35-dense-hipblaslt-100202.txt"
```

The table ships in newly built AppImages. For a source checkout, use the absolute path
to `tools/hip/gfx1201-qwen35-dense-hipblaslt-100202.txt` instead. Keep prefill at 512,
int8 KV and the existing 128 MiB attention score budget. This is opt-in; the original
Flash table remains unchanged. Runtime checks reject a mismatched architecture/library
version and fall back to rocBLAS. Swift and other model quality/performance have not
been validated with this dense table.

To inspect another model's bottleneck, `STRATA_Q35_PROFILE_PREFILL=1` enables GPU event
timings for native dense prefill. `PROFILE_PREFILL` reports whole-layer, GDN, attention,
feed-forward and remaining projection time per chunk. It excludes warm-up, short decode
and speculative verification. Profiling is disabled by default and adds events and a
synchronization when enabled; turn it off for normal use. Events are freed per chunk.

Raw measurements: [prefill tuning results](../bench/results/2026-10-14-prefill-tuning/).
HIP was built and tested; CUDA and SYCL toolchains were unavailable and were not built.
