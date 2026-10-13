# RX 9070 XT with 32 GB RAM: an optional Linux profile

This fork adds a configuration helper and a memory-limited launcher for one
RX 9070 XT with 16 GB VRAM and 32 GB system RAM. The engine, server and ordinary
setup defaults are unchanged. The profile takes effect only when you apply it.

Measured on October 13, 2026: Ryzen 7 7800X3D (8 physical cores), RX 9070 XT
(gfx1201), 30.9 GiB RAM, CachyOS, system ROCm 7.2, an NVMe SSD with Btrfs,
Strata engine 0.1.44. The engine measured about 50.6 GB/s host-to-device copies.
Windows, other cards, other CPUs and concurrent requests have not been tested
with this profile. This is a measured starting point, not a speed guarantee.

## Install and apply

Use the normal installer first. The Coder download is about 58 GB; use a data
directory on a drive with enough room. The setup steps and driver requirements
are in [AI_SETUP.md](AI_SETUP.md).

```sh
./setup.sh --yes --family coder --model IQ1_M --context 131072 --no-start
.venv/bin/python tools/hardware_profile.py apply --config strata-coder-iq1_m.json
.venv/bin/python tools/hardware_profile.py run \
  --config strata-coder-iq1_m-rx9070xt-32gb.json
```

Add `--data-dir /path/to/Strata-data` to setup to put model files on another
drive. The helper preserves the model paths, tokenizer, hipBLASLt tuning table,
port, API key and other unrelated settings. It creates a separate configuration;
the setup-generated one remains available for comparison or rollback. It refuses
to overwrite an existing tuned file unless given `--force`.

The launcher uses the config's port (8080 if absent), binds to localhost unless
the config says otherwise, and refuses a non-loopback host without an API key.
`--port 8096` overrides the port; `--open` opens the chat page when ready.

Linux with a systemd user manager and the cgroup v2 memory controller is required.
No root access is needed. The server and its engine run in one `strata-local.scope`,
limited to 20 GiB of charged memory and no swap. Another profile launcher cannot
start a second model under that same scope name. Stop the running model with:

```sh
systemctl --user stop strata-local.scope
```

The limit includes file cache and the process tree. It is not reserved RAM and
does not guarantee containment of every driver/kernel allocation. If the group
exceeds its limit, a process in it can be killed. Keep room for the desktop.

## What the profile changes

- 131072-token context; int8 KV, with 32768 cells per streamed layer in VRAM.
  The 128K backing KV uses about 1.55 GiB of pinned host RAM at startup.
- At most 11 GiB of resident experts, ranked by the model's own expert profile.
  The engine can clamp this budget lower if available RAM is insufficient.
- 3072 MiB VRAM reserve; automatic expert-cache size and prompt chunk size.
- Guarded page-locking in steps (`STRATA_PIN_GUARD=2`), with 4 GiB sizing and
  pinning headroom. The GPU can compute resident misses over PCIe. Upload-stage
  buffers stay pageable.
- Unbuffered file-tier reads (`STRATA_UNBUFFERED_LOAD=1`), asynchronous adaptive
  expert-cache swaps (`--adapt-async 1`) and helper affinity (`--aux-cpus auto`).
  These reduce mapped-file page faults and blocking work on the host core.

It preserves the installed MTP and sampling settings. It does not install drivers,
change zram, change system swap, patch kernels or publish model files. GPU/CPU
rounding and asynchronous placement can change greedy output compared with the
original configuration. The profile rejects CUDA, multi-GPU, batching, replicas
and image configurations rather than assuming that these measurements apply.

## Coder IQ1_M measurements

An earlier pageable, mapped-file configuration stalled near 0.6 tokens/s during
a writing request. No repeatable cold-start A/B baseline was completed: an earlier
uncontained engine reload triggered global OOM. Do not treat the results below as
a controlled percentage improvement over upstream defaults.

The final profile was tested with fresh mixed documentation/code prompts, no
prefix-cache reuse, temperature 0 and 128 generated tokens:

| Input tokens | Prompt read | Generation | Read time | Total request |
| ---: | ---: | ---: | ---: | ---: |
| 65547 | 749.8 tokens/s | 42.8 tokens/s | 87.4 s | 90.5 s |
| 130012 | 839.5 tokens/s | 48.9 tokens/s | 154.9 s | 157.6 s |

