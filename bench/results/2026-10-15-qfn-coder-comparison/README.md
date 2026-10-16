# QFN Coder IQ1_M: fork versus upstream

Measured October 15, 2026 on Ryzen 7 7800X3D, RX 9070 XT 16 GiB (gfx1201),
32 GB RAM at 4800 MT/s, NVMe/Btrfs, Linux and ROCm 7.2. The user explicitly
requested retaining the −50 mV GPU offset. These runs do not establish that the
undervolt is stable or explain the earlier system freeze.

Model: [ISTA-DASLab Qwen3.8-Flash-Next GSQ-RCO Coder](https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF),
revision `5348543e0147355ac9cbcb031184a3546350988e`, IQ1_M two-shard GGUF.
This variant prunes half the experts; its effective quant label includes pruning.
It does not mean that every retained weight uses one bit. The shared n-gram table
is still 28.8 GB. The second shard was verified byte-identical to the existing
IQ3_XXS table and hard-linked to avoid a duplicate allocation.

The initial first-shard transfer failed SHA-256 verification. It was replaced by
a fresh HF CLI download with Xet disabled; both final shards passed verification.
Only the corrected model and rebuilt pack were used for the reported comparison.
See [manifest](manifest.json) for hashes, commits and settings.

## Method and limits

Fork engine: `e3caf4d92c4024bf4c89522ed08e04085fd1dcef`.
Unmodified upstream engine: `296b59d2f73c8f04a805df29c2fa97655adace78`.
Both were built for HIP/gfx1201 against the same pinned ggml quant sources.
Both used the same fork Python HTTP frontend; this isolates engine comparison,
not the complete untouched upstream server application.

Same GGUF, tokenizer, pack, uniform expert ranking, 3302 GPU expert slots,
11 GiB RAM tier, 5120 MiB reserve, 8 CPU workers, int8 KV and 32768 GPU-resident
KV tokens. Configured context: 131072. Prefill auto selected 8192. Adaptive async
was disabled. No MTP head was loaded; suffix drafting remained enabled. Default
route-tail skipping was 7 in both matched runs. The fork's optional Linux I/O
experiments were not enabled. The larger reserve accommodated this desktop's
other VRAM use; smaller startup trials were stopped by the physical VRAM guard.

One engine and one request at a time. 20 GiB scope limit, zero scope swap,
3 GiB system-available RAM floor and 512 MiB physical VRAM floor stayed enabled.
Per-second memory/temperature/offset samples accompany context tests.

Context prompts were identical between engines (see prompt hashes in the JSON
records), with greedy sampling. The near-full test has 130028 actual input tokens,
leaving output room inside 131072. It repeats filler and tests three embedded
retrieval markers plus three small coding functions. It is not a realistic entire
repository reasoning test. Each condition is a single run, not a statistical
speed comparison. GPU/CPU placement and floating-point arithmetic can affect
outputs even with greedy sampling; the artifacts are preserved rather than
assuming exact deterministic text.

## Results

| Engine / input | Prefill tok/s | Decode tok/s | Cached follow-up tok/s | Code / retrieval |
| --- | ---: | ---: | ---: | --- |
| fork-8k / 8,136 | 459.7 | 16.4 | 14.4 | 12/13 / 3/3 |
| upstream-8k / 8,136 | 368.6 | 17.2 | 14.3 | 12/13 / 3/3 |
| fork-128k / 130,028 | 990.4 | 17.9 | 16.2 | 12/13 / 3/3 |
| upstream-128k / 130,028 | 979.8 | 17.7 | 20.1 | 12/13 / 3/3 |

Near-full prefill and initial decode were essentially tied. The 8K prefill differed,
but these single runs do not establish a repeatable gain. Cached follow-ups produced
different amounts of review text (126 vs 284 tokens at 8K; 192 vs 527 at 128K),
so their token rates are not a matched-output wall-time comparison.
Across the context tests, minimum system-available RAM was 6.25 GiB and minimum
physical free VRAM was 1746 MiB. File caching and desktop activity affect these figures.

