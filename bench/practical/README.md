# Practical capability comparisons

These fixed prompts ask for a playable Snake game, a Python interval-merging function,
and editable SVG artwork. Run one model at a time with the same settings and output
limits. The report saves prompt hashes, outputs, token counts, timings and objective
checks. A fixed seed and temperature zero do not guarantee identical outputs across
hardware or adaptive engine runs.

```sh
.venv/bin/python tools/benchmark_practical.py --output-dir benchmark-results/iq1
# Switch the running server to IQ3, then:
.venv/bin/python tools/benchmark_practical.py --output-dir benchmark-results/iq3
```

The configuration helper also exposes the same runner as
`tools/hardware_profile.py benchmark --output-dir benchmark-results/current`.

Use `--repeats 3` for repeated measurements. Use separate output directories so earlier
artifacts are preserved. Python checks accept a restricted pure-function subset; a
rejection can mean unsupported syntax, rather than a wrong algorithm. Review the saved
source too. SVG checks verify structure and specified constraints, not artistic quality.

To give both games more output room, rerun each model with
`--cases snake --max-tokens 16384`. Reports record the overridden limit. Keep these
expanded-budget results separate from the original 6144-token attempts.

The [review-driven revision workflow](../../docs/REVIEW_REVISION_BENCHMARK.md) tests
how the model responds to independent review feedback, while preserving each source
version and checking for regressions.

Optional browser checks and screenshots require a local Playwright installation:

```sh
npm install --prefix .benchmark-tools playwright
PLAYWRIGHT_BROWSERS_PATH="$PWD/.benchmark-tools/browsers" .benchmark-tools/node_modules/.bin/playwright install chromium
PLAYWRIGHT_BROWSERS_PATH="$PWD/.benchmark-tools/browsers" .venv/bin/python tools/benchmark_practical.py --browser-checks --output-dir benchmark-results/iq3-browser
```

The browser uses a fresh context and blocks external requests. Review games for working
keyboard/touch controls, visible score and restart behavior. Review SVGs for a recognizable
lighthouse, readable composition and editable layers. Record these observations separately
from automatic checks. An incomplete output or failed check remains a result; do not silently
retry only the weaker model. Compare generation speed alongside correctness and usability.

For comparisons with less adaptive variation, create separate configs with
`tools/hardware_profile.py apply --config CONFIG --repeatable`. This disables adaptive
swaps, PCIe sharing, prefix reuse and route-tail skipping and can be slower. Use the same
mode for both models; it is not a promise of bitwise reproducibility.
