# Remaining local model profiles

Tested October 14, 2026 on the RX 9070 XT 16 GiB / Ryzen 7800X3D / 32 GB RAM profile,
with system ROCm 7.2 and the native dense development engine inside the AppImage.
Model files live in `models/`; exported per-model tokenizers live in `packs/`.

## Available selections

| API model ID | Context setting | Drafting | Short smoke result |
| --- | ---: | --- | --- |
| `swift27-iq3-xxs` | Adaptive 262,144 limit; initially 4K | Off | 34.0 tokens/s |
| `swift27-iq3-s` | Adaptive 262,144 limit; initially 4K | Off | 13.6 tokens/s |
| `swift27-iq3-xxs-mtp` | Fixed 8,192 | One MTP draft, greedy only | 50.8 tokens/s, 26/29 drafts accepted |
| `swift27-iq3-s-mtp` | Fixed 8,192 | One MTP draft, greedy only | 52.2 tokens/s, 38/41 drafts accepted |
| `qwen35-08b-q8-compat` | Fixed 4,096 | Off; reasoning off | 257.0 tokens/s, only 11 output tokens |
| `tiel-coder` | Disabled candidate | Unavailable | Expert formats / memory not supported by the bundled profile |
| `cyber-tiel` | Disabled candidate | Unavailable | Same blockers |

![Verified model selector with the active MTP profile](media/router/local-profiles.png)

Saluki and Flash profiles remain registered. `GET /v1/models` lists every registered
entry; use `available` and `status.value` to filter unavailable profiles. Disabled models
have an `unavailable_reason`, cannot replace the loaded worker and appear greyed out in
the dropdown. Each entry also reports its configured `drafting` state. Auxiliary mmproj
files are not standalone language models, and these profiles remain text-only.

The MTP entries load **the complete GGUF with an embedded MTP block**. They are not
standalone draft-only models. These 8K profiles actively load and use the head; the
adaptive 256K path currently rejects MTP. The earlier temporary `-mtp-file` IDs were
replaced by the clearer `-mtp` IDs after verification.

The small model uses an explicit, lossy Q8 compatibility conversion for unsupported
projection formats in memory; its original GGUF is untouched. All Swift weights, including
MTP projections, were accepted natively. No Q8 conversion is enabled in the final Swift profiles.
The 0.8B profile disables thinking because its direct answer otherwise appeared in the
reasoning field instead of normal content. Its very short timing is not a sustained speed claim.

## MTP comparison

The same MTP-containing files were also tested at the same **8K context, int8 KV, prefill
512, greedy, 128-token output cap**, with drafting off:

| File | MTP off | One draft | Generated tokens |
| --- | ---: | ---: | ---: |
| Swift IQ3_XXS + MTP | 35.5 tokens/s | 50.8 tokens/s | 55 |
| Swift IQ3_S + MTP | 34.3 tokens/s | 52.2 tokens/s | 79 |

The complete assistant messages, including reasoning, were identical in each on/off pair.
This is one short prompt, not full numerical reference parity or a broad speed benchmark.
The prompt requested `square(n)` returning `n*n`; all Swift profiles returned a complete
function and finished normally. Output counts include reasoning.

The adaptive 256K IQ3_S measurement is **not** the MTP-off comparator: its placement/cache
strategy differs. Configured context capacity is not a filled-window test. No near-full
8K MTP or 256K Swift speed/quality result is claimed.

## Tiel and Cyber Tiel

Both Q4_K_XL files declare `qwen35moe`, with 40 main layers and an embedded MTP layer.
They contain about **18.64 GiB of routed expert weights**. Four main-layer down projections
use Q6_K, which the bundled MoE expert build does not enable; the MTP down projection uses
Q3_K, absent from its expert kernel formats. Dense Q6_K matrix support does not imply
support in those routed-expert kernels. The MoE path currently loads the embedded MTP
block even with drafting off, so changing `--mtp 0` does not bypass the latter blocker.

The hybrid path also copies the whole expert pool into host memory. That allocation is
above the conservative adapter allowance and leaves inadequate margin within the existing
20 GiB worker scope. Their profiles are saved and listed as unavailable; no unsafe load
was attempted. Running them requires more engine work or compatible smaller artifacts,
not simply copying a Flash/Saluki configuration.

## Reproduce or update the registry

With an existing HIP base configuration and built AppImage:

```sh
.venv/bin/python tools/local_model_profiles.py \
  --models models --packs packs \
  --base-config strata-saluki27-adaptive.json \
  --registry "$HOME/.config/strata/router.json" \
  --swift-mtp --include-q8-compat
```

Existing unrelated registry entries are retained. The helper exports each file's own
tokenizer/chat template and writes profile copies into the registry's `profiles/` folder.
Known files that are absent are skipped. It does not download, move or modify GGUF weights.
`--swift-mtp` opts into the measured fixed 8K drafting profiles; without it, the MTP-containing
files use the adaptive profile with drafting off. `--include-q8-compat` explicitly adds the
small model's conversion profile. Restart the router and refresh the web page after updates.
These are measured presets for specific files/hardware, not universal GGUF autodetection.

[Raw responses and comparison](../bench/results/2026-10-14-local-profiles/README.md).


MTP profiles default to **temperature 0** in the API and web UI. The router now keeps
browser sampling edits separately for each profile and applies saved profile defaults
when switching. Choosing a nonzero temperature disables dense MTP drafting; explicit
client sampling still overrides the preset. The standalone single-model web app is unchanged.

The final native IQ3_S MTP profile, with compatibility conversion disabled, completed
another 79-token smoke response at **53.3 tokens/s**, accepting 38/41 drafts. Its original
GGUF weights, including the head, were used directly. [Final native response](../bench/results/2026-10-14-local-profiles/final-native-mtp.json).
