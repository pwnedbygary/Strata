# Model results on this fork's RX 9070 XT PC

What each profile in Gary's router registry does on one PC: prompt and decode speed with the prompt filled to the
profile's context limit and at about 8K tokens, the follow-up time, and the checks on each answer. Every table says
when and with which build it was measured. A context limit counts as tested only where a prompt of that size ran.

## The PC

- GPU: AMD Radeon RX 9070 XT, 16 GB (gfx1201). The desktop holds about 1.0-1.5 GB of its VRAM.
- CPU: AMD Ryzen 7 7800X3D (8 cores, 16 threads). RAM: 32 GB (31 GiB usable). ROCm 7.2.4 on Linux.
- Other agent sessions share this PC. The Oct 25-26 tables come from timed windows in which they had paused builds,
  tests and emulators. A sampler logged the load, available RAM, VRAM and the top three processes by `ps` CPU use
  every 10 s; where it saw another session's build or java process during a measurement, the notes below say so.

## How the profile tables were measured

- `tools/profile_context_runs.py` with greedy requests (windows 7 and 8 ran the scripts it replaced, with the same
  steps). For each profile: a fresh router (the installed AppImage) on 127.0.0.1 from a copy of the registry;
  `tools/coding_context_bench.py` sends a coding prompt of the context limit minus 2,048 tokens (or about 8K) that
  holds three retrieval checkpoints (near the start, in the middle, near the end), asks for a fresh answer, then sends
  a follow-up request that continues the same conversation; `tools/check_coding_context.py` runs 13 checks on the
  fresh answer's code; a profile with `--vision` also answers a picture question (`tools/qwen35/pictures/shapes.png`;
  pass = all three shapes and colours named).
- The requests are greedy (`temperature` 0) with thinking off. The bench sends no other sampling field, so the router
  fills in the rest of each profile's `sampling` block. At temperature 0 those values change nothing except Saluki's
  presence penalty 1.1, which the engine subtracts from the tokens seen in the last 64 before it takes the most likely
  one: Saluki's rows are greedy with that penalty, and its Oct 16 llama.cpp baseline had none. In use the whole block
  applies, temperature included: temperature 1.0, top-p 0.95 and top-k 20 for the Flash-Next and dense profiles
  (Saluki adds presence penalty 1.1), temperature 0.6 with the same top-p and top-k for Tiel and Cyber Tiel. For
  Qwen3.8-Flash-Next that is the thinking-mode set of `serve/server.py`'s model-card table (0.7 / 0.8 / 20 with
  presence penalty 1.5 without thinking), and the router applies it whatever the thinking state. With sampling, fewer
  MTP drafts are expected to be accepted than with greedy decoding, so the drafting profiles may decode more slowly in
  use (not yet measured in a timed window; an untimed check of Swift IQ3_S at 4,044 tokens accepted 216 of 228 and 240
  of 252 sampled drafts in the fresh answer against 214 of 216 greedy, and 124 of 188 and 126 of 162 against 158 of
  188 in the follow-up). Only the Flash-Next comparison at the end samples.
- Prompt tok/s covers the whole fill (prompt tokens / prompt time; seconds in brackets). Decode tok/s is the fresh
  answer's (at most 768 tokens). "Follow-up" is the follow-up request's time to its first token and its decode speed.
  "Checks" are the retrieval checkpoints found, the code checks passed and the picture answer. Peak VRAM is the
  whole card's use, the desktop's included.
- Build of the Oct 25 tables: the installed AppImage (sha256 0ae6890f...): strata-native from `codex/rx9070xt-perf`
  d2b0565b with Gary's frontend commits, and the llama.cpp ROCm and Vulkan builds of the Oct 19 AppImage.
- Raw files (not in git): `local-tuning/perf-2026-10-25/` and `local-tuning/perf-2026-10-26/` in Gary's checkout.

## The profiles (Oct 26)

