def merge_intervals(intervals: list[list[int]]) -> list[list[int]]:
    """
    Merge overlapping or touching intervals.

    Args:
        intervals: A list of [start, end] intervals.

    Returns:
        A list of merged intervals sorted by start.

    Raises:
        ValueError: If input is malformed, contains non-integers, or has start > end.
    """
    if not intervals:
        return []

    # Validate input
    for interval in intervals:
        if not isinstance(interval, list) or len(interval) != 2:
            raise ValueError("Each interval must be a list of two elements.")
        start, end = interval
        # Check for booleans (bool is subclass of int, but we want strict int)
        if isinstance(start, bool) or isinstance(end, bool):
            raise ValueError("Endpoints must be integers, not booleans.")
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError("Endpoints must be integers.")
        if start > end:
            raise ValueError("Start must be less than or equal to end.")

    # Sort intervals by start time
    sorted_intervals = sorted(intervals, key=lambda x: x[0])

    merged = []
    current_start, current_end = sorted_intervals[0]

    for start, end in sorted_intervals[1:]:
        if start <= current_end:
            # Overlapping or touching intervals
            current_end = max(current_end, end)
        else:
            # Non-overlapping interval
            merged.append([current_start, current_end])
            current_start, current_end = start, end

    merged.append([current_start, current_end])

    return merged
