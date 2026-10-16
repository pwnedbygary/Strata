# Dedicated Vulkan preset tuning — October 16, 2026

RX 9070 XT 16 GiB, Ryzen 7800X3D, 32 GiB DDR5-4800, Linux, NVMe.
The GPU retained the user-authorized −50 mV offset. These are individual runs
on this desktop, not averages or a hardware stability certification.

The executable was the existing dedicated Vulkan `~/.local/bin/llama`, source
`a2878d30df0130dde503a7d9ba30d3d21bd71b9f`, SHA256
`8dc7aea00583be4cd73e142af9f174072998cd48a4a20341788270c3b559ba52`.
The real `llama serve --models-preset …` loader was exercised. The combined and
ROCm executables were not used in this sweep. No Strata native engine rates are
included here. Previous cross-backend tests are in [the unified comparison](../2026-10-16-unified-runner/README.md).

## Selected settings and completed fills

All models use Q8 K/V, batch 2048, eight CPU/batch threads, CPU-loaded vision
projectors, one model/slot, and speculation off. Timed requests contain text,
not screenshots. Tiel/Cyber use Fit off, all non-expert layers on GPU and the
first 27 expert layers on CPU. Swift uses automatic fitting with a 2048 MiB
fit target; forcing all layers onto GPU defeats the fitter in this revision.
The presets use `load-mode=none`; manual CPU experts use that mode in the
AppImage too.

| Model | Context ceiling | Microbatch | Short prefill / decode | Filled prefill / decode | Code checks at fill | Retrieval |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Tiel Coder Q4_K_XL | 262,144 | 1024 | 1,947 / 36.1 | 1,019 / 27.0 | 11/13 | 3/3 |
| Cyber Tiel Q4_K_XL | 262,144 | 1024 | 1,905 / 36.2 | 1,027 / 27.3 | 13/13 | 3/3 |
| Swift plain IQ3_XXS | 131,072 | 512 | 984 / 14.6 | 577 / 3.32 | 13/13 | 3/3 |
| Swift plain IQ3_S | 131,072 | 2048 | 949 / 8.70 | 600 / 2.07 | 13/13 | 3/3 |

Rates are tokens/second. Short prompts had 8,314/8,315 Tiel/Cyber input tokens
and 8,136 Swift tokens. Filled requests had about 260,096 Tiel/Cyber or 130,028
Swift input tokens, leaving output room. Exact input/cache counts and follow-up
rates are in [full-results.json](full-results.json); a warm-up can leave a small
shared template prefix cached. These are sustained request averages, not the
higher rate seen at the beginning of prefill. Cached follow-ups completed for
all four models. Their prompt rates describe only the small new suffix.

The short Tiel outputs each passed 12/13 checks. Filled Tiel missed normalization
of single/double backslashes. It is a usable context/memory completion, not a
perfect code-quality result. The bounded functional checker and three position
probes do not establish broad coding quality or arbitrary long-context accuracy.
Greedy requests use temperature zero and explicitly disable thinking; the saved
presets retain the user's sampling and reasoning defaults. Output can still vary
with floating-point execution order and batch size.

| Filled model | Minimum available RAM | Minimum dedicated VRAM free | Minimum GTT free |
| --- | ---: | ---: | ---: |
| Tiel | 7.49 GiB | 1,558 MiB | 1,936 MiB |
| Cyber Tiel | 7.26 GiB | 1,460 MiB | 2,046 MiB |
| Swift IQ3_XXS | 17.70 GiB | 1,287 MiB | 13,720 MiB |
| Swift IQ3_S | 14.24 GiB | 1,000 MiB | 11,678 MiB |

These margins include the desktop at measurement time. GTT is the AMD GPU's
host-visible memory budget; free RAM or VRAM alone does not describe it.

## Faster short settings and rejected attempts

At microbatch 2048 with 27 CPU expert layers, short Tiel reached **2,531 / 40.4**
and Cyber **2,409 / 36.1 tok/s** (12/13 code checks each). Tiel's filled attempt
crossed the reduced VRAM guard near 160K processed tokens: **536 MiB free VRAM**,
1,097 MiB GTT and 6.29 GiB RAM at the stop sample. It was stopped cleanly and is
excluded from completed throughput results. Cyber's full 2048 attempt was not
run after this failure. The long-context presets retain microbatch 1024.

Other excluded attempts are preserved in their named directories:

