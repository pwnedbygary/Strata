# Native C++ server and AppImage

This opt-in Linux path imports the MIT-licensed UnbiasedStrata frontend at
`b124b59ce48e4d53abd14d1fd08979350fc27358` and embeds this fork's newer engine,
including its dense Qwen35 path. Attribution is in `frontend/NOTICE.md` and
`frontend/LICENSE`. Python remains available for setup, development and the legacy
server, but is not bundled or invoked by the native AppImage runtime.

## Engine selection

The unified package includes the native Strata engine and local llama.cpp executables.
Automatic routing reads GGUF metadata without loading weights: a `qwen4exp` MoE
with a matching prepared expert pack uses Strata's VRAM/RAM/SSD tiers. Dense and
unverified MoE models use llama.cpp. A measured native preference may be bound to
an exact model path and file size, as with this machine's Swift IQ3_S profiles;
changing that model removes the preference. This is a conservative compatibility
rule, not support for every MoE in the tiered engine.

The sidebar selects Automatic, llama.cpp or Strata, then Vulkan or ROCm when
llama.cpp is selected. Only the dedicated Vulkan and ROCm builds are packaged. Backend selection is saved per profile and
applies on Load. Switching engines releases the previous worker first. Both
engines share the memory scope and per-user model lock. External harnesses still
use the same `/v1` address, with routing details included in `/v1/models`.

llama.cpp uses Flash Attention, one slot, Q8 KV and CPU vision by default. Tune
exposes its actual microbatch, fit margin, KV precision and draft count. Native
Strata controls remain available on the native path. Configured context is a
ceiling; longer contexts and backend combinations require separate validation.
Live llama.cpp rates are estimates from observed progress until final timings
arrive; completed rates use its reported timings. KV payload and expert-tier
counters are unavailable when the selected backend does not provide them.

## Run

```sh
./dist/Strata-Unified-RX9070XT-x86_64.AppImage
# Or select another local registry / port:
./dist/Strata-Unified-RX9070XT-x86_64.AppImage \
  --registry "$HOME/.config/strata/router.json" --port 8096
```

No arguments opens the local web UI. Models load on demand from the existing
registry. `/v1/models` lists every profile with configured context, output budget,
modalities and tool/streaming capabilities. A profile's configured ceiling is not
a claim that a completely filled window has passed validation. The UI supports
streaming text, inline screenshots, model switching, stopping and memory release.

One model worker is resident at a time. Direct worker invocation outside a finite
cgroup memory budget is refused; router mode creates the bounded scope automatically. Both worker types take a per-user lock;
a second model worker fails before loading weights. Model switches drain the
current request before stopping its scope and loading the next. Workers use
systemd user scopes with 20 GiB memory and zero scope swap by default; the profile
can specify `router.memory_max_gib`. Startup caps that hard budget against currently
available RAM after keeping the system margin. The scope leaves `MemoryHigh` unset:
it counts the mapped expert-file cache and can force repeated SSD reads before the
hard limit is reached. The hard `MemoryMax`, zero scope swap and live system-memory
floor remain active. Requests arriving during inference receive HTTP 429 instead of building
an unbounded generation queue. Physical-system floors default to 3 GiB
available RAM and 512 MiB free dedicated VRAM. The monitor stops the worker if
those floors are crossed. Admission uses an additional 1 GiB host / 256 MiB GPU
margin. Active generation checks those softer limits at progress/token boundaries
and sends STOP, drains the response, and returns an explicit error. The external
llama.cpp supervisor checks the same soft floors every 200 ms and terminates its
backend if headroom is lost. Cancellation disconnects the upstream request;
backend process shutdown remains available through Release memory. HTTP thread
and queue counts are bounded. The engine child dies if its supervising worker
crashes. Systemd remains the final process-memory boundary; it is not a substitute
for preflight and adaptive weight offload. Strata cannot reserve memory against
all other applications or guarantee protection from driver/hardware failures. A failed worker is not blindly restarted during a
request. These limits do not establish hardware/undervolt stability.

The runtime binds loopback only. `--api-key KEY` or `STRATA_API_KEY` protects the
API; foreign browser origins are rejected. It never downloads a model, tokenizer,
projector, remote screenshot or web asset. Model/tokenizer/chat templates and
projectors come from existing local GGUF files. The only outgoing HTTP connection
in this frontend is the router's loopback connection to its own worker. Local
hardware diagnostics and terminal logs are not remote reporting.

## Monitor, Tune and Settings