- `saluki27-abliterated-mtp-vision`: Saluki 27B IQ2-mix with an MTP head, on Strata. Context 131,072, `--prefill 2048`,
  `--mtp 2`, `--vision`, reserves 1,536 / 1,024 MiB.
- `swift27-iq3-s-mtp` and `swift27-iq3-s-mtp-vision`: Swift 1.5 27B IQ3_S with an MTP head, on Strata; context,
  prefill, MTP and reserves as Saluki's, `--vision` only in the vision profile.
- `swift27-iq3-xxs` and `swift27-iq3-xxs-vision`: Swift 1.5 27B IQ3_XXS with an MTP head (the `-mtp` file since
  Oct 25), on Strata; the same settings as the IQ3_S pair.
- `tiel-coder` and `cyber-tiel-coder`: 35B-A3B mixtures of experts, UD-Q4_K_XL, on llama.cpp Vulkan. Context 262,144,
  the experts of 25 layers on the CPU, q8_0 KV, no MTP.
- `flash-iq3` and `flash-q2_0`: Qwen3.8-Flash-Next, IQ3_XXS and Q2_0 packs, on Strata's Flash engine. Context 131,072,
  int8 KV (32,768 cells in VRAM), an 11 GiB RAM tier, MTP drafts. The router's tuning file sets `--spec 3` and a
  3,584 MiB VRAM reserve over the profile files' 4 and 3,072 MiB.

"Before" is what the profile ran before the Oct 24-25 changes (on the engine Automatic picked then), measured the same
day with the same AppImage unless the row says otherwise.

## Prompt filled to the context limit (Oct 25)

| Profile | Engine | Prompt tokens | Prompt tok/s (s) | Decode tok/s | Follow-up s, tok/s | Checks | Peak VRAM MiB |
|---|---|---:|---:|---:|---:|---|---:|
| saluki27-abliterated-mtp-vision | Strata | 128,974 | 773 (167) | 49.25 | 1.3, 43.04 | 3/3, 13/13, pass | 15,182 |
| swift27-iq3-s-mtp, window 7 | Strata | 128,974 | 737 (175) | 12.15 | 1.4, 10.86 | 3/3, 13/13 | 15,279 |
| swift27-iq3-s-mtp, window 8 | Strata | 128,974 | 732 (176) | 11.73 | 1.4, 10.51 | 3/3, 13/13 | 15,268 |
| swift27-iq3-s-mtp-vision | Strata | 128,974 | 738 (175) | 11.99 | 1.4, 10.84 | 3/3, 13/13, pass | 15,270 |
| swift27-iq3-xxs, run 1 | Strata | 128,974 | 755 (171) | 17.29 | 1.4, 14.80 | 3/3, 13/13 | 15,268 |
| swift27-iq3-xxs, run 2 | Strata | 128,974 | 731 (176) | 17.94 | 2.3, 15.27 | 3/3, 13/13 | 15,270 |
| swift27-iq3-xxs-vision | Strata | 128,974 | 753 (171) | 17.44 | 1.4, 14.76 | 3/3, 13/13, pass | 15,278 |
| tiel-coder | llama.cpp | 260,095 | 1,003 (259) | 32.11 | 0.6, 32.25 | 3/3, 11/13 | 14,783 |
| cyber-tiel-coder | llama.cpp | 260,096 | 1,001 (260) | 31.88 | 0.6, 33.04 | 3/3, 13/13 | 14,784 |
| flash-iq3 | Strata | 128,974 | 447 (289) | 8.50 | 4.4, 15.77 | 3/3, 13/13 | 14,469 |
| flash-q2_0 | Strata | 128,974 | 675 (191) | 18.46 | 1.6, 30.71 | 3/3, 13/13 | 14,463 |

