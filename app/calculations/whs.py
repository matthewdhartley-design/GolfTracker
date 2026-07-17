import pandas as pd

from app.calculations.net_double_bogey import capped_hole_score, course_handicap

# WHS Rule 5.1 selection table: number of recent scores available ->
# (number of best differentials to average, adjustment applied to that average).
_SELECTION_TABLE = {
    1: (1, -2.0), 2: (1, -2.0), 3: (1, -2.0),
    4: (1, -1.0),
    5: (1, 0.0),
    6: (2, -1.0),
    7: (2, 0.0), 8: (2, 0.0),
    9: (3, 0.0), 10: (3, 0.0), 11: (3, 0.0),
    12: (4, 0.0), 13: (4, 0.0), 14: (4, 0.0),
    15: (5, 0.0), 16: (5, 0.0),
    17: (6, 0.0), 18: (6, 0.0),
    19: (7, 0.0),
    20: (8, 0.0),
}


def score_differential(total_score, course_rating, slope_rating):
    """WHS score differential: (113 / Slope Rating) * (Score - Course Rating),
    rounded to 1 decimal place per WHS convention.

    Works elementwise on pandas Series as well as plain scalars.
    """
    return round((113 / slope_rating) * (total_score - course_rating), 1)


def _select_best(differentials: list[float]) -> list[float]:
    """The best (lowest) differentials selected per Rule 5.1, out of at
    most the most recent 20 scores.
    """
    recent = differentials[-20:]
    num_to_use, _ = _SELECTION_TABLE[len(recent)]
    return sorted(recent)[:num_to_use]


def handicap_index(differentials: list[float]) -> float | None:
    """WHS Handicap Index (Rule 5.1) from a chronological list of score
    differentials, using at most the most recent 20. Returns None if the
    list is empty.
    """
    if not differentials:
        return None
    best = _select_best(differentials)
    _, adjustment = _SELECTION_TABLE[len(differentials[-20:])]
    return round(sum(best) / len(best) + adjustment, 1)


def counts_toward_current_handicap(df: pd.DataFrame) -> pd.Series:
    """Boolean mask marking which rows' score_differential contributed to
    the current (most recent) WHS handicap index, per Rule 5.1: the best
    N differentials among the most recent 20 rows.
    """
    recent = df.tail(20)
    num_to_use, _ = _SELECTION_TABLE[len(recent)]
    counting_index = recent["score_differential"].sort_values().index[:num_to_use]

    mask = pd.Series(False, index=df.index)
    mask.loc[counting_index] = True
    return mask


def _select_worst(differentials: list[float], count: int) -> list[float]:
    """The worst (highest) `count` differentials, out of at most the most
    recent 20 scores (fewer if fewer are available).
    """
    recent = differentials[-20:]
    n = min(count, len(recent))
    return sorted(recent, reverse=True)[:n]


def high_handicap_index(differentials: list[float]) -> float | None:
    """'High Handicap': the plain average of the worst 8 score differentials
    among the most recent 20 (fewer if fewer than 8 are available yet). This
    is not an official WHS metric -- no Rule 5.1 small-sample adjustment is
    applied, since that adjustment is specific to the best-side calculation.
    """
    if not differentials:
        return None
    worst = _select_worst(differentials, 8)
    return round(sum(worst) / len(worst), 1)


def counts_toward_current_high_handicap(df: pd.DataFrame) -> pd.Series:
    """Boolean mask marking which rows' score_differential contributed to
    the current (most recent) High Handicap: the worst 8 differentials
    among the most recent 20 rows (fewer if fewer than 8 are available yet).
    """
    recent = df.tail(20)
    count = min(8, len(recent))
    counting_index = recent["score_differential"].sort_values(ascending=False).index[:count]

    mask = pd.Series(False, index=df.index)
    mask.loc[counting_index] = True
    return mask


def _is_placeholder(value) -> bool:
    """True if a rating-type value is missing or this project's '0' placeholder
    sentinel for "not yet supplied" (see golf_schema memory notes)."""
    return pd.isna(value) or value == 0


