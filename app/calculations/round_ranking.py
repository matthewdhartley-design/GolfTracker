import pandas as pd

# CCC changed its Yellow tee's course rating in April 2026 (see golf_schema
# memory notes), so the same physical tee is split into two tee_color_played
# values in the DB. For ranking purposes they're the same tee.
_CCC_YELLOW_VARIANTS = {"Yellow", "Pre April 26 - Yellow"}


def _tee_group(course_name: str, tee_color: str) -> str:
    if course_name == "CCC" and tee_color in _CCC_YELLOW_VARIANTS:
        return "Yellow (merged)"
    return tee_color


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _rank_within(round_id: int, subset: pd.DataFrame) -> tuple[int, int] | None:
    """(rank, total) for round_id within `subset`, ranked by score_differential
    (rank 1 = lowest/best differential). None if the round isn't in `subset`."""
    if round_id not in subset["round_id"].values:
        return None
    ordered = subset.sort_values("score_differential").reset_index(drop=True)
    rank = int(ordered.index[ordered["round_id"] == round_id][0]) + 1
    return rank, len(ordered)


def compute_round_rankings(round_id: int, global_rated_df: pd.DataFrame) -> list[tuple[str, str]]:
    """Where a round's score differential ranks (best = lowest) among five
    comparison groups, each computed against the full (unfiltered) history
    regardless of any course/tee/year filters currently applied on screen:
      - Same Course & Tee (CCC's Yellow/Pre April 26 - Yellow tees merged)
      - Same Course (any tee)
      - All Time (every rated round)
      - Last 12 Months (the 12 months up to and including this round's date)
      - Calendar Year (every round in the same calendar year)

    Returns a list of (label, formatted rank string) pairs, skipping any
    group the round isn't part of (e.g. if course rating data is missing).
    """
    match = global_rated_df[global_rated_df["round_id"] == round_id]
    if match.empty:
        return []
    round_row = match.iloc[0]
    course = round_row["course_name"]
    tee = round_row["tee_color_played"]
    date = pd.Timestamp(round_row["date"])
    this_tee_group = _tee_group(course, tee)

    dates = pd.to_datetime(global_rated_df["date"])

    groups = {
        "Same Course & Tee": global_rated_df[
            (global_rated_df["course_name"] == course)
            & (
                global_rated_df.apply(
                    lambda r: _tee_group(r["course_name"], r["tee_color_played"]), axis=1
                )
                == this_tee_group
            )
        ],
        "Same Course (Any Tee)": global_rated_df[global_rated_df["course_name"] == course],
        "All Time": global_rated_df,
        "Last 12 Months": global_rated_df[
            (dates > date - pd.DateOffset(months=12)) & (dates <= date)
        ],
        f"Calendar Year {date.year}": global_rated_df[dates.dt.year == date.year],
    }

    results = []
    for label, subset in groups.items():
        ranked = _rank_within(round_id, subset)
        if ranked is None:
            continue
        rank, total = ranked
        percentile = max(1, round(rank / total * 100))
        results.append((label, f"{_ordinal(rank)} best of {total} (top {percentile}%)"))
    return results
