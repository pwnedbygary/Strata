# Flash Next / Gyro performance investigation

October 14, 2026. The [4070 Super report](https://www.reddit.com/r/Qwen_AI/comments/1x5mr7a/qwen_38_flash_next_running_at_12vram32gb_ram/)
claims roughly 900–1800 prefill tokens/s and 33–42 decode tokens/s with 12 GB VRAM,
32 GB RAM, Gyro-M/S, Q4 streamed KV and a 256K limit. A public recipe is now available in [Gitshop77/GyroStrata](https://github.com/Gitshop77/GyroStrata).
Its Windows/CUDA benchmark uses synthetic Python continuation, thinking off, 256-token
replies and prefix reuse; it is not the same workload as our coding and screenshot tests. These are reported numbers, not reproduced RX 9070 XT results.

The [publisher's model card](https://huggingface.co/agentionai/Qwen3.8-Flash-Next-Gyro-GGUF)
lists 27.64 GiB of GPU weights for Gyro-S and 34.98 GiB for Gyro-M, compared with 43.80
GiB for GSQ-RCO IQ3_XXS. Its quality measurements are publisher results, not an independent
review. Smaller experts could reduce SSD traffic at our memory budget; this has not
been measured here. Download sizes are larger: 58.5 GB and 92.0 GB respectively because
they include a disk-backed n-gram table.

Gyro uses custom trellis expert types and activation rotations. Its TQ1_0/TQ2_0 filenames
are size classes, not stock llama.cpp compatibility. The [public Strata rc2 fork](https://github.com/agentionai/Strata/blob/rc2/docs/GYRO.md)
requires the matching agentionai llama.cpp dependency. It documents experimental HIP
builds for gfx1201, with end-to-end AMD validation on gfx1151, not our RX 9070 XT.
It is not a drop-in model-file replacement for this fork's existing IQ3_XXS engine.

Our current Flash profile uses IQ3_XXS, an 11 GiB resident expert budget, 3 GiB VRAM reserve,
int8 KV with 32K resident, a 128K ceiling and MTP drafting. The Reddit report instead
uses a 16 GiB RAM expert tier, Q4 KV, MTP off, suffix speculation and different weights.
Each setting needs a matched test; increasing the RAM tier alone can consume the worker's
20 GiB limit. More VRAM on AMD does not imply faster CUDA-specific kernels.

Next comparison: counted fresh coding prompts and cached follow-ups on the existing
IQ3_XXS model, followed by bounded memory/speed trials for prefill chunk sizing, MTP versus
suffix drafting and expert-cache allocation. Keep output correctness and fresh/cached
prompt times separate. Gyro should get an isolated compatibility/parity build before
large downloads or an advertised working profile. No Gyro weights have been downloaded
or performance reproduced on this system yet.

## Public fork source audit

Inspected Gitshop77/GyroStrata at `d940059abc5c643b8d98e9f8cc76cf62c730bf1b`.
Reconstructed its pinned Strata base `a0116b2782a5b82622358c04a06496485d12b2d6`
and applied the supplied patch in an isolated local directory. All 47 changed-file
SHA-256 hashes match `pins.json`. The async-worker regression passed with the Linux
C++ compiler. The suffix-policy regression also passed after replacing the Windows-only
`_putenv_s` test calls with Linux `setenv`; production code was unchanged for that test.
These are CPU unit checks, not GPU parity or model throughput measurements.

The source audit found restrictions that matter for this machine:

| Change | Applicability here | Work needed |
| --- | --- | --- |
| SSD reads overlap RAM expert compute | The dispatch enabling branch is guarded by `_WIN32` | Audit Linux source-buffer lifetime and read synchronization before enabling it on HIP |
| Hot disk experts replace cold RAM experts | Disabled with adaptive async scheduling, multi-GPU, batching or overlapping windows | Our Flash profile uses `--adapt-async 1`; compare a synchronized path before changing that setting |
| Suffix cost reprobes | Backend-independent and opt-in | Measure recovery and overhead on existing IQ3_XXS; passing unit tests alone does not show a speed gain |
| Trellis quantization and activation rotations | Requires custom agentionai llama.cpp and CPU/GPU/prefill/pack support | Build and run HIP numerical parity before loading Gyro weights |
| Conversation checkpoints | May improve repeated-prefix workloads | Check memory costs and changed-prefix correctness separately from fresh prefill |

The dependency is pinned to agentionai llama.cpp
`dc255f2a4b6e4211b555b0c05260b2523281f314`. Replacing our current dependency wholesale
could affect the dense models and vision path; this audit has not changed either.
The existing IQ3_XXS GGUF does not need trellis support to test scheduling improvements.

Recommended implementation order: isolate the suffix reprobe change first, then audit
and port SSD/RAM overlap, then test RAM rebalancing with adaptive async disabled. Keep
each feature opt-in and compare the same coding prompt, output, cached follow-up and
physical RAM/VRAM samples against the current build. Maintain desktop memory reserves;
the fork's 512 MiB RAM floor is too small for the earlier pressure observed here.
Only after HIP trellis parity passes should a Gyro-M download be considered. Its pinned
GGUF is 91,965,774,272 bytes and the recipe budgets 120 GiB for weights and pack together.
Any downloaded weights belong in this checkout's `models/` directory.

The opt-in suffix policy change has now been ported and tested in the source build
(see below). It is not enabled in the regular AppImage or live profiles. No Gyro
weights have been downloaded, and the NVIDIA figures have not been reproduced on AMD.

## First port: suffix cost reprobes

`STRATA_LOOKUP_REPROBE_ROUNDS=128` enables the imported policy adjustment; unset,
zero or invalid values keep the old policy. Accepted values are 16–300. The policy
retries stale intermediate suffix window sizes and refreshes their measured costs.
The change does not add expert memory or alter the token verifier.
Attribution: Gitshop77/GyroStrata, MIT, revision above.

Built the HIP engine on the RX 9070 XT system. Existing policy tests and the imported
cold-cost recovery regression pass. A 5,000-round deterministic trace of window picks,
chain lengths and costs matches the original policy byte-for-byte when the option is
unset. CUDA and SYCL were not built: their toolchains are unavailable here.

Same-day single paired run, existing QFN IQ3_XXS, Ryzen 7800X3D, 32 GiB RAM at 4800 MT/s,
RX 9070 XT 16 GiB, NVMe. Both configurations use the same source binary, 9 GiB RAM expert
tier, 3 GiB VRAM reserve, int8 KV, 128K ceiling, adaptive async on, MTP off and suffix
speculation. Input is 8,186 counted tokens; each reply is 278 tokens.

| Policy | Fresh prefill tok/s | Fresh output tok/s | Cached output tok/s | Minimum free physical VRAM | Minimum available RAM |
| --- | ---: | ---: | ---: | ---: | ---: |
| Default | 354.6 | 10.9 | 13.8 | 1,572 MiB | 10.304 GiB |
| Reprobe 128 | 362.2 | 10.8 | 14.0 | 1,483 MiB | 10.131 GiB |

Fresh and follow-up answer bytes match between policies. This one pair shows no clear
speed gain; prefill timing differences do not demonstrate a benefit from a decode policy.
Keep the option disabled in normal profiles. Raw prompts, answers, timings and 1-second
memory samples are in [the result directory](../bench/results/2026-10-14-gyro-policy/).
The router's 3 GiB available-RAM and 512 MiB physical-VRAM guards remained active.
Sampling cannot rule out shorter spikes; this was not a 128K context fill or endurance test.
The temporary two-profile source server was stopped after testing and the normal
AppImage server with ten profiles was restored, unloaded.

## Linux/HIP ports: SSD overlap and RAM rebalancing

The source now supports `STRATA_RESIDENT_IO_OVERLAP=1` on Linux as well as Windows.
A persistent host worker reads missing file experts while the CPU pool computes resident
experts, then joins before preparing the file jobs. The demand vector and source buffers
remain alive until that join, including early returns. Peer/remote dispatch, activation
rotation exchange and non-native kernels retain their old path. The first mixed dispatch
logs activation, so an enabled variable is not mistaken for proof that overlap ran.

`STRATA_RAM_REBALANCE=512` bounds hot file-to-RAM promotions per completed reply.
Values 0–512 are accepted; omission and invalid values disable it. Promotion keeps the
existing RAM capacity, replaces only same-layer cold blobs after successful reads, and
excludes GPU-owned blobs. It requires single-GPU, unbatched, synchronized dispatch,
`--adapt-async 0`, no overlapping windows and no active exchange rotation. The engine
waits for pending commits and synchronizes the GPU before replacing bytes. Do not assume
it runs with the normal profile's `--adapt-async 1` setting.

HIP build and four source tests passed; an additional GPU-backed RAM integrity regression
checked capacity, ownership, promoted bytes, evicted file fallback and reversed heat.
CUDA and SYCL were not built because their toolchains are unavailable on this host.
The default-path fresh and cached answer bytes match the pre-port run on this workload.
This is not a claim of exhaustive backend or model parity.

Same-day 8,186-token coding prompt, suffix speculation, MTP off, 128K ceiling, int8 KV,
9 GiB resident RAM tier and 3 GiB VRAM reserve. Same hardware as above. The final
synchronized pair ran after compilation finished:

| Synchronized configuration | Fresh prefill tok/s | Fresh output tok/s | Cached output tok/s | Minimum free physical VRAM | Minimum available RAM |
| --- | ---: | ---: | ---: | ---: | ---: |
| Features off | 341.1 | 10.6 | 13.5 | 1,536 MiB | 10.340 GiB |
| Overlap + 512 promotions | 354.6 | 10.6 | 15.3 | 1,396 MiB | 10.314 GiB |

The combined run promoted 512 experts after each reply in 651.6 and 647.5 ms. Cached
output rate improved about 13% in this one pair. Reply lengths differed (284 versus
278 tokens), so it is not a matched-output latency comparison or a sustained speed claim.
All fresh and follow-up code answers passed the same thirteen checks; the synchronized
answers were not byte-identical. The existing tail-skip path and adaptive expert placement
make window/placement changes relevant to numerical output. No broad code quality or
long-context retrieval evaluation was performed here.

Earlier asynchronous exploratory runs measured 10.0/12.8 output tok/s with features off
and 9.7/13.7 with overlap. Compilation overlapped these trials; they are retained for
transparency, not used to claim performance improvements. The synchronized pair was not
subject to that compile load. Overlap and rebalancing contributions have not been isolated
in the final pair. Both new features remain disabled in the normal profiles.

[Raw prompts, replies, code checks, engine logs, timings, memory samples and build hashes](../bench/results/2026-10-14-gyro-io/).
The 3 GiB RAM and 512 MiB physical-VRAM guards stayed active. These are short 8K tests,
not endurance or filled-128K tests. No Gyro weights were downloaded or trellis kernels ported.

A separate local executable was built as
`dist/Strata-RX9070XT-Gyro-IO-experimental-x86_64.AppImage`, with the tested source engine
bundled for Flash. The regular AppImage was preserved and restored with all ten profiles,
unloaded. An isolated eleven-profile registry (normal entries plus one experimental Flash
entry) is at `local-tuning/gyro-io/experimental-router.json`. It uses a 9 GiB RAM tier and
the synchronized settings above. This local registry contains machine-specific paths and
is not committed. Stop the current server before running the experimental image:

```sh
./dist/Strata-RX9070XT-Gyro-IO-experimental-x86_64.AppImage \
  --registry local-tuning/gyro-io/experimental-router.json \
  --memory-floor-gib 3 --vram-floor-mib 512 --port 8096
```

Rebuilding the experimental image requires `tools/build_appimage.py --flash-engine
build-hip/strata` in addition to its appimagetool and vision-engine arguments; its default
Flash bundle remains `engine/strata`. Source options alone do not update that bundled binary.
