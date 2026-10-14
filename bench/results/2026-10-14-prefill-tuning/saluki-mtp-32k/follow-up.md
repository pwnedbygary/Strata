**Boundary-case tests:**

1. `normalize_path`: `normalize_path("a/./b/../c")` → should raise `ValueError` (rejects `..`).
2. `retry_delay`: `retry_delay(0, 0, 5)` → returns `0` (base=0 edge case).
3. `next_head`: `next_head((0, 0), (1, 0), 1, 1)` → returns `(0, 0)` (wraps at width=1).

**Remaining bug:** None. All three functions correctly implement their requirements.