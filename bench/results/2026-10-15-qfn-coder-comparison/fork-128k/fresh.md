```python
def normalize_path(path):
    normalized = path.replace('\\', '/')
    components = normalized.split('/')
    result = []
    for component in components:
        if component == '':
            continue
        if component == '.':
            continue
        if component == '..':
            raise ValueError("Path contains '..' component")
        result.append(component)
    return '/'.join(result)

def retry_delay(attempt, base, cap):
    if attempt < 0:
        raise ValueError("attempt must be nonnegative")
    if base < 0:
        raise ValueError("base must be nonnegative")
    if cap < 0:
        raise ValueError("cap must be nonnegative")
    return min(cap, base * (2 ** attempt))

def next_head(head, direction, width, height):
    if width <= 0:
        raise ValueError("width must be a positive integer")
    if height <= 0:
        raise ValueError("height must be a positive integer")
    x = (head[0] + direction[0]) % width
    y = (head[1] + direction[1]) % height
    return (x, y)
```

# CHECKPOINT_EARLY: 09ed174738e36a7f4c139f32
# CHECKPOINT_MIDDLE: 727e0ed9bcd370343ecb8ac3
# CHECKPOINT_LATE: 5d7f2ce515903fb0619b149f