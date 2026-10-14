```python
def normalize_path(path):
    parts = path.replace('\\', '/').split('/')
    result = []
    for part in parts:
        if part == '':
            continue
        if part == '.':
            continue
        if part == '..':
            raise ValueError("path contains '..' component")
        result.append(part)
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
    if not isinstance(width, int) or width <= 0:
        raise ValueError("width must be a positive integer")
    if not isinstance(height, int) or height <= 0:
        raise ValueError("height must be a positive integer")
    new_x = (head[0] + direction[0]) % width
    new_y = (head[1] + direction[1]) % height
    return (new_x, new_y)
```