The Swift IQ3_XXS rows and the second Swift IQ3_S row are from window 8 (20:55-21:22), the others from window 7
(14:55-16:17). Least RAM available during a run: 6.8-6.9 GiB for Flash-Next, 9.8-9.9 GiB for Tiel and Cyber Tiel,
15.9-23.0 GiB for the dense models. The 1-minute load reached 19.5 in the Flash-Next runs (the engine's own CPU expert
threads) and stayed under 5 in the others, except in two window 8 runs during which another session built: the Swift
IQ3_S run (java and clang from 21:04:35; load up to 10.3), whose prompt was under 1% and decode about 3.5% slower than
window 7's, and the second Swift IQ3_XXS run (clang, about 21:14-21:16; load up to 29.8), whose prompt was 3% slower
than the first run's. Lighter processes of another session also ran in window 8: a `javap` at 21:10:16, near the end
of the Swift IQ3_XXS vision run, a second java process at 21:11:03, and the java process first seen at 21:04:35,
which the sampler listed in nearly every sample until the window's end. By its `ps` figures (CPU time over its
lifetime) it worked after 21:05 only in bursts, about 38 CPU-seconds in the first 8K run without the MTP head, 18 at
the end of the 8K vision run and 110 during the compile, and was idle otherwise. So every later window 8 run had it
listed: the Swift IQ3_XXS vision run at the limit, every run at 8K and the window's last two runs at the limit (the
second Swift IQ3_XXS run and the second run without the MTP head); apart from the compile, their 1-minute load peaked
at 3.6-6.6.

| Profile | Before | Before: prompt / decode tok/s | Now | Decode now / before |
|---|---|---:|---:|---:|
| saluki27-abliterated-mtp-vision | llama.cpp Vulkan, Oct 16, 130,028 tokens (1) | 709.8 / 33.91 | 773 / 49.25 | x1.45 |
| swift27-iq3-s-mtp-vision | Strata, `--prefill 512`, `--mtp 1`, reserves 3,072 / 2,048 MiB | 569 / 6.82 | 738 / 11.99 | x1.76 |
| swift27-iq3-xxs | llama.cpp Vulkan (129,014 tokens by its count) | 539 / 4.95 | 755 / 17.29, 731 / 17.94 | x3.49, x3.62 |
| swift27-iq3-xxs-vision | llama.cpp Vulkan | 539 / 5.05 | 753 / 17.44 | x3.45 |
| tiel-coder | the experts of 27 layers on the CPU | 978 / 30.51 | 1,003 / 32.11 | x1.05 |
| cyber-tiel-coder | the experts of 27 layers on the CPU | 982 / 29.26 | 1,001 / 31.88 | x1.09 |

(1) `codex/rx9070xt-32gb-profile`, `bench/results/2026-10-16-native-dense-comparison/README.md` (13/13 code checks,
3/3 retrieval, cached review decode 33.74): a separate llama.cpp server, text only and reserving 2,048 MiB of VRAM,
not the router's profile (vision on, a 1,024 MiB fit target); not rerun on Oct 25.

The other "before" runs: 1-minute load up to 7.1, and 12.3 at the start of the old-settings Swift IQ3_S run, which is
the load average still falling after the Flash-Next run before it (only the Swift engine was busy then).

`swift27-iq3-s-mtp` had the same old settings as its vision twin and was not run in them on this build. From Oct 25
16:17 to 22:30 the Swift IQ3_XXS profiles ran Strata on the file without the MTP head: 785 / 8.40 (window 7), 801 / 8.01
and 788 / 8.31 (window 8) at the limit. In window 8's two pairs at the limit the file with the head read the prompt
5.7-7.2% slower (the 7.2% pair includes the run during the compile) and decoded 2.16 times as fast. In all four
window 8 pairs (two at the limit, two at 8K) the fresh answers with and without drafts were byte-identical; the
follow-up answers differed (at the limit in one word, at 8K from the fifth line on), so the two files' follow-up speeds
come from different text. At the limit Tiel's fresh answers fail the two backslash checks with 25 and with 27 CPU
layers alike (its `normalize_path` ignores backslashes).

