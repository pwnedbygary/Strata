# Local llama.cpp presets

The external `/home/garyb/Mounts/NVME/Strata/models/presets.ini` belongs to the regular
llama app. It is not bundled in Strata's AppImage. The unified Strata UI uses its
own model registry and saved overrides instead.

Model and projector paths were migrated to the organized Strata model library.
The original file is backed up locally; its sampling and performance settings
were initially preserved. The following tuning work tests the dedicated Vulkan
executable on the RX 9070 XT / Ryzen 7800X3D / 32 GiB DDR5-4800 machine.

Test one model at a time. The comparison launcher uses a 20 GiB cgroup ceiling,
no scope swap, physical RAM/VRAM floors, and the same per-user model lock as Strata.
It tests the actual presets loader, not an approximation of its argument parsing.
Explicit `n-gpu-layers=all` defeats the automatic fitter in this source revision;
manual tensor-placement overrides also make the fitter refuse to adjust placement.
Use automatic placement when relying on fitting. Keep failed/guarded loads out of
throughput comparisons.

The four presets retain Q8 KV. Tiel and Cyber Tiel target 262,144 configured
context; both Swift quantizations target 131,072, including an increase from the
old 98,304 Swift IQ3_S setting. A configured target is not full-window validation.
Fresh coding prompts and bounded functional checks compare batch sizes and
speculation; selected candidates receive separate filled-window and cached
follow-up checks. Reasoning is disabled in the speed test requests; those rates
do not include the cost of a reasoning trace.

The short sweep also compares explicit CPU expert placement with automatic
fitting. Manual placement uses Fit off; the automatic fitter refuses pre-existing
tensor overrides. GPU-host-visible GTT is tracked separately: Cyber Tiel at 28
CPU expert layers and microbatch 2048 crossed the 1024 MiB GTT guard despite
having free physical RAM and dedicated VRAM. That guarded run is not a speed
result. An MoE MTP trial ended with Vulkan device loss and is excluded as well.

The selected long-context settings are 27 CPU expert layers, Fit off and microbatch
1024 for Tiel/Cyber; Swift uses Fit on, a 2048 MiB target and microbatch 512
(IQ3_XXS) or 2048 (IQ3_S). The complete 256K/128K fills, functional results,
failed attempts and margins are in the [measured preset record](../bench/results/2026-10-16-llama-presets/README.md).

At the user’s request, later test guards were lowered to 640 MiB free dedicated
VRAM and 768 MiB GTT; the 4 GiB available-RAM floor and 20 GiB worker cap stayed
active. The CPU27/2048 Tiel fill still crossed the VRAM guard near 160K processed
tokens, so 1024 remains the selected long-context microbatch. A fast short test
is not evidence that a configuration fits a filled context.

Manual CPU experts now use `load-mode=none` in the AppImage as well. A packaged
Tiel 128K fill completed at 1,375 / 29.86 tok/s with no MemoryHigh/OOM events.
The public 256K profiles still require admission headroom: on this model the
conservative estimate is about 13.51 GiB free VRAM before loading. Other desktop
applications can cause an early refusal. Lower the context in Tune or free GPU
memory before retrying; the app does not close other applications.
