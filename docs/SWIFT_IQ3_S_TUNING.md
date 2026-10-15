# Swift IQ3_S with embedded MTP

October 14, 2026: RX 9070 XT 16 GiB, Ryzen 7800X3D, 32 GB JEDEC 4800 RAM,
ROCm 7.2 / hipBLASLt 100202. The existing
`Swift-1.5-Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf` is used directly; no conversion or new
model download. The matching Swift CPU image encoder remains enabled.

All these trials use the new dense prefill calibration, prefill 512, int8 KV and an
adaptive 262,144-token ceiling. The counted prompts repair three functions amid
repeated archived code/tool logs, then review the answer using its cached prefix.
This is a controlled synthetic coding workload, not a complete agent evaluation.

| Trial | Fresh prefill tokens/s | Answer tokens/s | Cached review tokens/s | Weights file-backed after fill |
| --- | ---: | ---: | ---: | ---: |
| 7,628 tokens, MTP off, original memory settings | 810.1 | 9.5 | 9.8 | 1.11 GiB |
| 7,628 tokens, one MTP draft, original memory settings | 753.8 | 15.0 | 14.1 | 1.53 GiB |
| 7,628 tokens, MTP off, finer growth / smaller reserve | 872.7 | 31.2 | 30.4 | 0.00 GiB |
| 7,628 tokens, one MTP draft, finer growth / smaller reserve | 814.0 | 33.9 | 31.4 | 0.31 GiB |
| 30,692 tokens, same tuned MTP settings | 442.9 | 17.4 | 16.2 | 1.13 GiB |
| 7,628 tokens, two drafts, 2048 MiB reserve / finer growth | 847.2 | 31.3 | 27.9 | 0.79 GiB |

First answers passed all 13 boundary checks. The 8K MTP on/off and tuned answers were
byte-identical. These are single trials, not confidence intervals. Different review
lengths mean the rates should not be mistaken for matched latency measurements.
No filled 256K prompt or general IQ3_S quality comparison is claimed.

## Memory fit

The original adaptive allocator grows from 4K to 16K cells as soon as the first 4K is
exceeded. This can evict weights that would fit beside an 8K cache. The new opt-in
`STRATA_Q35_KV_GROW_STEP=4096` grows by 4K instead. Supported steps are 4K multiples
through 64K; omission retains 16K. Both main and draft caches use the same capacity.
It changes allocated capacity, not the model's context ceiling or cache quantization.

The trial also lowers the existing `STRATA_Q35_RESERVE_MIB` from 2560 to 1536.
The two changes together account for the memory-fit comparison; their separate speed
contributions were not isolated. Minimum physical free VRAM reached **328 MiB during
8K prefill** and **399 MiB during 32K** in one-second samples. This is an aggressive
GPU profile. The original 2560 reserve leaves more room for desktop GPU use. Minimum
available system RAM remained above 20.6 GiB in the tuned coding trials.

A 4,086-token native test crossed the initial 4K capacity during generation. Its 64
output IDs and draft acceptance counts matched the fixed-16K reference, including a
separate 256K cache-allocation/eviction/reset cycle. That cycle tests storage, not a
filled 256K answer. Two changed-image fixtures with 4,086 input tokens also crossed
4K, read every requested value correctly, and decoded at 35.7–37.7 tokens/s.

## Recreate profiles

With the matching models and mmproj in `models/`, a current HIP build and an AppImage
containing the CPU encoder:

```sh
.venv/bin/python tools/local_model_profiles.py \
  --only swift27-iq3-s --swift-mtp --mtp-context 262144 --vision \
  --dense-prefill-tuning --dense-memory-fit --dense-reserve-mib 1536
```

`--only` leaves existing selections alone and avoids recreating retired Tiel or small
model entries. The tuning switches are opt-in; original generated settings remain the
default. The aggressive measurements above use a 1536 MiB reserve; omission now selects a
2048 MiB reserve for more desktop GPU headroom. The profile
`swift27-iq3-s-mtp-vision` uses one greedy draft. `--swift-mtp-drafts 2` selects two
proposals: the aggressive 8K trial measured 43.0 tokens/s for the first answer and
29.7 for its cached review, with the same first code answer. This was not uniformly
faster than one draft.
Use temperature zero for drafting. The preset generator does not delete GGUF files.

[Raw responses, checks, screenshots and telemetry](../bench/results/2026-10-14-swift-iq3-s-fit/).
HIP was built and tested; CUDA and SYCL were not built on this machine.

## Desktop headroom remains under investigation

The 2048 MiB reserve / two-draft coding trial kept at least 842 MiB physical VRAM free
in one-second samples, with more than 22 GiB available RAM. Two changed-image requests
then answered correctly at 32.3–32.4 output tokens/s, but the worker subsequently stopped
at the router's 512 MiB physical-VRAM guard. This is not a validated desktop-stable preset.
Keep the aggressive peaks distinct from a reliability recommendation. More GPU headroom
needs a separate trial before recommending this Swift preset for unattended use.
The original Saluki settings were retained; see [all current model results](MODEL_RESULTS.md).
