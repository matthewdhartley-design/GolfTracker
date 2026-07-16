import pandas as pd


def best_streak(holes_df: pd.DataFrame, length: int) -> dict | None:
    """Given one round's hole_number/score/par rows (not necessarily every
    hole present), find the best (lowest to-par) run of `length`
    *consecutive* hole numbers, sliding the window across every possible
    starting point until no more windows of that length fit.

    Returns {"to_par": int, "start_hole": int, "end_hole": int}, or None if
    the round doesn't have `length` consecutive holes anywhere.
    """
    ordered = holes_df.sort_values("hole_number")
    hole_numbers = ordered["hole_number"].tolist()
    diffs = (ordered["score"] - ordered["par"]).tolist()

    best = None
    n = len(hole_numbers)
    for i in range(n - length + 1):
        window_holes = hole_numbers[i:i + length]
        if window_holes[-1] - window_holes[0] != length - 1:
            continue  # gap inside this window -- not truly consecutive
        window_to_par = sum(diffs[i:i + length])
        if best is None or window_to_par < best["to_par"]:
            best = {
                "to_par": window_to_par,
                "start_hole": window_holes[0],
                "end_hole": window_holes[-1],
            }
    return best


def max_consecutive_holes(holes_df: pd.DataFrame) -> int:
    """Longest run of consecutive hole numbers present in this round's data."""
    hole_numbers = sorted(holes_df["hole_number"].tolist())
    if not hole_numbers:
        return 0
    longest = current = 1
    for i in range(1, len(hole_numbers)):
        if hole_numbers[i] == hole_numbers[i - 1] + 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


def best_streaks_by_round(all_holes_df: pd.DataFrame, length: int) -> dict[int, dict]:
    """Compute best_streak() for every round_id in all_holes_df, for a given
    streak length. Rounds that can't support that streak length are omitted.
    Returns {round_id: {"to_par", "start_hole", "end_hole"}}.
    """
    results = {}
    for round_id, group in all_holes_df.groupby("round_id"):
        streak = best_streak(group, length)
        if streak is not None:
            results[round_id] = streak
    return results
