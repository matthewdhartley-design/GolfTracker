import pandas as pd

# Shared "at or better than" score-to-par categories used by both the All Time
# Records tab (all-history streak stats) and the Macro Trends rounds table
# (per-round streak callouts).
STREAK_CATEGORIES = [
    ("Birdie or Better", -1),
    ("Par or Better", 0),
    ("Bogey or Better", 1),
    ("Double or Better", 2),
]


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


def _maximal_runs(holes_df: pd.DataFrame, max_to_par: int) -> list[dict]:
    """Every maximal run of *consecutive* hole numbers within one round's
    hole rows where score - par <= max_to_par (e.g. -1 for birdie-or-better).

    A missing hole_number breaks a run, same as best_streak() -- we can't
    confirm a skipped hole would have continued qualifying, so it doesn't.
    Returns a list of {"start_hole", "end_hole", "length"}.
    """
    ordered = holes_df.sort_values("hole_number")
    hole_numbers = ordered["hole_number"].tolist()
    qualifies = (ordered["score"] - ordered["par"] <= max_to_par).tolist()

    runs = []
    start = None
    prev_hole = None
    for hole, ok in zip(hole_numbers, qualifies):
        is_consecutive = prev_hole is not None and hole == prev_hole + 1
        if not is_consecutive and start is not None:
            runs.append({"start_hole": start, "end_hole": prev_hole})
            start = None
        if ok:
            if start is None:
                start = hole
        elif start is not None:
            runs.append({"start_hole": start, "end_hole": prev_hole})
            start = None
        prev_hole = hole

    if start is not None:
        runs.append({"start_hole": start, "end_hole": prev_hole})

    for run in runs:
        run["length"] = run["end_hole"] - run["start_hole"] + 1
    return runs


def category_streaks(all_holes_df: pd.DataFrame, max_to_par: int) -> list[dict]:
    """Every maximal run of consecutive holes across all rounds in
    all_holes_df where score - par <= max_to_par (e.g. -1 for birdie-or-
    better, 0 for par-or-better). Each run is tagged with its round_id so
    the caller can look up when/where it happened.

    Rounds are never combined -- a streak always resets at the boundary
    between two rounds, even if their hole numbers happen to be adjacent
    (e.g. hole 18 of one round and hole 1 of the next).
    """
    runs = []
    for round_id, group in all_holes_df.groupby("round_id"):
        for run in _maximal_runs(group, max_to_par):
            run["round_id"] = round_id
            runs.append(run)
    return runs


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
