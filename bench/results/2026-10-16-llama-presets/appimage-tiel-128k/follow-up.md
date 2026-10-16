**normalize_path**
- Boundary test: `normalize_path('a/./b/../c')` → raises `ValueError` (the `..` is rejected even though it would resolve cleanly).
- Bug: none against the stated requirement. Rejecting any `..` is what was asked. Note this means `normalize_path('..')` and `normalize_path('a/../b')` both raise, which is intentional per spec.

**retry_delay**
- Boundary test: `retry_delay(0, 0, 5)` → `0` (base 0 caps at 0); `retry_delay(10, 1, 5)` → `5` (cap hit).
- Bug: none.

**next_head**
- Boundary test: `next_head((0, 0), (-1, 0), 5, 5)` → `(4, 0)` (wraps negative).
- Bug: none against the stated requirement. `%` wraps negatives toward zero-side, so `-1 % 5 == 4`. If you intended wrap toward the high end differently (e.g. `-1` should map to `width-1`), this matches; if you wanted truncation instead of wrap, that's a spec mismatch, not a code bug.