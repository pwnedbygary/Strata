# Saved model profiles and the AppImage

The opt-in router keeps one public endpoint and loads one configured Strata model at a time.
The existing `serve/server.py` single-model path is unchanged. Models keep their own engine,
tokenizer, chat template, context, GPU/cache flags and sampling defaults. Switching waits for
an active generation, including its streamed response, to finish, stops the old worker and
starts the new one. Weights must be loaded again; switching is not instantaneous. Prompt/KV
caches are lost on a switch; clients must send their conversation history again.

## This machine

Register the already-prepared profiles once:

```sh
.venv/bin/python tools/router_profile.py \
  --registry "$HOME/.config/strata/router.json" \
  --profile saluki27=strata-saluki27-adaptive.json \
  --profile flash-iq3=strata-iq3_xxs.json \
  --default saluki27 --bundle-engines
```

`--bundle-engines` copies settings into the registry's `profiles/` directory and selects
bundled executables. Model weights, packs and tokenizers stay external. This copy leaves
the source profiles alone. Each profile can have its own optional `router` block:

```json
{
  "router": {
    "display_name": "Saluki 27B — adaptive 256K",
    "description": "Text-only RX 9070 XT profile; filled 256K quality not validated",
    "max_output_tokens": 16384
  }
}
```

The optional output cap is enforced by the router. Without it, the context budget is the
only advertised output bound; actual output must fit after the tokenized input. Edit the
saved profile JSON to persist profile settings and restart the router after edits. Settings
edited through the embedded single-model UI affect that worker's temporary config; they do
not rewrite the saved profile. Register models only after preparing and validating a native
profile; the router does not add support for an unsupported model architecture.

Stop an existing standalone server, then launch:

```sh
systemctl --user stop strata-local.scope
./dist/Strata-RX9070XT-x86_64.AppImage --open
```

Open `http://127.0.0.1:8096/`, select a profile and click **Load model**. **Release memory**
stops the worker while leaving the router available. Models also load on the first API request.
The registry defaults to `$XDG_CONFIG_HOME/strata/router.json` (normally
`~/.config/strata/router.json`). Use `--registry /path/to/router.json` for another registry.

The source launcher uses original executable paths rather than bundle paths:

```sh
.venv/bin/python tools/router_profile.py --registry local-tuning/router-source.json \
  --profile saluki27=strata-saluki27-adaptive.json --profile flash-iq3=strata-iq3_xxs.json
.venv/bin/python -m serve.router --registry local-tuning/router-source.json --open
```

The same endpoint accepts OpenAI chat/completions/Responses and Anthropic messages.
The harness base URL remains **`http://127.0.0.1:8096/v1`**. Select `saluki27` or
`flash-iq3` in the request's `model` field. An omitted model uses the active profile,
or the default when none is active. Unknown model names return 404 rather than silently
using a different model. API requests do not require the web page to be open.

## Discovery for harnesses

`GET /v1/models` and `GET /models` list **all registered profiles**, without loading them.
Each entry supplies OpenAI's `id`/`object`, plus:

| Field | Meaning |
| --- | --- |
| `context_length`, `meta.n_ctx` | Configured `--max-context` token limit; null if absent/unknown |
| `max_output_tokens`, `meta.max_output_tokens` | Optional enforced output cap, bounded by known context; otherwise the context bound |
| `output_limit_policy` | Actual output also shares the context with tokenized input |
| `model_architecture` | GGUF family from config, e.g. `qwen35` or `qwen4exp` |
| `architecture.input_modalities`, `output_modalities` | Text/image input according to configured vision; text output |
| `capabilities` | Streaming, tool formatting, configured vision and image generation |
| `sampling_defaults` | Profile sampling settings; explicit request sampling overrides them |
| `fit_max_tokens` | Whether the worker clamps output to remaining context instead of rejecting an oversized request |
| `status.value` | `unloaded`, `loading` or `loaded` |

These describe configured limits and available API formats, not capability or quality
scores. A configured context limit is not a full-window benchmark. There is no portable
standard requiring every harness to consume these extra metadata fields; a harness that
only reads IDs may still need its own context setting. Absolute model paths and API keys
are not exposed by discovery.

`GET /router/status` reports loading/errors and active profile. `POST /router/load`
with `{"model":"saluki27"}` switches explicitly; `POST /router/unload` releases the worker.
The health endpoint remains reachable with no loaded model.