The nearly full-window run finished with about 2.1 GiB available system RAM.
The scope recorded zero OOM events/kills. The runs used a 1 GiB available-RAM
abort threshold. These are single prompts with short answers; task, expert-cache
placement and drafting acceptance affect speed. A filled window does not mean
every later request must reread the entire history: matching prefixes can be reused.

A higher-memory trial generated sampled prose at 57.8–58.6 tokens/s, but left
less than 1 GiB available after a longer prompt. That configuration was not kept.
Reducing its RAM budget retained 34.5–49.9 tokens/s on three 256-token prose
answers. The profile above reserves additional desktop VRAM and uses less RAM.

Coder's IQ1_M name refers to the pruned Coder family, with roughly 23 GB of expert
weights; it is not simply the full model quantized uniformly to one bit.

## Qwen IQ3_XXS

Use the supported ISTA-DASLab GSQ-RCO IQ3_XXS files. The full model has about
43 GB of experts, so this machine uses its NVMe file tier for many more misses.
Its two GGUF shards total about 75.8 GB; the 28.8 GB second shard can be shared
with Coder only after checking its SHA-256 against the repository's metadata.
The packed `experts.bin` adds about 40 GiB on disk and enables the unbuffered
file tier. Model files remain outside this repository.

Install another model without starting it, then apply the same opt-in helper:

```sh
./setup.sh --yes --family qwen --model IQ3_XXS --context 131072 --no-start
.venv/bin/python tools/hardware_profile.py apply --config strata-iq3_xxs.json
.venv/bin/python tools/hardware_profile.py run \
  --config strata-iq3_xxs-rx9070xt-32gb.json
```

Stop the first model before starting the second. Use a separate pack, tokenizer
and full-model expert profile; do not point IQ3_XXS at the Coder pack or profile.
Do not infer full-window speed from a short prompt, or model quality from throughput.

## Repeat the measurements

IQ3_XXS with this profile on the same RX 9070 XT / 32 GiB machine:

| Uncached input tokens | Output tokens | Input tokens/sec | Generation tokens/sec |
| --- | --- | --- | --- |
| 65,547 | 128 | 431.7 | 16.5 |
| 130,012 | 128 | 440.5 | 28.0 |

The near-full-window request took 299.8 seconds overall, including 295.1 seconds
to read the prompt. Neither test triggered the RAM guard or an OOM. These are
single reference-summary tests with short answers, not a throughput guarantee.
Short writing trials ranged from 15.4 to 38.0 tokens/sec. Expert placement and
draft acceptance affect the result; larger context is not inherently faster.

For capability comparisons, use the fixed game, Python and SVG tasks in
[the practical benchmark suite](../bench/practical/README.md). Reports preserve
artifacts and checks separately from speed and manual visual review.
The [first IQ1_M versus IQ3_XXS results](PRACTICAL_BENCHMARKS.md) include failures
and the review limitations.

The API benchmark runs against an already-running server and starts no additional
engine. For example, at port 8096:

```sh
.venv/bin/python tools/benchmark_local_api.py --url http://127.0.0.1:8096 \
  --temperature 0.7 --max-tokens 256 --repeats 3 --output results.json
```

Add `--prompt-file reference.txt` to measure longer prompts and `--timeout 1800`
for long prefills. The output keeps engine timings, actual input/output token
counts, cache reuse and response text. Run clients sequentially and compare the
same prompts, output length, temperature and warm/cold state.

For a large-context test, use the RAM monitor around the benchmark:

```sh
.venv/bin/python tools/benchmark_guarded.py --output memory.json -- \
  .venv/bin/python tools/benchmark_local_api.py --url http://127.0.0.1:8096 \
  --prompt-file reference.txt --repeats 1 --timeout 1800 --output results.json
```

It stops `strata-local.scope` if available system RAM falls below 1 GiB. Its
samples include whole-system available RAM and driver-reported free VRAM.
Sampling can miss brief peaks; this is a test aid, not a guarantee against OOM.

The helper's tests need no GPU, downloads or systemd:

```sh
python3 -m unittest tools.test_hardware_profile
```
