**Boundary-case tests:**

1. **normalize_path**: `normalize_path("a/../b")` → raises `ValueError` (correctly rejects `..`).
2. **retry_delay**: `retry_delay(0, 0, 0)` → returns `0` (correctly handles zero base/cap).
3. **next_head**: `next_head((0, 0), (-1, -1), 1, 1)` → returns `(0, 0)` (correctly wraps negative offsets).

**Remaining bug:** None. All three functions satisfy their stated requirements.