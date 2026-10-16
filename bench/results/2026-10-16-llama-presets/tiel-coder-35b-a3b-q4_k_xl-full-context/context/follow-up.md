**normalize_path**
- Boundary test: `normalize_path('a/./b/../c')` → raises `ValueError` (the `..` is rejected even though it would resolve cleanly). This matches the requirement "reject ANY '..' component."
- No remaining bug.

**retry_delay**
- Boundary test: `retry_delay(0, 0, 5)` → `0` (base 0 yields 0 regardless of cap); `retry_delay(10, 1, 5)` → `5` (cap wins). Both correct.
- No remaining bug.

**next_head**
- Boundary test: `next_head((0, 0), (-1, 0), 5, 5)` → `(4, 0)` (wraps negative). Correct.
- Remaining bug: `isinstance(True, int)` is `True`, so passing `width=True`/`height=True` silently passes validation (treated as 1). Also, `width`/`height` given as `float` (e.g. `5.0`) are rejected even though they're positive integers numerically. If strict int typing matters, guard against bool; otherwise this is acceptable.