The local UI has Chat, Monitor, Tune, Settings and About pages. Monitor samples
local counters every two seconds: prefill progress and average rate, decode rate,
context position, KV capacity/payload, adaptive weight placement, MTP acceptance,
physical GPU memory, system-available RAM and worker budget accounting. Rate graphs
show this browser session's recent observations; an idle chart is not a benchmark.
Flash-Next's idle expert census is explicitly marked stale during generation.
GPU memory includes the whole desktop. Cgroup memory includes charged file cache;
it is not process RSS and does not include dedicated VRAM. Missing counters are
shown as unavailable. A shared model lock held by another runner is shown as
GPU in use; native token counters do not describe that external runner. Cancelled prefill rates use processed tokens, not the full
requested prompt.

Tune has per-profile sliders and numeric inputs. Dense profiles expose context,
prefill chunk, embedded MTP depth, attention scratch, memory reserves and optional
vision threads. Flash-Next exposes its resident RAM budget, CPU workers, GPU KV
residency, speculation window and KV precision. Int8 remains the baseline. Q4 and
hybrid KV require explicit selection; approximate tail skipping is labeled as
changing answers. A larger setting is not a claim of higher throughput.

llama.cpp Tune also offers an Automatic fitting switch and a MoE-only slider
for explicit CPU expert layers. Fit must be off for manual expert placement;
turning Fit on clears that override. The fit-target slider steps through 1024,
2048, 4096 and 8192 MiB, with an editable custom value. Manual mode keeps dense
layers on the GPU and performs conservative weight/KV/workspace and RAM/GTT
admission checks. Manual CPU experts use the measured `load-mode=none` path;
mmap can cause repeated reclaim with CPU tensor overrides. Manual estimates
refuse split GGUFs rather than counting only the first shard. These estimates
can refuse a configuration that another runner
can load; they do not replace filled-window validation. The llama.cpp supervisor
also stops on critically low GTT headroom. Native Strata's expert-tier controls
are separate. llama.cpp MoE MTP is currently blocked after a Vulkan device-loss
trial; native Strata MTP and dense llama.cpp settings remain separate.

Settings holds local GGUF/projector/pack/shard/head paths and the screenshot toggle.
Browse opens a local file/folder picker; paths remain editable. Selection only
sets the path and does not upload or copy weights. About keeps linked credits;
optional profile diagnostics live under Tune.
Absolute paths must exist; GGUF headers and directory structure are checked before
saving. Compatibility is checked by the loader. Browser monitoring and auto-scroll
preferences stay in browser local storage. API keys are not stored there.

Overrides are private, atomically written files beside the registry: for
`~/.config/strata/router.json`, the file is
`~/.config/strata/native-tuning-router.json`. Original profile JSON files are never
rewritten. **Save overrides** preserves the active worker; **Save & reload model**
restarts it and clears engine KV. `/v1/models` reports the active context while
saved changes wait for reload, with a separate `pending_configuration` object.
Reset restores the original profile plus this native executable's memory defaults.
Invalid saved overrides block loading rather than silently loading another config.

The native RX 9070 XT path enables missing dense head-reuse/buffer-loan settings
and a 2048 MiB physical reserve when a profile did not specify them. On 12–20 GiB
HIP cards, prepared Flash-Next profiles start with at least a 4096 MiB VRAM reserve;
the source profile is unchanged and explicit tuning overrides remain possible.
The 3072 MiB Flash startup trial crossed the 512 MiB guard on this desktop;
4096 MiB loaded and served a short compatibility request. This is a safety setting,
not a measured throughput gain. Known resident expert budgets that exceed the
bounded worker allowance are refused before launching the engine.

`POST /router/cancel` asks the worker to stop without waiting for the generation
lock. Dense native prefill checks STOP between chunks, resets partial state and
shrinks KV. A real 130K-input cancellation/recovery test completed in about 4.9 s,
including a successful subsequent short request. The normal engine protocol and
computation remain unchanged when `STRATA_NATIVE_MONITOR` is unset; the native
frontend enables this opt-in diagnostics/control path.

## APIs

- OpenAI `/v1/chat/completions`: streaming/nonstreaming text, reasoning, function
  tools and inline `data:image/...;base64,...` screenshot inputs.
- Anthropic `/v1/messages` and `/v1/messages/count_tokens`: native translation of
  text, tool history, inline images, reasoning controls and streaming blocks.
- Stateless `/v1/responses`: client-supplied input history, function calls/results,
  streaming events, and reasoning replay with the existing `strata.r1:` encoding.
