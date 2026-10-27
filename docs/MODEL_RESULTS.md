# Model results on this fork's RX 9070 XT PC

What each profile in Gary's router registry does on one PC: prompt and decode speed with the prompt filled to the
profile's context limit and at about 8K tokens, the follow-up time, and the checks on each answer. Every table says
when and with which build it was measured. A context limit counts as tested only where a prompt of that size ran.

## The PC

- GPU: AMD Radeon RX 9070 XT, 16 GB (gfx1201; 16,304 MiB). The desktop holds part of its VRAM, and how much varies:
  1,406-1,447 MiB at the window 7 run starts (Oct 25), 1,115-2,026 MiB at the window 10 run starts (Oct 26).
- CPU: AMD Ryzen 7 7800X3D (8 cores, 16 threads). RAM: 32 GB (31 GiB usable). ROCm 7.2.4 on Linux.
- Other agent sessions share this PC. The Oct 25-26 tables come from timed windows in which they were asked to pause
  builds, tests and emulators. A sampler logged the load, available RAM, VRAM and the top three processes by `ps` CPU
  use every 10 s; where it saw another session's build or java process during a measurement, the notes below say so.
  In window 10 (Oct 26) other sessions' work ran during part of the first pass; its notes say which runs were repeated.

## How the profile tables were measured

- `tools/profile_context_runs.py` (windows 7 and 8 ran the scripts it replaced, with the same steps). For each
  profile: a fresh router (the installed AppImage) on 127.0.0.1 from a copy of the registry;
  `tools/coding_context_bench.py` sends a coding prompt of the context limit minus 2,048 tokens (or about 8K) that
  holds three retrieval checkpoints (near the start, in the middle, near the end), asks for a fresh answer, then sends
  a follow-up request that continues the same conversation; `tools/check_coding_context.py` runs 13 checks on the
  fresh answer's code; a profile with `--vision` also answers a picture question (`tools/qwen35/pictures/shapes.png`;
  pass = all three shapes and colours named).
- Oct 25 (windows 7 and 8): greedy requests (`temperature` 0) with thinking off. The bench sends no other sampling
  field, so the router fills in the rest of each profile's `sampling` block. At temperature 0 those values change no
  token except Saluki's presence penalty 1.1, which the engine subtracts from the tokens seen in the last 64 before it
  takes the most likely one: Saluki's Oct 25 rows are greedy with that penalty, and its Oct 16 llama.cpp baseline had
  none.
- Oct 26 (window 10): the bench sends no sampling field but a fixed seed (20261026), so the whole block applies, as
  for any client that sends no sampling fields: temperature 1.0, top-p 0.95 and top-k 20 for the Flash-Next and dense
  profiles (Saluki adds presence penalty 1.1), temperature 0.6 with the same top-p and top-k for Tiel and Cyber Tiel.
  Thinking stays off. For Qwen3.8-Flash-Next that is the thinking-mode set of `serve/server.py`'s model-card table
  (0.7 / 0.8 / 20 with presence penalty 1.5 without thinking), and the router applies it whatever the thinking state.
  The picture question stays greedy. Repeated runs with the same seed gave byte-identical answers on the dense
  profiles and other answers on Flash-Next (at 8K).
- Prompt tok/s covers the whole fill (prompt tokens / prompt time; seconds in brackets). Decode tok/s is the fresh
  answer's (at most 768 tokens); "Drafts" (window 10) are its MTP drafts accepted / offered. "Follow-up" is the
  follow-up request's time to its first token and its decode speed. "Checks" are the retrieval checkpoints found, the
  code checks passed and the picture answer. Peak VRAM is the whole card's use, the desktop's included.
- Build of the Oct 25 and Oct 26 profile tables: the installed AppImage (sha256 0ae6890f...): strata-native from
  `codex/rx9070xt-perf` d2b0565b with Gary's frontend commits, and the llama.cpp ROCm and Vulkan builds of the Oct 19
  AppImage.
- Raw files (not in git): `local-tuning/perf-2026-10-25/` and `local-tuning/perf-2026-10-26/` in Gary's checkout,
  and window 10's `/home/garyb/Mounts/NVME/OpenChamber/strata/perf-2026-10-26/` on the PC's NVMe drive.

## The profiles (Oct 26)