## Memory and access

The worker process tree runs in a systemd user scope named `strata-router-model-<pid>.scope`,
with **MemoryMax=20G**, **MemorySwapMax=0** and a **1.5 GiB available-system-RAM guard**.
The router stays alive to report load failures and allow another profile to be selected.
Only one contained router instance is allowed per user. The launcher refuses to coexist
with the old `strata-local.scope`. Stop the router with Ctrl+C or SIGTERM; it stops its worker.
The router itself is outside the model scope. These bounds cannot reserve GPU memory against
other desktop applications or account for every driver allocation.

Default binding is `127.0.0.1`; a non-loopback bind requires `--api-key` (or `STRATA_API_KEY`).
Clients send a Bearer token or `x-api-key`. The browser key field establishes an HttpOnly,
SameSite session cookie, allowing the embedded chat to use the authenticated router. A local
private worker uses a separate generated credential. Foreign browser origins and unknown
Host headers are rejected; cross-origin harness browser apps are not supported yet.
POST request bodies are limited to 32 MiB and require Content-Length. At most eight POST
requests are admitted concurrently; additional requests receive 429, while model discovery
remains available. For a wildcard bind, name the IP/hostname clients use with
`--allowed-host` (for example `--host 0.0.0.0 --allowed-host 192.168.1.50 --api-key ...`).

## Building the executable and AppImage

Build on Linux x86_64 with the HIP development engine and installed Flash engine present.
The first package uses system ROCm; it does **not** bundle ROCm or the GPU driver. This local
build is tested on CachyOS/ROCm 7.2/gfx1201 and does not establish compatibility with older
Linux distributions, other GPUs, Windows or other ROCm versions.

```sh
.venv/bin/python -m pip install -r packaging/requirements-build.txt
.venv/bin/python tools/build_appimage.py --appimagetool /path/to/appimagetool-x86_64.AppImage
```

Get appimagetool from [the official project](https://github.com/AppImage/appimagetool/releases).
The build creates `dist/strata-router/strata-router` (standalone executable with its adjacent
runtime files) and `dist/Strata-RX9070XT-x86_64.AppImage`. Python, the web app, both engine
executables, the expert-placement profile and HIP tuning tables are bundled. GGUFs, expert
packs, tokenizers, user configurations and logs are not bundled. The source repository is
not needed to run the prepared bundled profiles, but their external model paths must exist.

AppImages need executable permission. If FUSE is unavailable, use:

```sh
APPIMAGE_EXTRACT_AND_RUN=1 ./dist/Strata-RX9070XT-x86_64.AppImage --open
```

See [AppImage execution](https://docs.appimage.org/user-guide/run-appimages.html) and
[PyInstaller runtime paths](https://pyinstaller.org/en/stable/runtime-information.html).

## Validation

`python -m unittest serve.test_router` tests discovery, metadata, real HTTP routing through
mock workers, streaming, safe serialization, release/reload, load failure recovery, Host/
Origin checks and browser/API authentication. The embedded chat's relative assets and health
paths are checked. Live hardware results and the rendered router screenshot are recorded
separately; neither mock tests nor packaging imply full-context model validation.


On October 14, 2026, the AppImage loaded the real Saluki adaptive profile on the documented
RX 9070 XT system and served a 68-input/64-output request at **33.0 decode tokens/s**.
That request reached its 64-token cap; it was a transport/throughput smoke test, not a
finished coding-quality benchmark. The initial build was about **46.4 MiB**. Direct FUSE
execution and extract-and-run both reached the launcher. Seven router integration tests and
nine existing single-model lifecycle regression tests passed. The embedded chat rendered
with the Outfit font, working styles and no page errors in a fresh browser against the real packaged Saluki
worker. After updating paths for the moved model directory, the same packaged router switched
to Flash IQ3_XXS and completed a 68-input/73-output request at 9.2 decode tokens/s (cold).
Saluki completed its 68-input/77-output request at 33.5 tokens/s. These short smoke tests
confirm both model paths and switching; they do not replace the practical benchmarks. This is an experimental package, not a universally
portable release.

[Raw AppImage smoke-test responses and discovery](../bench/results/2026-10-14-router-appimage/README.md).

Release/reload and SSE streaming also passed on the real Saluki profile, ending with `[DONE]`.