## Prompt of about 8K tokens (Oct 25)

| Profile | Engine | Prompt tokens | Prompt tok/s (s) | Decode tok/s | Follow-up s, tok/s | Checks | Peak VRAM MiB |
|---|---|---:|---:|---:|---:|---|---:|
| saluki27-abliterated-mtp-vision | Strata | 8,136 | 1,337 (6) | 72.53 | 0.4, 61.39 | 3/3, 13/13, pass | 12,287 |
| swift27-iq3-s-mtp, window 7 | Strata | 8,136 | 1,228 (7) | 68.64 | 0.8, 59.68 | 3/3, 13/13 | 15,257 |
| swift27-iq3-s-mtp, window 8 | Strata | 8,136 | 1,203 (7) | 67.88 | 0.9, 59.63 | 3/3, 13/13 | 15,350 |
| swift27-iq3-s-mtp-vision | Strata | 8,136 | 1,223 (7) | 68.50 | 0.8, 60.09 | 3/3, 13/13, pass | 15,816 |
| swift27-iq3-xxs, run 1 | Strata | 8,136 | 1,308 (6) | 68.67 | 0.4, 62.14 | 3/3, 13/13 | 14,514 |
| swift27-iq3-xxs, run 2 | Strata | 8,136 | 1,321 (6) | 68.47 | 0.4, 61.99 | 3/3, 13/13 | 14,483 |
| swift27-iq3-xxs-vision | Strata | 8,136 | 1,280 (6) | 69.08 | 0.4, 61.47 | 3/3, 13/13, pass | 14,344 |
| tiel-coder | llama.cpp | 8,189 | 1,936 (4) | 42.47 | 0.3, 44.60 | 3/3, 12/13 | 14,278 |
| cyber-tiel-coder, 27 CPU layers | llama.cpp | 8,190 | 1,950 (4) | 45.57 | 0.3, 45.80 | 3/3, 12/13 | 13,344 |
| flash-iq3 | Strata | 8,136 | 381 (21) | 9.03 | 3.7, 15.03 | 3/3, 13/13 | 14,413 |
| flash-q2_0 | Strata | 8,136 | 468 (17) | 16.30 | 1.6, 26.47 | 3/3, 13/13 | 14,395 |

Cyber Tiel was measured at 8K only with its old 27 CPU layers. Tiel (with 25 and with 27 CPU layers) and Cyber Tiel
fail one check at 8K: `next_head((0,0),(1,0),2.5,4)` returns `(1.0, 0)` instead of raising `ValueError`. The Swift
IQ3_XXS and second Swift IQ3_S rows are from window 8 (its other processes are noted above), the others from window 7.
1-minute load up to 8.0 (Flash-Next) and 7.1 in the others.

| Profile | Before | Before: prompt / decode tok/s | Now | Decode now / before |
|---|---|---:|---:|---:|
| saluki27-abliterated-mtp-vision | llama.cpp Vulkan, Oct 16, 8,136 tokens (2) | 1,246.2 / 49.68 | 1,337 / 72.53 | x1.46 |
| swift27-iq3-s-mtp-vision | Strata, `--prefill 512`, `--mtp 1`, reserves 3,072 / 2,048 MiB | 955 / 34.59 | 1,223 / 68.50 | x1.98 |
| swift27-iq3-xxs | llama.cpp Vulkan (8,176 tokens by its count) | 818 / 15.51 | 1,308 / 68.67, 1,321 / 68.47 | x4.43, x4.41 |
| swift27-iq3-xxs-vision | llama.cpp Vulkan | 825 / 15.68 | 1,280 / 69.08 | x4.41 |
| tiel-coder | the experts of 27 layers on the CPU | 1,877 / 41.09 | 1,936 / 42.47 | x1.03 |

