# Practical model comparisons

The fixed tasks and repeat commands are in [bench/practical](../bench/practical/README.md).
Run both models on the same machine, keep the output limits and prompts unchanged,
and save failed or incomplete outputs. Report objective checks separately from
manual review. The saved artifacts are the evidence, not a model-generated score.

## First runs: October 13, 2026

Ryzen 7 7800X3D, RX 9070 XT 16 GiB, 30.9 GiB RAM, CachyOS, ROCm 7.2,
NVMe/Btrfs, engine 0.1.44, the [optional hardware profile](HARDWARE_RX9070XT_32GB.md).
Temperature 0, top-p 1, seed 20261013, reasoning disabled, one request at a time.
Both models used 128K context, int8 KV, 11 GiB resident experts and 3072 MiB VRAM
reserve. These short prompts did not fill the context window.

| Task | Coder IQ1_M | Full IQ3_XXS |
| --- | --- | --- |
| Merge intervals | 470 tokens at 34.4 tokens/s; forbidden typing import. After removing only the import and replacing its annotations, 11/11 function checks passed. | 329 tokens at 12.4 tokens/s; original output passed 11/11 checks. |
| Lighthouse SVG | 4096 tokens at 45.9 tokens/s; output limit, unclosed XML and repeated zero-area paths. Partial browser render does not make it valid. | 2511 tokens at 22.9 tokens/s; complete SVG, 7/7 structural checks, successful render. |
| Snake | 6144 tokens at 37.3 tokens/s; output limit, unfinished CSS, no game or benchmark API. | 6144 tokens at 20.0 tokens/s; output limit, unfinished script and missing benchmark API. |

The reviewer inspected the Python source and rendered SVGs. IQ3's lighthouse was
recognizable, with a clear beam, storm clouds and waves, though visually simple.
The first two tasks favor IQ3 for following instructions and producing usable
artifacts; IQ1 produced tokens faster. Neither throughput nor this tiny sample
establishes general model intelligence.

Both game attempts failed the same output budget. IQ3 reached JavaScript but did
not finish; IQ1 spent its entire budget on styling. Do not count partial screenshots
as successful games. IQ1's guarded run kept at least 2.6 GiB available RAM and did
not trigger its abort threshold. For these tasks the reviewer prefers IQ3 when a
usable first response matters, and IQ1 when faster output is worth more cleanup.

These compare the pruned Coder family against the full model, not just two
quantizations of otherwise identical weights. Adaptive placement was enabled;
IQ3 had previous long-context runs while IQ1 started fresh. Timing comparisons
are illustrative single runs, not controlled speed ratios. Fixed prompts and
seeds make the protocol repeatable, not bitwise reproducible.