- `saluki27-abliterated-mtp-vision`: Saluki 27B IQ2-mix with an MTP head, on Strata. Context 131,072, `--prefill 2048`,
  `--mtp 2`, `--vision`, reserves 1,536 / 1,536 MiB (`STRATA_Q35_RESERVE_MIB` / `STRATA_Q35_PHYSICAL_RESERVE_MIB`;
  the second was 1,024 MiB until Oct 26, 21:10).
- `swift27-iq3-s-mtp` and `swift27-iq3-s-mtp-vision`: Swift 1.5 27B IQ3_S with an MTP head, on Strata; context,
  prefill and MTP as Saluki's, reserves 1,536 / 1,024 MiB, `--vision` only in the vision profile.
- `swift27-iq3-xxs` and `swift27-iq3-xxs-vision`: Swift 1.5 27B IQ3_XXS with an MTP head (the `-mtp` file since
  Oct 25), on Strata; the same settings as the IQ3_S pair.
- `tiel-coder` and `cyber-tiel-coder`: 35B-A3B mixtures of experts, UD-Q4_K_XL, on llama.cpp Vulkan. Context 262,144,
  the experts of 26 layers on the CPU (25 until Oct 26, 21:10), q8_0 KV, no MTP.
- `flash-iq3` and `flash-q2_0`: Qwen3.8-Flash-Next, IQ3_XXS and Q2_0 packs, on Strata's Flash engine. Context 131,072,
  int8 KV (32,768 cells in VRAM), an 11 GiB RAM tier, MTP drafts. The router's tuning file sets `--spec 3` and a
  3,584 MiB VRAM reserve over the profile files' 4 and 3,072 MiB.

## Sampled requests (Oct 26, window 10)

Window 10 (19:45-20:57) ran every profile with its own sampling and a fixed seed, through the same AppImage as the
Oct 25 tables: a first pass at about 8K and at the limit, then variant runs for the profiles that failed as deployed,
then repeats of the runs that other sessions' work had overlapped. A row is from a repeat unless it says otherwise.

### Prompt filled to the context limit

| Profile | Engine | Prompt tokens | Prompt tok/s (s) | Decode tok/s | Drafts | Follow-up s, tok/s | Checks | Peak VRAM MiB |
|---|---|---:|---:|---:|---:|---:|---|---:|
| saluki27-abliterated-mtp-vision (a) | Strata | 128,974 | 762 (169) | 45.65 | 203/224 | 1.4, 35.06 | 3/3, 13/13, pass | 14,758 |
| swift27-iq3-s-mtp | Strata | 128,974 | 740 (174) | 12.71 | 214/216 | 1.5, 11.14 | 3/3, 13/13 | 15,330 |
| swift27-iq3-s-mtp-vision | Strata | 128,974 | 741 (174) | 12.64 | 214/216 | 1.4, 11.18 | 3/3, 13/13, pass | 15,256 |
| swift27-iq3-xxs, first pass | Strata | 128,974 | 751 (172) | 17.65 | 202/208 | 1.7, 15.46 | 3/3, 13/13 | 15,278 |
| swift27-iq3-xxs-vision, first pass | Strata | 128,974 | 743 (174) | 15.93 | 202/208 | 2.3, 14.44 | 3/3, 13/13, pass | 15,488 |
| tiel-coder (b) | llama.cpp | 260,095 | 990 (263) | 29.78 | - | 0.7, 30.70 | 3/3, 10/13 | 14,289 |
| cyber-tiel-coder (b) | llama.cpp | 260,096 | 991 (262) | 30.34 | - | 0.7, 29.88 | 3/3, 12/13 | 14,231 |
| flash-iq3, first pass | Strata | 128,974 | 435 (296) | 8.98 | 50/58 | 2.1, 16.25 | 3/3, - (c) | 14,808 |
| flash-q2_0, first pass | Strata | 128,974 | 672 (192) | 19.76 | 231/268 | 1.7, 31.64 | 3/3, 12/13 | 14,558 |

(a) A variant run with the 1,536 MiB physical reserve the profile has had since Oct 26, 21:10, from a copy of the
registry with that setting; Saluki's other reserves are in the table below. (b) Variant runs with 26 CPU expert layers,
as the profiles have had since 21:10, from a copy of the registry with that setting (see "Tiel's CPU expert layers").
(c) The fresh answer was 88 tokens long: the three retrieval codes and no code. The code checker stopped with an error
on it instead of failing its checks.

### Prompt of about 8K tokens

