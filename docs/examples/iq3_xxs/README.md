# IQ3_XXS examples and measurement evidence

Captured October 13, 2026 on the RX 9070 XT / 30.9 GiB RAM system documented in
[the profile guide](../../HARDWARE_RX9070XT_32GB.md), Strata engine 0.1.44.

- [Reviewed Snake game](snake-reviewed.html): model-authored full revision, then nine
  model-authored literal edits from a second independent review. No manual repair.
- [Lighthouse SVG](lighthouse.svg): original generated vector artwork.
- [Interval-merging Python](merge_intervals.py): original generated function.
- [Measurements](measurements.json): selected timing, token, hash and check fields.
- [Engine excerpts](engine-excerpts.log): selected actual startup and timing lines.

Screenshots in `docs/media/rx9070xt-32gb/` are real browser captures of these artifacts,
not mockups. Local paths, API keys, raw conversations and memory-sampling logs are not
included in the exported measurements. Model weights are not included.

The examples preserve the measured outputs, including remaining issues. The game
factory should be passed an explicit seed; one pending callback can execute after
death; spoken status strings could be friendlier. The Python function assumes a
list input. Results demonstrate these tasks and iterations, not general intelligence
or a guarantee that future responses will be correct. See [the independent review
experiment](../../REVIEW_REVISION_BENCHMARK.md) for failures and limitations.
