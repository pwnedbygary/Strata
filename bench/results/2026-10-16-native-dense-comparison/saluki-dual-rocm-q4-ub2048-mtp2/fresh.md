```python
def normalize_path(path):
    parts = path.replace('\\', '/').split('/')
    for part in parts:
        if part == '..':
            raise ValueError("path contains '..' component")
    cleaned = [part for part in parts if part not in ('', '.')]
    return '/'.join(cleaned)

def retry_delay(attempt, base, cap):
    if attempt < 0 or base < 0 or cap < 0:
        raise ValueError("attempt, base, and cap must be nonnegative")
    return min(cap, base * (2 ** attempt))

def next_head(head, direction, width, height):
    if not isinstance(width, int) or width <= 0:
        raise ValueError("width must be a positive integer")
    if not isinstance(height, int) or height <= 0:
        raise ValueError("height must be a positive integer")
    return ((head[0] + direction[0]) % width, (head[1] + direction[1]) % height)

# CHECKPOINT_EARLY: 09ed174738e36a7f4c139f32
# CHECKPOINT_MIDDLE: 727e0ed9bcd370343ecb8ac3
# CHECKPOINT_LATE: 5d7f2ce515903fb0619b149f
```