import pandas as pd

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


def compute_handicap_trend(rounds_df: pd.DataFrame) -> pd.DataFrame:
    """Add handicap trend columns to a chronologically-sorted rounds
    DataFrame that has total_score, course_rating, and slope_rating columns:

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
    """
    df = rounds_df.copy()
    df["score_differential"] = score_differential(
        df["total_score"], df["course_rating"], df["slope_rating"]
    )

    running: list[float] = []
    index_after_round = []
    counting_low = []
    counting_high = []
    high_index_after_round = []
    high_counting_low = []
    high_counting_high = []
    for diff in df["score_differential"]:
        running.append(diff)

        index_after_round.append(handicap_index(running))
        best = _select_best(running)
        counting_low.append(min(best))
        counting_high.append(max(best))

        high_index_after_round.append(high_handicap_index(running))
        worst = _select_worst(running, 8)
        high_counting_low.append(min(worst))
        high_counting_high.append(max(worst))

    df["whs_handicap_index"] = index_after_round
    df["counting_low"] = counting_low
    df["counting_high"] = counting_high
    df["counts_toward_handicap"] = counts_toward_current_handicap(df)

    df["high_handicap_index"] = high_index_after_round
    df["high_counting_low"] = high_counting_low
    df["high_counting_high"] = high_counting_high
    df["counts_toward_high_handicap"] = counts_toward_current_high_handicap(df)

    return df