| Profile | Engine | Prompt tokens | Prompt tok/s (s) | Decode tok/s | Drafts | Follow-up s, tok/s | Checks | Peak VRAM MiB |
|---|---|---:|---:|---:|---:|---:|---|---:|
| saluki27-abliterated-mtp-vision (d) | Strata | 8,136 | 1,317 (6) | 70.81 | 205/220 | 0.4, 60.53 | 3/3, 13/13, pass | 12,163 |
| swift27-iq3-s-mtp | Strata | 8,136 | 1,256 (6) | 65.52 | 216/228 | 0.7, 57.03 | 3/3, 13/13 | 15,211 |
| swift27-iq3-s-mtp-vision | Strata | 8,136 | 1,180 (7) | 65.48 | 216/228 | 1.1, 57.00 | 3/3, 13/13, pass | 15,213 |
| swift27-iq3-xxs | Strata | 8,136 | 1,314 (6) | 66.84 | 223/232 | 0.4, 55.35 | 3/3, 13/13 | 12,788 |
| swift27-iq3-xxs-vision | Strata | 8,136 | 1,292 (6) | 65.95 | 223/232 | 0.4, 55.75 | 3/3, 13/13, pass | 14,197 |
| tiel-coder (b) | llama.cpp | 8,189 | 1,942 (4) | 41.33 | - | 0.3, 41.21 | 3/3, 12/13 | 13,958 |
| cyber-tiel-coder (b) | llama.cpp | 8,190 | 1,928 (4) | 40.43 | - | 0.3, 43.22 | 3/3, 12/13 | 13,796 |
| flash-iq3 | Strata | 8,136 | 363 (22) | 11.63 | 325/365 | 5.4, 12.42 | 3/3, 6/13 | 14,128 |
| flash-q2_0 | Strata | 8,136 | 452 (18) | 16.50 | 210/235 | 1.4, 32.24 | 3/3, 12/13 | 14,208 |

(d) With the 1,024 MiB physical reserve the profile had until 21:10.

### Saluki's physical reserve

`STRATA_Q35_PHYSICAL_RESERVE_MIB` at the limit, with the VRAM the desktop held at the run's start and the least free
VRAM logged during the run. The worker cancels a running request when less than 768 MiB of VRAM is free (it checks at
most every 0.5 s).

| Physical reserve MiB | Run | Desktop VRAM at start MiB | Least free VRAM MiB | Prompt / decode tok/s | Follow-up s, tok/s |
|---:|---|---:|---:|---|---:|
| 1,024 | first pass | 1,637 | 702 | cancelled at the switch to decode | - |
| 1,024 | repeat | 1,173 | 1,079 | 771 / 46.14 | 1.2, 35.91 |
| 1,280 | variant | 1,177 | 1,348 | 769 / 46.73 | 1.3, 36.38 |
| 1,536 | variant | 1,177 | 1,546 | 762 / 45.65 | 1.4, 35.06 |

The three runs that finished gave byte-identical fresh and follow-up answers.

### Tiel's CPU expert layers

The router starts a llama.cpp profile with manual expert placement only when the free VRAM covers the GGUF file's
size less the experts of its CPU layers, an estimate of the q8_0 KV cache for the whole context, and 2 GiB
(`frontend/backend.hpp`). For the Tiel and Cyber Tiel files (21,696 MiB; 464 MiB of experts in most layers) at
262,144 tokens that is 14,766 MiB with 25 CPU layers, 14,302 with 26 and 13,838 with 27, so the desktop may hold at
most 1,538, 2,002 or 2,466 MiB of the card's 16,304. In the first pass it held 1,591-1,955 MiB at the four Tiel and
Cyber Tiel starts, and the router refused them with 25 layers ("Manual placement exceeds conservative VRAM budget");
in window 7 the 25-layer runs started with 1,428-1,446 MiB held. The 26-layer runs started with 1,115-1,479 MiB held.
They ran from a copy of the registry holding only these two profiles, as `tiel-coder-cm26` and `cyber-tiel-coder-cm26`;
the copy's tuning file has Cyber Tiel's entry, unchanged, under its new id (Tiel has none in either file), and each
profile file differs from the live one only in its display name and description.

### Notes

