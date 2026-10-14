# Remaining local model profiles

Tested October 14, 2026 on the RX 9070 XT 16 GiB / Ryzen 7800X3D / 32 GB RAM profile,
with system ROCm 7.2 and the native dense development engine inside the AppImage.
Model files live in `models/`; exported per-model tokenizers live in `packs/`.

## Measured selections

Swift MTP selections in the table below are historical measurements. They were removed
from this user's registry, including the fast 8K variants; their GGUF files were retained.
Current screenshot-enabled Saluki/Swift selections are listed in [Screenshot input](SCREENSHOT_INPUT.md).

| API model ID | Context setting | Drafting | Short smoke result |
| --- | ---: | --- | --- |
| `swift27-iq3-xxs` | Adaptive 262,144 limit; initially 4K | Off | 34.0 tokens/s |
| `swift27-iq3-s` | Adaptive 262,144 limit; initially 4K | Off | 13.6 tokens/s |
| `swift27-iq3-xxs-mtp` | Adaptive 262,144 limit; initially 4K | One MTP draft, greedy only | 47.2–47.4 tokens/s after a 4,086-token prompt; full fill pending |
| `swift27-iq3-s-mtp` | Adaptive 262,144 limit; initially 4K | One MTP draft, greedy only | Larger-context throughput not measured yet |
| `swift27-iq3-xxs-mtp-fast-8k` | Fixed 8,192 | One MTP draft, greedy only | 50.8 tokens/s, 26/29 drafts accepted |
| `swift27-iq3-s-mtp-fast-8k` | Fixed 8,192 | One MTP draft, greedy only | 52.2 tokens/s, 38/41 drafts accepted |
| `qwen35-08b-q8-compat` | Fixed 4,096 | Off; reasoning off | 257.0 tokens/s, only 11 output tokens |
| `tiel-coder` | Disabled candidate | Unavailable | Expert formats / memory not supported by the bundled profile |
| `cyber-tiel` | Disabled candidate | Unavailable | Same blockers |

![Verified model selector with the active MTP profile](media/router/local-profiles.png)

Saluki and Flash profiles remain registered. `GET /v1/models` lists every registered
entry; use `available` and `status.value` to filter unavailable profiles. Disabled models
have an `unavailable_reason`, cannot replace the loaded worker and appear greyed out in
the dropdown. Each entry also reports its configured `drafting` state. Auxiliary mmproj
files are not standalone language models. IDs without `-vision` remain text-only.

The historical MTP entries load **the complete GGUF with an embedded MTP block**. They are not
standalone draft-only models. Adaptive MTP now requires the additional opt-in
`STRATA_Q35_ADAPTIVE_MTP=1`: both main and draft KV caches grow together, and the eight
MTP matrices participate in weight eviction/restoration. Fixed 8K variants remain
available for short conversations. The earlier temporary `-mtp-file` IDs were
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
  --vision --saluki-abliterated --remove-swift-mtp --include-q8-compat
```

Existing unrelated registry entries are retained. The helper exports each file's own
tokenizer/chat template and writes profile copies into the registry's `profiles/` folder.
Known files that are absent are skipped. It does not download, move or modify GGUF weights.
`--swift-mtp` opts into drafting. Its default context remains 8K; `--mtp-context 262144`
adds adaptive MTP and retains separate `-fast-8k` profiles. Without drafting, MTP-containing
files use the adaptive profile with drafting off. `--include-q8-compat` explicitly adds the
small model's conversion profile. Restart the router and refresh the web page after updates.
These are measured presets for specific files/hardware, not universal GGUF autodetection.

The local selection now uses separate `saluki27-abliterated-vision` and
`saluki27-abliterated-mtp-vision` profiles, both with a 262,144-token adaptive limit.
`--remove-swift-mtp` removes only registry selections; it does not delete weight files.
`--saluki-abliterated` adds both Saluki image variants using the matching Saluki projector.

[Raw responses and comparison](../bench/results/2026-10-14-local-profiles/README.md).


MTP profiles default to **temperature 0** in the API and web UI. The router now keeps
browser sampling edits separately for each profile and applies saved profile defaults
when switching. Choosing a nonzero temperature disables dense MTP drafting; explicit
client sampling still overrides the preset. The standalone single-model web app is unchanged.

The final native IQ3_S MTP profile, with compatibility conversion disabled, completed
another 79-token smoke response at **53.3 tokens/s**, accepting 38/41 drafts. Its original
GGUF weights, including the head, were used directly. [Final native response](../bench/results/2026-10-14-local-profiles/final-native-mtp.json).

## Adaptive MTP storage checks

With Swift IQ3_XXS, a 4,086-token prompt plus 64 generated tokens crossed the initial
4K cache during speculative decoding. All 64 IDs and the 30/34 accepted drafts matched
fixed 16K storage. A second run first allocated and touched all 17 attention caches at
256K, evicted 380 matrices, then shrank to 4K and restored all 408 main/MTP matrices.
It produced those same IDs and draft decisions. Rates were 48.1 tokens/s fixed, 47.4
adaptive growth and 47.2 after the storage cycle. This is internal storage/speculation
validation, not external numerical parity or a completed full-context language test.

The separate near-full test uses `tools/context_fill.py`: it counts the request with the
server tokenizer, streams prefill progress, and records physical GPU free memory and
system available RAM. It asks for three exact values placed at the start, middle and
end of a 261,120-token reference. This simple retrieval probe is not a long-context coding
benchmark. Results must be recorded after generation completes.

The extreme fill was stopped at the user's request after 121,856 processed tokens,
before generation. It is not a completed 256K benchmark. [Storage checks and stopped fill](../bench/results/2026-10-14-mtp-context/README.md).
The replacement [32K/64K coding-context checks](../bench/results/2026-10-14-coding-context/README.md)
separate fresh prefill, cached follow-ups, decode rate and simple code correctness.
