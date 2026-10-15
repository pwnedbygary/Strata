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
        raise ValueError("attempt must be a nonnegative integer")
    if base < 0:
        raise ValueError("base must be a nonnegative number")
    if cap < 0:
        raise ValueError("cap must be a nonnegative number")
    return min(cap, base * (2 ** attempt))


def next_head(head, direction, width, height):
    if not isinstance(width, int) or width <= 0:
        raise ValueError("width must be a positive integer")
    if not isinstance(height, int) or height <= 0:
        raise ValueError("height must be a positive integer")
    x = (head[0] + direction[0]) % width
    y = (head[1] + direction[1]) % height
    return (x, y)
```