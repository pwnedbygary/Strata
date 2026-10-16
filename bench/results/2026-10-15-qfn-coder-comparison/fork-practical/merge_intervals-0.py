def merge_intervals(intervals: list[list[int]]) -> list[list[int]]:
    """Merge overlapping or touching intervals.

    Parameters:
        intervals: A list of [start, end] pairs with integer endpoints.

    Returns:
        A new list of merged [start, end] pairs sorted by start.

    Raises:
        ValueError: If input is malformed, contains non-integer endpoints
                    (including booleans), or has start > end.
    """
    if not isinstance(intervals, list):
        raise ValueError("Input must be a list")

    validated: list[tuple[int, int]] = []
    for item in intervals:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("Each interval must be a list of exactly two elements")
        start, end = item[0], item[1]
        # Reject booleans explicitly (bool is subclass of int)
        if isinstance(start, bool) or isinstance(end, bool):
            raise ValueError("Endpoints must be integers, not booleans")
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError("Endpoints must be integers")
        if start > end:
            raise ValueError("start must not be greater than end")
        validated.append((start, end))

    if not validated:
        return []

    validated.sort(key=lambda x: x[0])

    merged: list[list[int]] = []
    cur_start, cur_end = validated[0]
    for i in range(1, len(validated)):
        s, e = validated[i]
        if s <= cur_end:  # overlapping or touching
            if e > cur_end:
                cur_end = e
        else:
            merged.append([cur_start, cur_end])
            cur_start, cur_end = s, e
    merged.append([cur_start, cur_end])
    return merged
