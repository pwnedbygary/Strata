def merge_intervals(intervals: list[list[int]]) -> list[list[int]]:
    """Merge overlapping or touching intervals.

    Args:
        intervals: A list of two-element lists [start, end] with integer endpoints.

    Returns:
        A new list of merged, sorted intervals as two-element lists.

    Raises:
        ValueError: If an interval is malformed, has non-integer endpoints,
            or start > end.
    """
    if not intervals:
        return []

    validated: list[tuple[int, int]] = []
    for interval in intervals:
        if not isinstance(interval, list) or len(interval) != 2:
            raise ValueError("Each interval must be a list of exactly two elements")
        start, end = interval
        if isinstance(start, bool) or isinstance(end, bool):
            raise ValueError("Endpoints must be integers, not booleans")
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError("Endpoints must be integers")
        if start > end:
            raise ValueError("start must be <= end")
        validated.append((start, end))

    validated.sort(key=lambda x: x[0])

    merged: list[list[int]] = []
    for start, end in validated:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    return merged
