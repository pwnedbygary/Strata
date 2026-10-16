from typing import List

def merge_intervals(intervals: List[List[int]]) -> List[List[int]]:
    """Merge overlapping or touching intervals.

    Args:
        intervals: A list of two-element lists [start, end] with integer endpoints.

    Returns:
        A new list of merged intervals sorted by start.

    Raises:
        ValueError: If input is malformed, contains non-integer endpoints (including booleans),
                    or has start > end.
    """
    if not isinstance(intervals, list):
        raise ValueError("Input must be a list")

    # Validate and copy intervals to avoid mutating input
    validated: List[List[int]] = []
    for item in intervals:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("Each interval must be a list of exactly two elements")
        start, end = item[0], item[1]
        # Reject booleans (bool is subclass of int in Python)
        if isinstance(start, bool) or isinstance(end, bool):
            raise ValueError("Endpoints must be integers, not booleans")
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError("Endpoints must be integers")
        if start > end:
            raise ValueError("start must not be greater than end")
        validated.append([start, end])

    if not validated:
        return []

    # Sort by start, then by end
    validated.sort(key=lambda x: (x[0], x[1]))

    merged: List[List[int]] = []
    current_start, current_end = validated[0]

    for i in range(1, len(validated)):
        next_start, next_end = validated[i]
        if next_start <= current_end:
            # Overlapping or touching
            current_end = max(current_end, next_end)
        else:
            merged.append([current_start, current_end])
            current_start, current_end = next_start, next_end

    merged.append([current_start, current_end])
    return merged
