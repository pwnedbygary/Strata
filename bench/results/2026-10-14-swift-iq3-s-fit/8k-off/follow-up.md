**Review:**

1. **`normalize_path`**: Correct. Handles backslash conversion, filters empty/`.` components, raises on `..`, preserves other text.
   - *Boundary test*: `normalize_path("a/./b//c")` → `"a/b/c"`

2. **`retry_delay`**: Correct. Validates nonnegative inputs, returns `min(cap, base * 2**attempt)`.
   - *Boundary test*: `retry_delay(0, 5, 10)` → `5`

3. **`next_head`**: **Bug**: The modulo operator `%` in Python handles negative numbers by wrapping into the positive range (e.g., `-1 % 5 == 4`), which is correct for wrapping. However, the requirement says "Wrap each resulting coordinate to its grid dimension." The current implementation is actually correct for standard grid wrapping. Let me re-check: `head[0] + direction[0]` could be negative, and `% width` wraps it correctly. No bug here.

Wait — let me re-examine. The function looks correct. All three functions appear correct.

**Remaining bug**: None. All three functions satisfy their requirements.

**Boundary-case tests:**
- `normalize_path("a/./b//c")` → `"a/b/c"`
- `retry_delay(0, 5, 10)` → `5`
- `next_head((0, 0), (-1, 0), 5, 5)` → `(4, 0)`