def compute_handicap_trend(
    rounds_df: pd.DataFrame, hole_df: pd.DataFrame | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add handicap trend columns to a chronologically-sorted rounds
    DataFrame that has round_id, total_score, course_rating, slope_rating,
    and course_par columns, and return (rounds_result, capped_holes).

    Every round's score used for the differential is net-double-bogey capped
    when possible (adjusted gross score, per WHS): each hole is capped at
    par + 2 + the strokes that round's Course Handicap grants on that hole,
    where Course Handicap is derived from the WHS Handicap Index as it stood
    immediately *before* that round (a genuinely sequential, rolling
    computation -- capping round N affects the index used to cap round N+1).
    Capping requires `hole_df` to have a matching round_id/hole_number group
    with all 18 holes present (a partial set, e.g. 16 of 18 holes recorded,
    would silently sum to far less than the real round and produce a bogus
    low differential -- summing only what's there is not the same as
    capping), par/stroke_index, a real (non-placeholder) course_par/
    course_rating/slope_rating, and a prior Handicap Index to already exist
    (impossible for the very first rated round). Whenever any of that is
    unavailable, the round's raw total_score is used unchanged -- this is a
    deliberate fallback, not an error.

    rounds_result columns (one row per round):
    - effective_score: the score actually used for this round's differential
      (net-double-bogey capped where possible, else raw total_score).
    - course_handicap_used: the Course Handicap applied for capping, or None
      if this round's score wasn't capped.
    - score_differential: the WHS score differential for that round.
    - whs_handicap_index / counting_low / counting_high: the WHS Rule 5.1
      handicap index after that round, and the min/max of the differentials
      that fed into it at that point in time.
    - counts_toward_handicap: marks which rows feed into the latest
      (most recent) whs_handicap_index, for chart highlighting.
    - high_handicap_index / high_counting_low / high_counting_high: the
      "High Handicap" (worst-8) mirror of the above, after that round.
    - counts_toward_high_handicap: marks which rows feed into the latest
      (most recent) high_handicap_index.

    capped_holes columns: every column from hole_df for rounds with hole
    data, plus 'capped_score' (equal to 'score' wherever capping wasn't
    possible for that round).
    """
    df = rounds_df.sort_values("date").reset_index(drop=True).copy()

    holes_by_round = (
        {round_id: group for round_id, group in hole_df.groupby("round_id")}
        if hole_df is not None and not hole_df.empty
        else {}
    )

    running: list[float] = []
    effective_scores = []
    course_handicaps_used = []
    index_after_round = []
    counting_low = []
    counting_high = []
    high_index_after_round = []
    high_counting_low = []
    high_counting_high = []
    capped_hole_groups = []

    for row in df.itertuples():
        prior_index = handicap_index(running)

        hole_group = holes_by_round.get(row.round_id)
        can_cap = (
            hole_group is not None
            and len(hole_group) == 18
            and prior_index is not None
            and not _is_placeholder(row.course_par)
            and not _is_placeholder(row.course_rating)
            and not _is_placeholder(row.slope_rating)
        )

        if can_cap:
            ch = course_handicap(prior_index, row.slope_rating, row.course_rating, row.course_par)
            hole_group = hole_group.copy()
            hole_group["capped_score"] = [
                capped_hole_score(score, par, si, ch)
                for score, par, si in zip(hole_group["score"], hole_group["par"], hole_group["stroke_index"])
            ]
            effective_score = hole_group["capped_score"].sum()
            capped_hole_groups.append(hole_group)
        else:
            ch = None
            effective_score = row.total_score
            if hole_group is not None:
                hole_group = hole_group.copy()
                hole_group["capped_score"] = hole_group["score"]
                capped_hole_groups.append(hole_group)

        effective_scores.append(effective_score)
        course_handicaps_used.append(ch)

        diff = score_differential(effective_score, row.course_rating, row.slope_rating)
        running.append(diff)

        index_after_round.append(handicap_index(running))
        best = _select_best(running)
        counting_low.append(min(best))
        counting_high.append(max(best))

        high_index_after_round.append(high_handicap_index(running))
        worst = _select_worst(running, 8)
        high_counting_low.append(min(worst))
        high_counting_high.append(max(worst))

    df["effective_score"] = effective_scores
    df["course_handicap_used"] = course_handicaps_used
    df["score_differential"] = running
    df["whs_handicap_index"] = index_after_round
    df["counting_low"] = counting_low
    df["counting_high"] = counting_high
    df["counts_toward_handicap"] = counts_toward_current_handicap(df)

    df["high_handicap_index"] = high_index_after_round
    df["high_counting_low"] = high_counting_low
    df["high_counting_high"] = high_counting_high
    df["counts_toward_high_handicap"] = counts_toward_current_high_handicap(df)

    capped_holes = (
        pd.concat(capped_hole_groups, ignore_index=True)
        if capped_hole_groups
        else pd.DataFrame(columns=(hole_df.columns.tolist() if hole_df is not None else []) + ["capped_score"])
    )

    return df, capped_holes