(2) The same Oct 16 server and file (13/13 code checks; retrieval not probed); not rerun on Oct 25.

On the file without the MTP head, Swift IQ3_XXS read 8K at 1,353 / 35.01 (window 7), 1,341 / 35.04 and 1,335 / 35.03
(window 8). In the two window 8 pairs at 8K the file with the head read the prompt 1.0-2.4% slower and decoded
1.95-1.96 times as fast.

`flash-q2_0` decodes about twice as fast as `flash-iq3` and gives different answers. Upstream's yardstick against
Q8_0 (`docs/QUANTS.md`, 4,995 teacher-forced positions on an R9700): Q2_0 80.60% the same top token, mean KL 0.315,
perplexity 4.475; IQ3_XXS 84.46%, 0.202, 4.119.

## Flash-Next at 8K, before and after the rebase onto upstream 0.2.6 (Oct 26)

Window 9 (17:00-17:17): old = `codex/rx9070xt-perf` d2b0565b, new = the same commits rebased onto upstream 0.2.6
(08688d57, the rebased d2b0565b), run directly through `--serve` with each profile's arguments as the router runs them
(its tuning file sets `--spec 3` and `--vram-reserve-mib 3584`). An 8,137-token prompt, 128 tokens sampled with the
profile's values (temperature 1.0, top-p 0.95, top-k 20) and a fixed seed; one warm-up, then three pairs in
alternating order, each run a fresh engine. Runs in pair order:

| Profile | Engine | Prompt tok/s | Decode tok/s | Median prompt / decode |
|---|---|---|---|---:|
| flash-iq3 | old | 233.3, 300.9, 345.5 | 7.31, 3.70, 7.92 | 300.9 / 7.31 |
| flash-iq3 | new | 266.9, 254.6, 325.9 | 7.50, 8.00, 8.06 | 266.9 / 8.00 |
| flash-q2_0 | old | 413.0, 406.4, 371.7 | 13.87, 13.89, 14.26 | 406.4 / 13.89 |
| flash-q2_0 | new | 377.5, 504.9, 398.0 | 14.35, 14.48, 13.74 | 398.0 / 14.35 |

All seven runs of each profile, old and new, gave the same 128 tokens. Decode is the same within about 4%: in the five
pairs without the slow run the new engine is 1.8-4.2% faster in four and 3.6% slower in one. During the old IQ3_XXS
run at 3.70 tok/s available RAM fell to 1.0-2.1 GiB; in every other run it stayed at about 4 GiB or more. The prompt
speed of one engine varies more between its runs (233-346 tok/s for the old engine on IQ3_XXS) than between the
engines. 1-minute load up to 13 (the engine's own CPU threads), one GPU compute process at a time.

## Changes that did not work (Oct 25)

- `flash-iq3` and `flash-q2_0` with a 2,048 MiB VRAM reserve (a tuning-file override): 1,752-1,998 MiB of VRAM was
  free after loading and about 480 MiB during the request, and the router's memory monitor stopped the worker (its
  VRAM floor is 512 MiB) at 8K and at the limit. The profiles keep 3,584 MiB.
- `tiel-coder` with llama.cpp's fit (no CPU expert layers, a 1 GiB target): the worker's memory cgroup filled to its
  20 GiB cap (the model file is 21.2 GiB), and the router's memory guard stopped the worker, at 8K and at the limit.

## Not measured

- Sampled (not greedy) decode speeds of the dense and Tiel profiles.
- Cyber Tiel at 8K with 25 CPU layers.
- A prompt beyond 131,072 tokens on the dense models (their profiles stop there).
- The dense profiles on this branch's 0.2.6 rebase (their logits at 33 positions of an 8K prompt are bit-identical to
  d2b0565b's, whose AppImage ran the Oct 25 tables), and Flash-Next on it beyond 8K.
- Windows, CUDA and SYCL builds, and other GPUs.
