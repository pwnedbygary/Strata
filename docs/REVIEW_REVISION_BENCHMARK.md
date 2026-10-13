# Review-driven code revisions

This experiment measures a practical workflow: generate code, review it independently,
give the model the source plus that review, then independently review the revision.
Completion and a model's assertion that it fixed something are not review evidence.

The original source and results stay separate. The revision runner saves the source,
requirements, review, exact prompt, revised artifact, response, text hashes, token counts,
timings and basic checks. It never edits the original source. Use an empty output folder.

For the IQ3 Snake game produced by the expanded-budget run:

```sh
PLAYWRIGHT_BROWSERS_PATH="$PWD/.benchmark-tools/browsers" \
  .venv/bin/python tools/benchmark_guarded.py --output revision-memory.json -- \
  .venv/bin/python tools/benchmark_revision.py \
  --source /path/to/original-snake.html \
  --requirements bench/practical/snake.txt \
  --review bench/practical/snake_review.md --case snake \
  --output-dir benchmark-results/snake-revision

PLAYWRIGHT_BROWSERS_PATH="$PWD/.benchmark-tools/browsers" \
  node tools/benchmark_snake_revision.mjs benchmark-results/snake-revision/revised.html
```

Install the optional browser dependencies as described in
[the practical suite](../bench/practical/README.md). The browser uses a fresh context
and blocks external requests. The added checks target small-screen layout, browser
zoom, accessible controls, idle/pause scheduling, pause-key autorepeat, engine isolation,
copied state and a full-board win. The latter drives a Hamiltonian cycle through the
board, growing from three cells to 400 without crossing occupied body cells.

The review includes an explicit testability request: expose `window.createSnakeGame(seed)`
with reset/step/state methods independent of DOM and timing. The original window.bench
API and seeded food rules must remain intact. These added checks supplement the original
11 gameplay checks; source inspection still checks maintainability and whether behavior
regressed. A passing test does not prove the absence of all bugs.

Use the same runner with `--case merge_intervals` or `--case lighthouse_svg` for those
artifact types, supplying the source and an actual review of that source. Review findings
should be checked for applicability rather than copied blindly to unrelated generated code.
Record each iteration separately and preserve failed attempts. Temperature zero and a
fixed seed keep the request protocol consistent, but adaptive engine placement can change
outputs between runs.

For a focused subsequent review, add `--edit-json --max-tokens 4096`. The model
returns literal old/new edits, each of which must match exactly once. Missing,
ambiguous or unchanged anchors are rejected, with the model response retained.
The edits are applied to a separate artifact, then that artifact is checked and
reviewed. This avoids spending tokens regenerating unrelated styling and preserves
each review iteration. It does not exempt small patches from regression checks.

The helper tests run without a model or browser:

```sh
python3 -m unittest tools.test_hardware_profile tools.test_practical_checks tools.test_benchmark_revision
```

## Measured IQ3 experiment, October 13, 2026

The same RX 9070 XT / 30.9 GiB RAM machine and 0.1.44 profile documented in
[the hardware guide](HARDWARE_RX9070XT_32GB.md), temperature 0 and seed 20261013:

| Iteration | Input tokens | Output tokens | Generation | Whole request | Independent result |
| --- | ---: | ---: | ---: | ---: | --- |
| Full revision | 7482 | 7083 | 14.2 tokens/s | 523.6 s | Engine/layout improved, UI failed integration review. |
| Focused patch | 8115 | 2694 | 17.0 tokens/s | 179.3 s | Nine anchored edits; 11 core and 20 review-specific checks passed. |

The first revision isolated the engine, sped up food occupancy lookup, added a
full-board win and fixed the three small-screen layouts. But it omitted elapsed
time from snapshots while the UI still read it, causing a boot exception; it also
tried to mutate copied pause state. The added live announcement region was empty.
These were caught by independent source and browser review, not by the model.

The second review supplied those concrete integration findings. The model returned
nine literal edits affecting 48 added and 11 removed lines, rather than another
full-file rewrite. The patched game booted without errors, kept the original seeded
movement/growth rules, passed keyboard/mobile controls, stopped idle/pause loops,
provided labels/zoom/reduced motion, and announced meaningful state changes without
announcing unchanged ticks. Separate engine instances and copied snapshots worked.
A Hamiltonian-cycle test reached a 400-cell win after 39671 moves. Both guarded
model requests completed without an abort; available host RAM stayed above 2.66 GiB.

The second artifact is a working prototype, with minor follow-ups still identified:
the new factory omits food initialization when no seed is supplied (the UI supplies
one), one pending animation callback runs after death before stopping, and spoken
announcements use internal words such as "dead" rather than "Game Over". The unused
engine elapsed field also remains. Those findings were retained, not silently repaired.

This single example supports review-assisted iteration, not trusting a revision on
first submission. The first pass made useful changes and introduced regressions;
the focused follow-up fixed the major integration defects. Existing originals, both
model responses, both reviews and the failing test evidence were preserved locally.