- Other sessions' work overlapped the first pass. During both Swift IQ3_S runs at the limit a headless browser of up
  to about 10 cores and a .NET build of up to about 5 cores ran (by `ps`; 1-minute load up to 14.6): those runs decoded
  at 10.67 and 10.87 tok/s (follow-up 8.70 and 9.32), 14-16% slower than the repeats above (follow-up 17-22%), with
  byte-identical answers. npm, node, two short builds and short commands of other sessions ran during the 8K pass.
  The seven Strata profiles' 8K runs and both Swift IQ3_S runs at the limit were repeated at the end of the window; in
  the repeats the sampler saw no other session's process except a node process (owner unknown) in flash-iq3's
  follow-up (it also logged a kernel worker in flash-q2_0's run). Three first-pass rows overlapped lighter work and
  were not repeated: Swift IQ3_XXS (one short command of another session within about a second of its request's
  start), its vision profile (`gh` commands of up to half a core in its decode and follow-up) and flash-q2_0 (a
  browser starting and a short node process during its prompt read and decode). In the first-pass flash-iq3 run at the
  limit the sampler saw no other session's process.
- Against the greedy Oct 25 rows (one or two runs per profile, a day earlier): at 8K the five dense profiles decoded
  2.4-4.5% slower, and Saluki, Swift IQ3_S and Swift IQ3_XXS each accepted a smaller share of their drafts (205 of
  220 against 219 of 226, 216 of 228 against 214 of 216, 223 of 232 against 212 of 212). At the limit Saluki with its
  old 1,024 MiB reserve decoded 6.3% slower (46.14 against 49.25; follow-up 35.91 against 43.04) and accepted 203 of
  224 drafts against 226 of 232; the Swift IQ3_S pair and both Flash-Next profiles decoded 4.6-7.0% faster than in
  window 7; Swift IQ3_XXS's 17.65 lies between its two Oct 25 runs (17.29, 17.94), and its vision profile's
  first-pass 15.93 is 8.7% under Oct 25's 17.44. Tiel with 26 CPU layers (sampled) decoded 2.7% slower at 8K and 7.3%
  slower at the limit than with 25 (greedy, Oct 25), Cyber Tiel 4.8% slower at the limit, and Cyber Tiel at 8K gave
  40.43 against 45.57 with 27 layers on Oct 25; these comparisons mix the layer change with the sampling and the day.
- Code checks: Tiel 10/13 at the limit (11/13 on Oct 25), Cyber Tiel 12/13 (13/13). flash-q2_0 passed 12 of 13 in
  all three of its runs (13/13 at both sizes on Oct 25), failing the same check each time (a call that should raise
  `ValueError` returned a value). flash-iq3 at 8K passed 6 of 13 in the repeat and 13 of 13 in the first pass, whose
  answer differed.
- Least RAM available during the runs in the limit and 8K tables: 6.2-8.0 GiB for Flash-Next and the Tiel pair,
  18.1-22.2 GiB for the dense models. The 1-minute load reached 20.4 in the Flash-Next runs at the limit (the engine's
  own CPU expert threads) and 12.3 in Tiel's 8K run, which started right after one; the dense repeats and variants at
  the limit stayed under 3.2.

## Prompt filled to the context limit (Oct 25, greedy)

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

"Before" is what the profile ran before the Oct 24-25 changes (on the engine Automatic picked then), measured the same
day with the same AppImage unless the row says otherwise.

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

## Prompt of about 8K tokens (Oct 25, greedy)

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

On Oct 25 Cyber Tiel was measured at 8K only with its old 27 CPU layers (on Oct 26 with 26, sampled). Tiel (with 25
and with 27 CPU layers) and Cyber Tiel fail one check at 8K: `next_head((0,0),(1,0),2.5,4)` returns `(1.0, 0)`
instead of raising `ValueError`. The Swift IQ3_XXS and second Swift IQ3_S rows are from window 8 (its other processes
are noted above), the others from window 7. 1-minute load up to 8.0 (Flash-Next) and 7.1 in the others.

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

- A prompt beyond 131,072 tokens on the dense models (their profiles stop there).
- Saluki's 1,536 MiB physical reserve at 8K, and Tiel and Cyber Tiel with 26 CPU layers while the desktop holds more
  than 1,479 MiB of VRAM (by the router's check they start while it holds up to 2,002 MiB).
- The Swift profiles with more VRAM held by the desktop than in window 10 (up to 1,734 MiB at their starts). They keep
  the 1,024 MiB physical reserve, and the least free VRAM logged in their window 10 runs was 803-2,106 MiB, against
  the 768 MiB under which the worker cancels a running request.
- The dense profiles on this branch's 0.2.6 rebase (their logits at 33 positions of an 8K prompt are bit-identical to
  d2b0565b's, whose AppImage ran the profile tables), and Flash-Next on it beyond 8K.
- Windows, CUDA and SYCL builds, and other GPUs.
