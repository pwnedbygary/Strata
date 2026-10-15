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

## Further attention and decode-buffer tuning

A clean repeat with a constant reported 374 W GPU cap completed the same 131020-token
prompt. This describes the power cap, not confirmed stock voltage; voltage offset
was not recorded during those runs. The preceding exploratory run changed from a 250 W cap to unrestricted mid-run;
its 302.1 / 19.5 / 18.1 tok/s results are archived separately, not used for the comparison.

| Opt-in Strata preset | Fresh prefill | Answer decode | Cached review decode |
| --- | ---: | ---: | ---: |
| Previous head reuse / prefill loan | 243.1 tok/s / 539.0 s | 18.6 tok/s | 16.6 tok/s |
| Tuned attention / token-buffer loan | 302.3 tok/s / 433.4 s | 19.7 tok/s | 18.0 tok/s |

The new first answer was byte-identical and again passed 13 code checks and all three
retrieval checks. Both phases had all weights GPU-resident during generation. Shrinking
per-token work buffers from 512 rows to eight returned 325 MiB, preserving verification
rows and MTP hidden seeds. Buffers expand again for prefill, with weight placement and
graph pointers updated. Fixed/growing/reset native tests retained all 64 token IDs and
draft counts. The clean run sampled at least 1044 MiB free physical VRAM and 23.864 GiB
available RAM. Its cached review returned first content after 1.40 s.

These additional settings are enabled by `--saluki-128k-tuning` in the updated generator:

```json
{
  "STRATA_Q35_ATTN_LT": "1",
  "STRATA_Q35_TOKEN_BUFFER_LOAN": "1",
  "STRATA_HIPBLASLT_TUNING": "@bundle/tools/hip/gfx1201-qwen35-long-context-hipblaslt-100202.txt"
}
```

The attention path pads to already allocated KV capacity, zeroes future rows and keeps
causal masking. This stabilizes matrix shapes and permits split reductions on the final
partial chunk. The new table retains the original nine projection rows and adds 58
attention shapes. Every selected GEMM passed finite-output, relative L2, absolute-error
and padding-canary validation. Whole-attention numerical checks include 16383, 16385,
131020 and 131072 positions; maximum observed absolute error was 2.62e-7.

A separate experiment using this prefill GEMM path for single-row decode was rejected:
at 131020 positions it took 9.07 ms versus 4.26 ms for the existing decode kernel, and
relative L2 error 0.00212 exceeded the 0.0005 test limit. Production decoding retains the
original kernel. This is why the verified gain is mostly in prefill, despite eliminating
weight offload during decode. The 25–30 tok/s target remains unmet.

[Answers, timing, memory, calibration and rejected-probe evidence](../bench/results/2026-10-14-saluki-attention-lt/).

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

## Freeze investigation, October 15

The user reported a later hard freeze. The previous boot's persisted journal ends at
01:21 EDT without an orderly shutdown; no OOM kill, GPU timeout/reset or machine-check
fault was recorded near that end. The saved clean benchmark completed at 22:59 EDT
on October 14 and the AppImage build at 23:01. These times do not establish when or
why the machine froze. The current GPU reports a -50 mV offset, also present in the
active saved LACT profile. Its setting at the freeze is not established. An undervolt
is a plausible lead, not a confirmed diagnosis; driver, platform and application causes
are not excluded. No voltage, clock, fan or power settings were changed by this investigation.

The rebuilt normal router was restored with ten profiles and no GPU model loaded.
Its bundled dense executable has the same SHA256 as the measured source build.
The new AppImage's post-reboot GPU smoke test is deferred while the active undervolt
is unresolved. CPU profile checks, the physical-memory reader test and Python syntax
checks pass. CUDA and SYCL remain unbuilt on this machine.

Future context benchmarks record the boot ID, UTC start time, kernel release, reported
GPU voltage offset and power cap. Memory samples are flushed every second and synced
to disk every five seconds; a hard lock can still lose data. To refuse a new benchmark
before any model request when the reported voltage offset is nonzero or unavailable:

```sh
.venv/bin/python tools/coding_context_bench.py --model saluki27-abliterated-mtp-vision \
  --tokens 131072 --long-context-probes --require-zero-gpu-offset \
  --output local-tuning/stock-voltage-128k
```

This only checks the exposed GPU voltage offset at startup; it does not establish
stock CPU/RAM/clocks or guarantee stability. RAM/VRAM guards cannot prevent every
GPU or platform hard lock. [Kernel documentation for the voltage-offset interface](https://docs.kernel.org/gpu/amdgpu/thermal.html#pp-od-clk-voltage).
