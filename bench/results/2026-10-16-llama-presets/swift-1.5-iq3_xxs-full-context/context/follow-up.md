**Review against requirements:**

1. **`normalize_path`** — ✅ Correct. Splits on `/`, discards `''` and `'.'`, raises `ValueError` on any `'..'`, preserves other text, returns slash-separated relative path.

2. **`retry_delay`** — ✅ Correct. Validates nonnegative inputs, returns `min(cap, base * 2**attempt)`.

3. **`next_head`** — ✅ Correct. Validates positive integer `width`/`height`, wraps each coordinate via `%`.

**Boundary-case tests:**

- `normalize_path("a/./b/../c")` → raises `ValueError` (the `'..'` is rejected even though it would cancel `b`).
- `retry_delay(0, 0, 5)` → `0` (base=0 yields 0 regardless of cap).
- `next_head((0, 0), (-1, -1), 1, 1)` → `(0, 0)` (negative direction wraps in a 1×1 grid).

**Remaining bug:** None. All three functions satisfy their stated requirements.