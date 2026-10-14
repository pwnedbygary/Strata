# Experimental MoE model preparation

This fork's RX 9070 XT / 32 GB profile remains a Flash-Next profile. Other MoE models need their own execution path, tensor layout and supported quantization formats. Sharing the MoE label does not make their weights interchangeable.

The installed HIP engine advertises `qwen4exp` and `qwen35moe` through `engine/strata --families`. Qwen35 has a separate engine; it does not use the Flash-Next expert pack or its bounded NVMe expert tier. In hybrid mode, Qwen35 keeps all routed expert weights in host RAM and duplicates a cache in VRAM. Its attention cache also differs. The Flash-Next 128K settings cannot be copied directly.

## Opt-in tools

`tools/moe_profile.py inspect MODEL.gguf` reads headers to report architecture, expert formats and expert bytes without loading the weights. `prepare` accepts only the current 35B Qwen35 geometry on HIP. It rejects incompatible expert projection formats, known layout differences, excessive host expert allocation and missing MTP metadata. The engine still performs the complete layout validation; passing the Python checks is not a guarantee that a model will load.

Example, for a compatible file with its own exported tokenizer:

```sh
.venv/bin/python tools/moe_profile.py prepare \
  --gguf /absolute/path/model.gguf \
  --base-config strata-iq3_xxs.json \
  --tokenizer /absolute/path/tokenizer \
  --output strata-moe-trial.json
.venv/bin/python tools/moe_profile.py run --config strata-moe-trial.json
```

The trial uses 8K context, 6 GiB expert VRAM, seven CPU threads, prefill 256 and MTP off. These are conservative trial settings, **not measured optimal settings**. It removes Flash-specific flags and environment settings, retains the API configuration, requires available RAM above expert allocation plus 4 GiB, refuses a second active scope and uses a 20 GiB process-tree limit with no swap. No upstream engine or default configuration changes are made.

`tools/gguf_no_mtp.py SOURCE OUTPUT` adds an explicit zero-MTP metadata field to a separate single-file, 40-layer Qwen35 GGUF with no MTP metadata or block 40 tensors. It preserves tensor directory entries and verifies the copied tensor payload with SHA-256. It does not convert quantization or fix tensor shapes, and its result must still pass engine validation.

## Trials on October 14, 2026

Hardware: RX 9070 XT 16 GiB, Ryzen 7800X3D, approximately 31 GiB system RAM, HIP/ROCm 7.2; engine 0.1.44. Both startup attempts exited before serving requests. There are no throughput or output-quality results for these candidates.

| Candidate | Host expert weights | Result |
|---|---:|---|
| Unsloth Qwen3.6-35B-A3B UD-IQ3_XXS, revision `5bc3e238d916f48a861bac2f8a1990a0e9b7e98d` | 11.11 GiB | Rejected: IQ3_S down projections unsupported by the installed native kernels |
| chtisgit Qwen3.6-35B-A3B GSQ hybrid, revision `526e747844ac1bc2ae1ce5f771a0af366eeb13ef` | 8.44 GiB | Missing explicit MTP count; metadata-only copy passed payload verification but engine rejected shared expert gate shape `[2048, 1]`, requiring `[2048]` |

Sources: [Unsloth artifact repository](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF), [GSQ conversion repository](https://huggingface.co/chtisgit/Qwen3.6-35B-A3B-2Bit-GSQ-hybrid-GGUF). The GSQ original SHA-256 was `8e50912f5d0703401ca21b09deb2ee8a84d03536ade6fb44815fcb40a0b03596`; copied tensor payload SHA-256 was `e22c6ef3ac4ba44dc36e50b4514a8c2503f51ef48bc3642080a1555994ae325b`.

Next engine work requires a reviewed layout adapter or compatible conversion, numerical comparison against a reference implementation, backend builds for touched engine files and same-day performance measurements. Mixtral, DeepSeek and other architectures are not supported by this tool. CUDA and SYCL trials were not performed.

## Desktop memory pressure

The October 14 Flash-Next termination was a global kernel OOM, not a recorded 20 GiB scope-limit event. Browser videos can add both RAM and VRAM pressure. A process-tree limit does not reserve memory against other applications, and zram's compressed storage consumes real RAM. The launcher now clears a failed scope before a new start; it does not raise memory limits or change swap configuration.

Tests, without a GPU or downloads:

```sh
.venv/bin/python tools/test_moe_profile.py
.venv/bin/python tools/test_hardware_profile.py
```

## Native engine development update

The development HIP build now accepts the singleton shared-expert gate when `STRATA_Q36_SINGLETON_GATE=1` is set. The allowance is restricted to Qwen35's `ffn_gate_inp_shexp.weight`, with shape `[embedding_length, 1]`; no bytes are reshaped or requantized. With the variable absent or set to `0`, the original strict layout check remains in force. Synthetic tests cover default rejection, opt-in acceptance, non-singleton rejection, other tensor rejection and Flash-Next rejection.

A second native fix supplies planar `ActQ` activations to the optimized Q2_0 CPU gate/up kernels. Previously the Qwen35 hybrid driver filled only `nact`, while that kernel read `act`; the GSQ model crashed during warm-up through a null pointer. Other formats still use their existing activation path. The development build subsequently loaded the GSQ model and completed warm-up: 733 tensors, 4.77 GiB dense GPU weights, 5.57 GiB cached experts, 8.44 GiB pinned host experts, 8K context. These allocation figures are engine logs, not total process or GPU usage.

The executable is `build-hip/strata`, not the installed `engine/strata`. The local development config is `strata-qwen35-native-dev.json`; generated configs and model data are not part of the repository. Do not use the conservative preparation tool to launch this layout variant yet: it intentionally still rejects the singleton gate. HIP compiled successfully; CUDA and SYCL toolchains are not installed on this PC, so their builds remain unverified. Numerical reference parity and a same-day Flash-Next identity comparison remain outstanding. This is experimental work, not a universal-model release.

## Native expansion order

The user's local Swift 27B and Underdog-Saluki 27B models have architecture `qwen35`, with 64 layers, hidden width 5120 and dense feed-forward width 17408. Tiel/Cyber-Tiel 35B have `qwen35moe`, 40 main layers plus MTP and 256 routed experts. The local 0.8B `qwen35` model is a smaller correctness fixture for a future dense path (24 layers, width 1024, feed-forward 3584).

Native support needs these distinct stages:

1. Finish Qwen35 MoE validation: reference logits, CPU/GPU expert agreement, supported quantization combinations, context and memory tests, then same-day speed tuning.
2. Add a dense Qwen35 path: shared GDN/attention primitives, dense SwiGLU instead of routed experts, metadata-derived dimensions and buffer sizes. The 0.8B model checks geometry before testing the 27B models. Merely recognizing `qwen35` is insufficient: current MoE buffers and layout guards require experts.
3. Separate reusable weight storage, GPU cache placement and CPU/GPU scheduling from each family's forward pass. Attention styles, rotary embedding, normalization, router scoring, expert activation and cache state remain explicit family capabilities.
4. Add other MoE families individually with reference implementations and supported-format tests. Flash-Next's NVMe caching can be reused where its data and scheduling contracts fit, but its forward pass cannot be applied to arbitrary models.

The intended direction is Strata's own engine. A separate runner backend is not the implementation target for this work. Experimental dense Qwen35 support is now implemented; see [native 27B support](DENSE_QWEN35.md). Mixtral and DeepSeek execution are not implemented.

Native short-generation and practical results are recorded in [the October 14 trial](../bench/results/2026-10-14-native-qwen35-gsq/README.md).