The accompanying reports contain fresh prefill/decode, cached follow-up,
13 code checks and three marker checks. The practical suite uses the frozen
prompts in `bench/practical`, seed 20261013, temperature 0, no presence/frequency
penalty. Initial output caps: Snake 6144, Python 3072, SVG 4096. Separate Snake/SVG
retries use 8192; they do not replace the initial failures.

The raw upstream Python artifact imports `typing.List`, which violates the prompt's explicit
no-import requirement and is also rejected by the restricted validator. A separate, labeled normalization removes only
that import and changes annotation `List` to builtin `list`; its unchanged
function body passes all 11 behavior checks. The original artifact and raw
rejection remain in the results. Both implementations validate inputs, copy
before sorting, merge touching intervals and avoid mutating the input, with
O(n log n) sorting work. These bounded checks are not a general correctness proof.

Long CSS/SVG repetition can reach 25–30+ tokens/s without producing useful work.
Do not interpret that as a successful coding-throughput target. Browser checks
use an isolated browser with network requests blocked and GPU acceleration off.
Structural SVG checks and screenshots establish specific properties, not overall
design quality. Failed and truncated artifacts are intentionally retained.

### Practical artifacts

| Engine / output cap | Snake | Python | SVG |
| --- | --- | --- | --- |
| Fork / initial | 6144 cutoff; no game | 11/11 behavior checks | 4096 cutoff; invalid XML |
| Upstream / initial | 6144 cutoff; no game | Raw no-import violation; 11/11 after annotation-only normalization | Complete; 7/7 structural checks |
| Fork / 8192 retry | Cutoff; no game | Not retried | Cutoff; invalid XML |
| Upstream / 8192 retry | Cutoff; no game | Not retried | Complete in 1815 tokens; 7/7 structural checks |

Both Python responses used Markdown fences despite the raw-source requirement.
Upstream SVG finished at 25.7 tok/s initially and 24.7 on the larger-budget retry.
The successful SVG is a recognizable lighthouse/sea/beam composition; the fork
SVG is incomplete. Snake repeatedly emits CSS rules on both engines.
These are individual outputs, not an estimate of overall model accuracy.

![Successful upstream SVG](upstream-practical/lighthouse_svg-0.svg.png)

### Full-routing control

A separate fork run set `STRATA_ROUTE_TAIL_SKIP=0`, verified in the engine process
environment, and kept the same Snake prompt, 6144 output cap and memory settings.
It again repeated CSS until cutoff and had no game API. Decode was 15.5 tok/s;
this cold-start control is not a matched warm speed comparison. It does not
establish a quality benefit for this task, so the setting was not promoted.
The artifact and browser result remain in `fork-full-routing/`.

Recommendation for this tested workflow: keep the higher-quality models as the
normal choices. Coder IQ1_M can produce useful bounded functions and SVG, but these
runs do not support relying on it for long artifact generation. No universal
model ranking follows from three practical prompts. Normal model profiles remain;
Coder is a separate experimental text-only 128K entry, with Saluki still default.

## Reproduction

Prepare the verified GGUF and pack with `tools/iq_pack.py`, create the uniform
expert profile with `tools/make_profile.py --no-base --n-expert 256`, then adapt
the saved profile paths to your machine. The upstream binary is a separate
clean build; do not overwrite the production engine for comparison.

```bash
.venv/bin/python tools/coding_context_bench.py --model qfn-coder-iq1-m-fork \
  --tokens 130048 --long-context-probes --output /tmp/qfn-coder-context
.venv/bin/python tools/benchmark_practical.py --model qfn-coder-iq1-m-fork \
  --output-dir /tmp/qfn-coder-practical --browser-checks
```

Output directories must be new. The router must already be running with the
matching model profile; repeat with the upstream model ID and separate paths.

[UnbiasedStrata feasibility review](../../../docs/UNBIASED_STRATA_REVIEW.md)
records a separate adapted HIP build and GPU smoke, not another speed result.
