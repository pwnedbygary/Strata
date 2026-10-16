**normalize_path**
- Boundary test: `normalize_path("a/./b/../c")` → raises `ValueError` (the `..` is rejected regardless of position).
- Remaining bug: none against the stated requirement. Note it also rejects a leading `..` like `"../x"`—correct per "reject ANY `..`."

**retry_delay**
- Boundary test: `retry_delay(0, 5, 3)` → `3` (cap wins); `retry_delay(2, 5, 100)` → `20`.
- Remaining bug: none. `min(cap, base*2**attempt)` matches the spec exactly.

**next_head**
- Boundary test: `next_head((-1, height-1), (1, 0), width, height)` → `(0, height-1)` (wraps around left edge).
- Remaining bug: `isinstance(True, int)` is `True`, so `width`/`height` of `True`/`False` pass the type check. Also, `width`/`height` as floats like `10.0` pass `isinstance(..., int)`? No—`10.0` is `float`, correctly rejected. The bool leak is the only gap; add `and not isinstance(width, bool)` if you want to exclude booleans.