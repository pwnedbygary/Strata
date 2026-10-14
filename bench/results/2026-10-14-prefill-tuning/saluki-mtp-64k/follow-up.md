**Boundary-case tests:**

1. `normalize_path`: `normalize_path("a/./b/../c")` → should raise `ValueError` (contains `..`).
2. `retry_delay`: `retry_delay(0, 0, 5)` → should return `0` (base=0, cap=5).
3. `next_head`: `next_head((0, 0), (1, 1), 1, 1)` → should return `(0, 0)` (wraps on 1×1 grid).

**Remaining bug:** None. All three functions correctly implement their requirements.