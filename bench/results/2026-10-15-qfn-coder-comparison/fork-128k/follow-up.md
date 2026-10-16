**Boundary-case tests:**

1. `normalize_path`: `normalize_path("a/../b")` → raises `ValueError` (correctly rejects `..`).
2. `retry_delay`: `retry_delay(0, 0, 0)` → returns `0` (all nonnegative, min(0, 0*1)=0).
3. `next_head`: `next_head((0, 0), (-1, -1), 5, 5)` → returns `(4, 4)` (wraps correctly).

**Remaining bug:** `retry_delay` does not validate that `attempt` is an integer. If `attempt` is a float (e.g., `1.5`), `2 ** 1.5` succeeds and returns a float, violating the "nonnegative integer" requirement. Fix: add `if not isinstance(attempt, int): raise ValueError(...)`.