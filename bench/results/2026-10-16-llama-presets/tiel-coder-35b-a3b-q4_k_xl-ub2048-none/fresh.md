```python
def normalize_path(path):
    parts = path.replace('\\', '/').split('/')
    out = []
    for part in parts:
        if part == '' or part == '.':
            continue
        if part == '..':
            raise ValueError("unsupported '..' component in path")
        out.append(part)
    return '/'.join(out)


def retry_delay(attempt, base, cap):
    if attempt < 0 or base < 0 or cap < 0:
        raise ValueError("attempt, base, and cap must be nonnegative")
    return min(cap, base * (2 ** attempt))


def next_head(head, direction, width, height):
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive integers")
    return (head[0] + direction[0]) % width, (head[1] + direction[1]) % height


# CHECKPOINT_EARLY: 09ed174738e36a7f4c139f32
# CHECKPOINT_MIDDLE: 727e0ed9bcd370343ecb8ac3
# CHECKPOINT_LATE: 5d7f2ce515903fb0619b149f
```

Notes: `normalize_path` returns `''` for an all-empty/`.` input (relative slash-separated path with no components). `next_head` uses modulo wrapping; negative coordinates still wrap correctly since Python's `%` is nonnegative for positive modulus.