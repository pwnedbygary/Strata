```python
def normalize_path(path):
    parts = path.replace('\\', '/').split('/')
    result = []
    for part in parts:
        if part == '' or part == '.':
            continue
        if part == '..':
            raise ValueError("Path contains '..' component")
        result.append(part)
    return '/'.join(result)

def bounded(value, low, high):
    return max(low, min(value, high))

def retry_delay(attempt, base, cap):
    if attempt < 0:
        raise ValueError("attempt must be nonnegative")
    if base < 0:
        raise ValueError("base must be nonnegative")
    if cap < 0:
        raise ValueError("cap must be nonnegative")
    return min(cap, base * (2 ** attempt))

def next_head(head, direction, width, height):
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise ValueError("width and height must be positive integers")
    x = (head[0] + direction[0]) % width
    y = (head[1] + direction[1]) % height
    return (x, y)
```