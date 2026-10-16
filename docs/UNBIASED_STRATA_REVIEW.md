# UnbiasedStrata assessment on RX 9070 XT

Inspected October 15, 2026: [robertkarl/UnbiasedStrata](https://github.com/robertkarl/UnbiasedStrata)
commit `b124b59ce48e4d53abd14d1fd08979350fc27358`. Its documented production path is
Linux/NVIDIA/CUDA; the AMD code is retained but not supported by its normal build.
Our test is an adapted HIP build, not upstream AMD support.

## What was checked

An isolated clone was built for gfx1201 / ROCm with its own pinned llama.cpp dependency,
`3cf03257f219afbe7334045ff7c6a06ac68c627d`. The local CMake adaptation enables the C++
frontend target on HIP and guards seven diagnostics whose source files were removed.
No inference kernel was changed. The resulting `unbiased-strata` executable built.
Child-watch, engine-protocol and pipe-backpressure CPU regressions passed. The real
IQ3_XXS GGUF's chat-template/parser regression also passed: optional tool arguments
before required ones, parallel-call handling, streamed text and whole tool-call deltas.

A GPU smoke test used the already verified full IQ3_XXS model, 128K configured context,
32K GPU-resident int8 KV, the existing MTP head, eight CPU workers and an 11 GiB RAM tier.
The 3072 MiB reserve trial stopped at the 512 MiB physical-VRAM guard during startup;
4096 MiB subsequently loaded and served the requested Python addition function.
This was a short compatibility smoke with concurrent model-file verification/download
I/O, not a performance comparison or a filled-128K validation. The -50 mV undervolt
was retained at the user's explicit request. RAM/VRAM guards and a 20 GiB/no-swap scope
remained active. No hardware stability guarantee is inferred.

## Implications for a new base

The compiled frontend is reusable in principle. It uses llama.cpp's tokenizer,
chat templates and parsers, and has tested child-process failure/disconnect handling.
Its Qwen3.6-35B-A3B MoE work is also relevant to broader model support. Those changes
need individual review and validation on this GPU.

Replacing the current repository wholesale would lose or require re-porting our
validated Saluki/Swift dense path, hardware profiles, model router, web UI and other
API dialects. Its engine lineage is 0.1.39; our compared engines report 0.1.44.
For example, the older engine rejects the newer `--adapt-async` flag. The frontend
also defaults QFN's n-gram table to RAM; we overrode this with `--ple-io direct` so a
28.8 GB table was not loaded into this 32 GiB system alongside the model.

Recommendation: keep the working fork as the engine/hardware baseline, and consider
an opt-in integration of the C++ frontend and selected model-generalization changes.
A C++ HTTP wrapper alone does not establish higher inference throughput. Measure it
with the same prompts, context, settings and memory placement before changing the
normal executable or claiming a speedup. No rebase or production frontend replacement
has been performed by this investigation.

## Reproduce the isolated HIP build

The local compatibility patch is preserved in
[`unbiased-hip-build.patch`](../bench/results/2026-10-15-qfn-coder-comparison/unbiased-hip-build.patch).
It applies to the exact inspected revision with `git apply --unidiff-zero`;
it is not installed into this fork.
Build its own pinned submodule with `STRATA_ENABLE_HIP=ON`,
`STRATA_NATIVE_EXPERTS=ON`, `STRATA_PREFILL_MMQ=ON`,
`CMAKE_HIP_ARCHITECTURES=gfx1201` and a Release configuration.
The removed diagnostic sources remain unavailable: guarding them allows building,
but does not claim their GPU checks passed. CUDA and SYCL were not built here.

The frontend/chat-parser test evidence and model comparison settings are in the
[comparison archive](../bench/results/2026-10-15-qfn-coder-comparison/README.md).
No downloaded models, compiled binaries or private crash journals are committed.

## Coder with runtime defaults: startup failed

A subsequent requested test used the verified Coder IQ1_M GGUF and its prepared pack,
the existing required QFN MTP head, port 8098, and **no engine-setting overrides**.
Default context was 32768. The same HIP build adaptation remained necessary.
The frontend's default `--ple-io ram` began loading the 26.8 GiB n-gram table into
system RAM. The kernel killed the test at its external 20 GiB/no-swap cgroup limit
(`Result=oom-kill`, peak exactly 21474836480 bytes) before startup completed.
No inference request was sent and there are no throughput or quality results.
This establishes failure under the retained memory envelope, not a test with unlimited
RAM or swap. The polling guard's `aborted=false` does not mean success: the cgroup
limit fired before its physical-system floors. The test processes exited, the normal
router stayed healthy and unloaded, and system-available RAM recovered to about 24 GiB.
The existing draft head is not a Coder-specific trained head; generation compatibility
was not reached. No higher-limit retry was performed.

[Raw default-test evidence](../bench/results/2026-10-15-qfn-coder-comparison/unbiased-coder-defaults/result.json).

## Follow-up integration

The opt-in native frontend is now implemented in this fork's `frontend/` directory,
retaining the newer engine and dense paths. It adds local registry routing,
Anthropic/Responses adapters, screenshot input, bounded workers and AppImage
packaging. This is a selective integration rather than a wholesale engine rebase.
See [native server details](NATIVE_SERVER.md) for the supported API subset and build.
The preceding isolated-build measurements describe the inspected upstream fork,
not performance claims for this integration.
