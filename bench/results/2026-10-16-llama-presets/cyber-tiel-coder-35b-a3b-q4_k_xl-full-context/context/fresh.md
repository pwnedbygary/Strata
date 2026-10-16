```python
def normalize_path(path):
    parts = path.replace('\\', '/').split('/')
    result = []
    for part in parts:
        if part == '' or part == '.':
            continue
        if part == '..':
            raise ValueError("unexpected '..' component in path")
        result.append(part)
    return '/'.join(result)


def retry_delay(attempt, base, cap):
    if attempt < 0 or base < 0 or cap < 0:
        raise ValueError("attempt, base, and cap must all be nonnegative")
    return min(cap, base * (2 ** attempt))


def next_head(head, direction, width, height):
    if not isinstance(width, int) or not isinstance(height, int):
        raise ValueError("width and height must be integers")
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    return (head[0] + direction[0]) % width, (head[1] + direction[1]) % height


# CHECKPOINT_EARLY: 09ed174738e36a7f4c139f32
# CHECKPOINT_MIDDLE: 727e0ed9bcd370343ecb8ac3
# CHECKPOINT_LATE: 5d7f2ce515903fb0619b149f
```

Notes on judgment calls:
- `normalize_path` rejects any literal `..` component (not just when it would escape the root), per the requirement.
- `next_head` uses `%` wrapping, which maps negatives to valid indices (e.g. `-1 % width == width - 1`). If you want out-of-bounds to raise instead, that's a different contract—say so.
- `retry_delay` allows `base`/`cap` as floats; the requirement says "nonnegative numbers," so floats are accepted.