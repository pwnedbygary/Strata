# Strata on an RX 9070 XT + 32 GB RAM

A personal fork of [Niko1221/Strata](https://github.com/Niko1221/Strata), tuned and tested
with **Qwen3.8-Flash-Next IQ3_XXS**, one 16 GB AMD GPU, 32 GB system RAM and an NVMe SSD.
The aim is usable local coding and creative work with a 128K context window on this PC.

This fork adds an **opt-in hardware profile**, a memory-limited launcher, practical
benchmarks and a generate → independent review → revise workflow. The engine,
server and ordinary installer defaults are unchanged. Model weights are not included.

<img src="docs/media/rx9070xt-32gb/snake-desktop.png" width="850" alt="IQ3-generated Neon Serpent Snake game running on desktop after two independent review rounds">

*An actual locally generated game, after two review rounds. Keyboard, mobile controls,
seeded food, growth and restart were checked. [Download the reviewed HTML](docs/examples/iq3_xxs/snake-reviewed.html)
and open it in your browser. Remaining issues are documented below.*

## The tested PC

Measurements below were recorded on **October 13, 2026**.

| Component | Tested configuration |
| --- | --- |
| GPU | AMD Radeon RX 9070 XT, 16 GiB VRAM, gfx1201 |
| CPU | Ryzen 7 7800X3D, 8 cores / 16 threads |
| RAM | 32 GB installed; 30.9 GiB reported by Linux |
| Storage | NVMe SSD, Btrfs |
| OS / runtime | CachyOS Linux, system ROCm 7.2 |
| Strata engine | 0.1.44 |
| Model | ISTA-DASLab GSQ-RCO Qwen3.8-Flash-Next IQ3_XXS |
| Serving | One model, one request at a time; images disabled |

This is an NVMe-backed full-model configuration. The complete expert pack does not
fit in the GPU and resident RAM caches; misses read weights from SSD. The upstream
setup guide normally recommends more RAM for this model. These results do not cover
Windows, other GPUs, concurrent requests or vision.

## What the tuning does

| Setting | This profile |
| --- | --- |
| Maximum context | 131,072 tokens |
| KV cache | int8; 32,768 resident cells per streamed layer |
| Host KV backing | About 1.55 GiB of pinned RAM allocated at startup |
| Resident expert budget | Up to 11 GiB, guarded page-locking |
| VRAM reserve | 3,072 MiB; automatic expert-cache and prefill sizing |
| File tier | Unbuffered NVMe reads |
| Overlap | Asynchronous adaptive expert swaps and automatic helper affinity |
| Process limit | systemd user scope: 20 GiB charged memory, zero process swap |

The profile keeps the model's MTP/speculation settings. The launcher bounds the server
and engine together and refuses an unprotected public bind. A separate test guard
stops the scope when available system RAM falls below 1 GiB.

An earlier uncontained configuration was OOM-killed. Higher-memory trials were faster
but left too little room for the desktop, so they were not retained. The current
review experiments kept at least **2.66 GiB available RAM** and did not trigger the guard.
The scope is not a guarantee against every GPU driver/kernel allocation or brief peak.
System swap, zram and drivers were not changed by this profile.

[Settings, tuning history and memory limits](docs/HARDWARE_RX9070XT_32GB.md)

## Measured generation speeds

These are real individual requests, not an advertised constant speed. Output lengths,
expert placement, SSD reads and draft acceptance differ between tasks. The writing
trials used temperature 0.7; the capability and context tests used temperature 0.

| IQ3_XXS task | Input / output tokens | Generation | Result |
| --- | ---: | ---: | --- |
| Short writing trials | 46 / 128 each | 15.4–38.0 tokens/s | Three trials; cold/warm behavior varied |
| Python interval merging | 308 / 329 | 12.4 tokens/s | 11/11 functional checks passed |
| Editable lighthouse SVG | 279 / 2,511 | 22.9 tokens/s | 7/7 structural checks; rendered successfully |
| Complete Snake game | 472 / 6,467 | 19.6 tokens/s | 11/11 gameplay checks; desktop/mobile controls worked |
| Full code-review revision | 7,482 / 7,083 | 14.2 tokens/s | Useful refactor, but introduced UI regressions |
| Focused review patch | 8,115 / 2,694 | 17.0 tokens/s | Working result; 11 core + 20 review-specific checks passed |

The first Snake attempt exhausted a 6,144-token cap. Raising the cap to 16,384 allowed
a new IQ3 attempt to finish. The focused patch returned nine literal edits, rather than
regenerating the entire file. [Practical comparisons and source review](docs/PRACTICAL_BENCHMARKS.md)

### Near-full 128K context

| Uncached input | Output | Prompt reading | Generation | Whole request |
| ---: | ---: | ---: | ---: | ---: |
| 65,547 tokens | 128 tokens | 431.7 tokens/s | 16.5 tokens/s | 159.6 s |
| 130,012 tokens | 128 tokens | 440.5 tokens/s | 28.0 tokens/s | 299.8 s |

The nearly full-window prompt took **295.1 seconds to read** and 4.6 seconds to generate
its short answer. It completed without an OOM or RAM-guard abort. These reference-summary
runs test capacity and throughput; they do not establish long-context answer quality.
The faster second result does not mean that larger context inherently increases speed.
**25–30 tokens/s happened in one near-full test; it is not sustained across every task.**

[Measurement JSON](docs/examples/iq3_xxs/measurements.json) ·
[Selected engine log lines](docs/examples/iq3_xxs/engine-excerpts.log)

Excerpt from the recorded engine output:

```text
strata generate: KV streaming: 32768 of 131072 cells per QSA layer in VRAM, the K/V in 1.55 GiB of pinned RAM
strata generate: the file tier reads unbuffered (STRATA_UNBUFFERED_LOAD=1)
strata serve: prompt 130012 tokens = 0 reused + 130012 read in 295115 ms (440.5 tok/s), 128 generated in 4567 ms (28.0 tok/s), drafts accepted 69 of 100, 6 checkpoints
```

## What it built

### A playable game, improved through review

The final Snake prototype has a DOM-free simulation factory, copied state snapshots,
deterministic food placement, a full-board win, accessible direction labels, mobile
scrolling and a loop that stops while paused. An independent cycle test filled the
400-cell board after 39,671 moves.

<img src="docs/media/rx9070xt-32gb/snake-mobile.png" width="300" alt="Reviewed Snake game on a narrow mobile layout with labelled direction buttons and a visible header">

The first review-driven rewrite broke startup and pause controls. Independent review
caught those regressions; a second, focused patch fixed them. Minor follow-ups remain:
calling the new factory without a seed leaves food uninitialized, one pending callback
runs after death, and announcements use internal words such as “dead.” The unused engine
time field also remains. This is a useful prototype, not a claim of flawless code.

[Review/revision experiment, checks and timing](docs/REVIEW_REVISION_BENCHMARK.md)

### Editable vector artwork

<img src="docs/media/rx9070xt-32gb/lighthouse.png" width="420" alt="IQ3-generated SVG lighthouse with storm clouds, waves and a warm light beam">

The model wrote [this standalone SVG](docs/examples/iq3_xxs/lighthouse.svg) as code:
named sky/sea/lighthouse/beam layers, reusable gradients, title/description metadata,
no raster assets or external dependencies. It passed the specified palette and structure
checks. The illustration is clear but simple; this is SVG drafting, not raster image generation.

### Small library code

[The generated Python function](docs/examples/iq3_xxs/merge_intervals.py) merges touching
and overlapping intervals in O(n log n), preserves the input, and rejects malformed
intervals and boolean endpoints. It passed the 11 benchmark cases. Its outer-input
validation could still be more defensive. Tests and source review are both needed.

## Install this profile

Use an NVMe location with room for the download, pack and build. The two GGUF shards
are about **75.8 GB**, and the packed experts add about **40 GiB** plus dense weights,
MTP and build/cache files; allow at least 150 GB free for a fresh installation.

Follow [AI_SETUP.md](docs/AI_SETUP.md) and [AMD_HIP.md](docs/AMD_HIP.md) for the normal
installer and AMD runtime prerequisites. This is an explicit, opt-in 32 GB file-tier
experiment; apply the bounded profile before starting the model.

```sh
git clone --branch codex/rx9070xt-32gb-profile https://github.com/pwnedbygary/Strata.git
cd Strata
./setup.sh --yes --family qwen --model IQ3_XXS --context 131072 --no-start
.venv/bin/python tools/hardware_profile.py apply --config strata-iq3_xxs.json
.venv/bin/python tools/hardware_profile.py run \
  --config strata-iq3_xxs-rx9070xt-32gb.json --port 8096 --open
```

Linux, a systemd user manager and cgroup v2 memory accounting are required by the
bounded launcher. The helper preserves model paths and writes a separate configuration.
The server is local at `http://127.0.0.1:8096/`, with an OpenAI-compatible API at `/v1`
and an Anthropic-compatible API at `/v1/messages`. A public bind requires an API key.

Stop the server with:

```sh
systemctl --user stop strata-local.scope
```

`experts.bin` is the packed expert-weight file used by this setup, not swap or chat
history. Keep it: the NVMe file tier depends on it. The GGUFs, pack and MTP are excluded
from Git and are not downloaded by cloning this fork.

## Repeat the practical tests

Run one client at a time against the already-running server. Keep prompt, sampling,
output budget and review mode consistent. The reports retain failed attempts too.

```sh
.venv/bin/python tools/hardware_profile.py benchmark \
  --cases merge_intervals,lighthouse_svg --output-dir benchmark-results/iq3-code-art
.venv/bin/python tools/hardware_profile.py benchmark \
  --cases snake --max-tokens 16384 --output-dir benchmark-results/iq3-snake
```

Add `--browser-checks` after installing the optional Playwright dependencies in
[the practical suite guide](bench/practical/README.md). Use the
[review-driven runner](docs/REVIEW_REVISION_BENCHMARK.md) to provide an actual source
review and measure whether a revision fixes findings without introducing regressions.
The request protocol uses fixed prompts and seeds; adaptive placement means outputs
are not guaranteed bit-identical across runs or hardware.

Helper tests need no model, GPU or downloads:

```sh
python3 -m unittest tools.test_hardware_profile tools.test_practical_checks tools.test_benchmark_revision
```

## Evidence and upstream credit

- [Exported examples, measurements and logs](docs/examples/iq3_xxs/README.md)
- [Hardware profile and tuning history](docs/HARDWARE_RX9070XT_32GB.md)
- [Practical model comparisons](docs/PRACTICAL_BENCHMARKS.md)
- [Independent review and revision results](docs/REVIEW_REVISION_BENCHMARK.md)
- [Original upstream README](README.upstream.md), [engine details](docs/DETAILS.md),
  [model guide](docs/MODELS.md) and [MIT license](LICENSE)

The inference engine, server, installer and original project belong to
[Niko1221 and the Strata contributors](https://github.com/Niko1221/Strata).
This fork contributes the optional profile, measurement tools, review workflow and
these hardware-specific results. Other translated READMEs describe the upstream project.
