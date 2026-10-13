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

## Snake with a larger output budget

Both models were rerun with the unchanged prompt and a 16384-token output cap.
Each started after a model reload. The original failures were preserved.

| Model | Output tokens | Generation | Result |
| --- | ---: | ---: | --- |
| Coder IQ1_M | 16384 | 57.5 tokens/s | Hit limit in CSS; identical `.panel .ft .t .k` rule repeated 869 times; no body, script or benchmark API. |
| Full IQ3_XXS | 6467 | 19.6 tokens/s | Finished; 11/11 browser checks passed, no JavaScript errors. |

IQ3 also passed separate desktop keyboard, mobile direction-button and restart
checks. Its vacating-tail-cell collision case worked. A larger cap let this IQ3
attempt finish; it did not resolve IQ1's repetitive output. These are new runs,
not continuations, and adaptive placement can change their text.

## Source review, beyond completion

**Python: both implementations are sound for the specified list input.** They
sort before merging, avoid mutating the caller's nested lists, reject booleans
as integer endpoints, and handle touching intervals. Both use O(n log n) time
and O(n) extra storage. IQ1 checks the outer input is a list; IQ3's early
`if not intervals` also accepts falsey non-list values such as None. That is a
robustness difference outside the annotated input type. IQ3's merge loop is
shorter and its validated tuples are a clear immutable snapshot. IQ1's forbidden
typing import is a small task-compliance defect, not evidence of a bad algorithm.

**SVG: IQ3 has substantially better output quality in this run.** It has meaningful
layer IDs, reusable gradients, title/description accessibility metadata and
editable geometry. The design is clear but simple. Some rectangles are expressed
as paths, making edits more tedious than necessary. IQ1's unfinished SVG contains
23 identical zero-area paths, which add size without drawing anything. This is
redundant geometry as well as a completion failure.

**Snake: IQ3 is a usable prototype with maintainable sections.** Its IIFE confines
state, named helpers separate reset/movement/food/rendering, seeded RNG follows
the specification, snapshots copy nested coordinates, and collision checking
correctly permits entering the tail cell when it moves away. Actual keyboard,
mobile controls and restart behavior were checked. Its source still needs work:

- At a 640 by 640 viewport the centered layout puts the header 321.7 pixels above
  the page's visible top. Tall mobile layouts need top alignment or safe centering.
- Browser zoom is disabled; direction buttons lack descriptive labels, canvas has
  no accessible description, and dynamic score/status lacks a live announcement.
- Movement directly calls rendering/DOM updates, so the simulation cannot be
  tested independently of the page without a small refactor.
- requestAnimationFrame continues while paused/dead. Food placement scans the
  snake for every grid cell; acceptable for 20 by 20, but not a scalable approach.
  These are source-level efficiency concerns, not measured frame-rate problems.
- Space-key autorepeat can toggle pause repeatedly. Unused rendering values and
  the stored animation-frame ID add minor clutter. There is no explicit full-board
  win state; that would be a useful additional edge case.

IQ1's expanded Snake output never produced gameplay code, so its movement algorithm
cannot be assessed. The 869 duplicate CSS rules are a concrete quality failure;
high generation speed here mostly produced repetition. The reviewer prefers IQ3
for these frontend tasks, while treating the small Python task as roughly tied.
This review concerns these artifacts and this greedy generation profile, not every
possible prompt or sampling configuration of either model.