- `/router/load`, `/router/unload`, `/router/cancel`, `/router/status`,
  GET/POST `/router/tuning`, local file listing `/router/files`, `/health`, `/v1/models`,
  `/v1/status` and basic `/metrics` diagnostics.

Responses storage/`previous_response_id`, hosted web-search/code tools, image
*generation*, internal MCP hosting, parallel model workers, arbitrary remote image
URLs, non-loopback binding and the legacy Prometheus/slot/session APIs are not
implemented on the native path. Unsupported requests must fail explicitly rather
than silently invoke an online service. External harnesses continue to execute
client-side tools themselves. This is not a promise of complete OpenAI/Anthropic
API coverage. The legacy server remains available for workflows that need its
additional endpoints.

QFN retains its VRAM/RAM/SSD expert tiers. Native direct CLI startup uses
`--ple-io direct`, avoiding UnbiasedStrata's RAM-loaded 26.8 GiB table default.
Existing profile engine args and opt-in tuning environment are retained. MTP is
optional, not forced for every model. The default path of the existing engine and
legacy Python server is unchanged.

## Build from local dependencies

Use an already present compatible llama.cpp checkout (the tested pin is
`3cf03257f219afbe7334045ff7c6a06ac68c627d`). The native option refuses an empty
`STRATA_GGML_DIR` rather than fetching source. Its tool-parser adaptation is made
in a build-tree copy, leaving the dependency checkout unchanged.

```sh
cmake -S . -B build-hip -DSTRATA_ENABLE_CUDA=OFF -DSTRATA_ENABLE_HIP=ON \
  -DSTRATA_NATIVE_EXPERTS=ON -DSTRATA_NATIVE_SERVER=ON \
  -DSTRATA_GGML_DIR="$PWD/third_party/llama.cpp" \
  -DCMAKE_HIP_ARCHITECTURES=gfx1201 -DCMAKE_BUILD_TYPE=Release
cmake --build build-hip --target strata-native -j 3
python tools/build_native_appimage.py --appimagetool /path/to/local/appimagetool \
  --runtime-file /path/to/local/runtime-x86_64 \
  --rocm-build-dir /path/to/rocm-only-llama-build \
  --vulkan-binary /path/to/tested/vulkan/llama \
  --output dist/Strata-Unified-RX9070XT-x86_64.AppImage
```

Build the external llama executables from the same pinned source revision when
comparing backend builds. The tested external checkout is
`a2878d30df0130dde503a7d9ba30d3d21bd71b9f`; enable `LLAMA_BUILD_APP`,
`LLAMA_BUILD_SERVER` and `LLAMA_BUILD_COMMON`. Set `GGML_HIP=ON`,
`GGML_VULKAN=OFF`, and `AMDGPU_TARGETS=gfx1201` for ROCm-only, or reverse
HIP/Vulkan for Vulkan-only. Combined builds were compared separately and are not included in the AppImage. These are separate
from the native engine's llama dependency pin above. Packaging reads existing
build directories and never downloads dependencies.

The package script uses Python at build time only. It includes native code,
licenses, expert-ranking data and tuning tables, with no Python interpreter,
JavaScript CDN, model weights or automatic updater. Compatible host ROCm and Linux
drivers remain required. Windows EXE packaging is deferred. CUDA/SYCL and other
GPUs have not been validated for this native frontend.

## Validation on this machine

Six native CPU tests, the real GGUF chat-template/tool-parser test, HTTP refusal /
save-merge-reset / auth tests, browser desktop/mobile checks, real worker reload
and pending-settings tests, screenshot enable/disable, and full IQ3_XXS MoE
compatibility were checked. Synthetic refusal tests do not exhaust system memory.
Native dense 8K/128K measurements and their failed headroom attempts are archived
in [the comparison record](../bench/results/2026-10-16-native-dense-comparison/README.md).
CUDA/SYCL and other machines were not tested here.

Per-profile thinking-mode sampling defaults are exposed by model discovery and
fill omitted API values. Explicit client values win. Chat starts with reasoning
enabled and a blank temperature override. See [sampling recommendations and
precedence](SAMPLING.md).

Coding harnesses with parallel subagents can opt into `"queue_requests": true`
in the router registry. This installation enables it: one request generates,
up to four wait, and SSE keep-alives avoid routine busy-retry collisions. Payload
and wait bounds remain enforced. See [request queue behavior and limits](REQUEST_QUEUE.md).