- Automatic-fit Tiel/2048 reached about 227K tokens before GTT fell to 341 MiB.
- Manual CPU26/2048 reached about 152K before VRAM fell to 739 MiB under the
  earlier 768 MiB guard.
- Cyber CPU28/2048 crossed the earlier 1024 MiB GTT guard in a short trial.
- A Tiel MoE embedded-MTP trial failed with Vulkan device loss. It was not a
  guard stop; sampling cannot guarantee catching every transient allocation.
  llama.cpp MoE MTP is blocked in the UI runner pending a validated implementation.
- An initial full Tiel fill produced only reasoning because the long-test request
  lacked explicit template thinking control. Its throughput/memory record is
  retained as `thinking-only`; it is not a code/retrieval pass. The corrected
  benchmark was rerun with `enable_thinking: false`.

Short n-gram speculation trials did not provide a useful consistent gain, with
very few accepted drafts. The final presets disable it and remove the 1 MiB
fit-target / forced-GPU combination that provided almost no memory margin.

## Guards, files and reproduction

One model runs at a time under the shared Strata GPU lock, a 20 GiB cgroup cap,
18 GiB MemoryHigh and no scope swap. Initial tests used 4 GiB RAM / 768 MiB VRAM /
1024 MiB GTT floors. Later tests used **4 GiB / 640 MiB / 768 MiB** at the user's
request. Per-run `command.json` records the actual thresholds. Polling guards are
not an OOM guarantee, and the 2048 failure is not a successful full-window test.

[short-results.json](short-results.json) contains successes and failures,
per-case settings, code checks and minimum margins. Each named directory has its
actual preset and response; full-context directories retain prompts, SSE, memory
samples, reports and checks. Failed runs must not be included in averages.

[presets-tuned.ini](presets-tuned.ini) is the final external preset file installed
at `/home/garyb/Mounts/NVME/Strata/models/presets.ini`. Before-tuning copies preserve
the original settings. Model/projector paths and sampling preferences are kept;
Swift IQ3_S increases from 98,304 to 131,072 context. The AppImage uses its own
registry, not this INI. Its Tiel/Cyber profiles receive the same validated placement.
Swift native/MTP profiles remain separate from these plain-GGUF Vulkan tests.

The archived `run*.py` files show the exact local sweep and cases. They assume
this checkout, models and Python environment. For a new measurement, pass the
archived preset to the dedicated Vulkan executable, use a fresh output directory,
and run `tools/coding_context_bench.py --long-context-probes` followed by
`tools/check_coding_context.py`. Python here is benchmark tooling; it is not
included in the native AppImage runtime.

The packaged runner also applies conservative admission estimates. This Tiel
256K placement estimates roughly 13.51 GiB free dedicated VRAM before loading;
a later desktop state with about 13.3 GiB free was refused before launch. That
refusal is expected, not a full-context completion. Background applications can
change which measured configuration fits. The app keeps its original memory
policy; an exploratory live MemoryHigh increase during a cancelled mmap trial
was not retained as a default change.

## Packaged-app check

After aligning manual CPU-expert loading with `load-mode=none`, a private 128K
Tiel profile in the final AppImage completed **130,020 input tokens at 1,375
prefill / 29.86 decode tok/s**. Its cached follow-up decoded at 29.64 tok/s.
Code checks: **12/13**; position probes: **3/3**. The worker's `memory.events`
recorded zero high/max/OOM/OOM-kill events. See [the run](appimage-tiel-128k/report.json).
This private 128K check does not replace the separately recorded standalone
256K results. The public menu retains its 256K Tiel/Cyber ceilings and admission
checks; the temporary test profile was not added to that menu.

The earlier mmap app run recorded 47,477 MemoryHigh events and was cancelled.
Its exploratory threshold adjustment is documented in `app-mmap-partial-note.json`;
that mixed run is not a fixed-setting speed comparison. The final loader mode
was tested with the unchanged default memory policy. No claim of a matched
before/after speedup is made from runs with different context allocations.

Final verification: HIP frontend build, seven native CPU tests, embedded UI syntax,
HTTP admission/auth/origin/save/reset tests, MoE-only placement controls, Fit
relationships, power-of-two and custom targets, desktop/mobile layout and GTT
rendering passed. CUDA, SYCL and Windows were not built or tested. No GPU kernel
source changed. The private QA server was unloaded after testing; the regular
8096 server was restored to Saluki dedicated Vulkan.
