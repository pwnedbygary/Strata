# Saluki at a filled 128K context

Measured October 14, 2026: RX 9070 XT 16 GiB, Ryzen 7800X3D, 32 GiB RAM,
JEDEC 4800 MT/s, Linux/HIP. Same local Saluki 27B IQ2-mix abliterated embedded-MTP
GGUF and identical 131,020-token coding/tool-log prompt in both Strata runs.
These are single runs, not stability guarantees or broad coding-quality evaluations.

| Strata configuration | Fresh prefill | Answer decode | Cached review decode |
| --- | ---: | ---: | ---: |
| Physical reserve, original attention/workspace, one draft | 91.5 tok/s / 1,431.2 s | 7.6 tok/s | 7.5 tok/s |
| Reused attention scratch, split reduction, returned prefill buffers, two drafts | 243.1 tok/s / 539.0 s | 18.6 tok/s | 16.6 tok/s |

Both generated the same 339-token first answer, passed 13 boundary checks, and copied
all three unique checkpoint IDs from the beginning, middle and end of the prompt.
The optimized follow-up reused 131,359 tokens and returned first content after 1.63 s.
Its sampled minimum was 1,025 MiB physical VRAM free and 23.189 GiB available RAM.
One-second samples can miss brief peaks. Neither run fills the configured 262,144-token ceiling.

The optimized settings remain opt-in:

```json
{
  "STRATA_Q35_ATTN_HEAD_REUSE": "1",
  "STRATA_Q35_PREFILL_LOAN": "1",
  "STRATA_Q35_KV_GROW_STEP": "4096",
  "STRATA_Q35_ATTN_SCORE_MIB": "256",
  "STRATA_Q35_RESERVE_MIB": "1536",
  "STRATA_Q35_PHYSICAL_RESERVE_MIB": "1024"
}
```

Use native dense low-bit, adaptive weights, adaptive MTP, int8 KV, prefill 512 and
`--mtp 2`, with the existing gfx1201 dense hipBLASLt table. The physical reserve
requires Linux AMD sysfs statistics for the selected HIP device. Keep the independent
router RAM and physical VRAM guards enabled. A runtime allocation's HIP free-memory
count can lead physical buffer retirement; the new allocator waits briefly after frees.

The optimized path dequantizes one KV head at a time, groups its query heads, splits
long value reductions, sizes decode partials to allocated KV capacity, and returns
prefill-only scratch/BLAS workspace before restoring weights for decode. At the end
of the initial fill, 0.14 GiB of weights remained file-backed; after follow-up growth,
0.28 GiB remained file-backed. This still limits generation speed.

Native storage-growth/reset checks retained all 64 generated token IDs and draft
acceptance counts. An isolated 131,072-position attention test reduced time from
871.3 to 223.6 ms, with relative L2 error 3.7e-6; this is a kernel result, not whole-model
throughput. HIP builds, the physical-statistics reader test and four CPU profile tests passed.
The rebuilt normal AppImage returned `ready` and passed two short changed-screenshot
OCR cases at 54.4–54.5 output tok/s; those are not long-context image tests. CUDA and SYCL
were not built on this machine. All new optimization flags default off.

This establishes usable text retrieval at 128K, but misses the desired 25–30 tok/s
and does not establish an overall speed advantage over upstream llama.cpp.

## Same-day upstream comparison

Official llama.cpp commit `a0e6dc7384edb8f5d927155e1d26c10b4a310e6d`, HIP gfx1201,
flash attention on, batch/ubatch 512, one slot, context 139264, q8_0 K/V (including
MTP), embedded two-draft MTP. Automatic GPU fitting with `--fit-target 2560` was
used after the forced-all-GPU configuration crossed the same 512 MiB physical VRAM
guard at startup. Both engines ran separately with a 20 GiB RAM scope, no swap,
a 3 GiB available-RAM floor and a 512 MiB physical VRAM floor.

| Engine | Fresh prefill | Answer decode | Cached review decode | Fresh total time |
| --- | ---: | ---: | ---: | ---: |
| Optimized Strata | 243.1 tok/s | 18.6 tok/s | 16.6 tok/s | 557.34 s |
| llama.cpp automatic fit | 522.5 tok/s | 3.15 tok/s | 2.84 tok/s | 358.09 s |

Identical prompt SHA256, actual chat input count 131020 and first-answer bytes (339
tokens); both passed 13 code checks and three checkpoint retrieval checks. The llama
Anthropic count endpoint reported 131060, while its chat usage reported 131020;
comparisons use chat usage. Both reused 131359 tokens for the follow-up.
Strata decoded about 5.9 times faster than this fitted baseline, but llama.cpp completed
the fresh request sooner because of its faster prefill. This is one automatic-fit
configuration, not an exhaustive llama.cpp tuning comparison. KV quantization differs:
Strata uses per-row int8 scales, llama.cpp q8_0 uses block scales. No claim is made
that their memory layouts or numerical precision are identical.

The updated normal Saluki MTP profile uses these settings. To generate them explicitly:

```sh
.venv/bin/python tools/local_model_profiles.py --saluki-abliterated --only saluki27-abliterated --saluki-128k-tuning
```

Rebuild the HIP engine and AppImage before enabling these flags on another checkout.
The normal upstream/default engine path remains unchanged unless flags are enabled.
 Screenshot-enabled
profiles still reset the text prefix for image requests, so screenshot-heavy long chats
can require another full prefill. No long-context image benchmark is claimed.

[Saved answers, timing reports and memory samples](../bench/results/2026-10-14-saluki-128k/).
