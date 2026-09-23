import pandas as pd

from app.calculations.whs import compute_handicap_trend
from database.queries import get_all_hole_scores_with_par, get_macro_rounds


def get_full_handicap_history() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch every round and hole score, and run the full (unfiltered)
    sequential WHS + net-double-bogey-capping engine over all of it.

    Returns (rated_df, capped_holes_df) -- see compute_handicap_trend for
    columns. Rounds with placeholder/missing course_rating, slope_rating, or
    course_par are excluded from rated_df (same treatment as Macro Trends),
    as are rounds explicitly flagged excluded_from_handicap.

    This is the *global* history (not filtered to a course/tee/year, unlike
    Macro Trends' deliberately-filtered recomputation) -- callers that only
    care about one course should filter capped_holes_df by course_name
    afterward rather than filtering the input, since the rolling handicap
    calculation needs your whole real history to be accurate.
    """
    rounds_df = get_macro_rounds()
    hole_df = get_all_hole_scores_with_par()

    rated_df = rounds_df[
        rounds_df["course_rating"].notna() & (rounds_df["course_rating"] != 0)
        & rounds_df["slope_rating"].notna() & (rounds_df["slope_rating"] != 0)
        & ~rounds_df["excluded_from_handicap"]
    ].sort_values("date")

    if rated_df.empty:
        return rated_df, pd.DataFrame()

    hole_df = hole_df[hole_df["round_id"].isin(rated_df["round_id"])]
    return compute_handicap_trend(rated_df, hole_df)


def yearly_handicap_lows(rated_df: pd.DataFrame) -> list[dict]:
    """One row per calendar year present in rated_df: the round_id, date, and
    value of that year's lowest WHS Handicap Index -- used to overlay a
    "best of the year" callout on charts spanning rated_df's date range.
    """
    if rated_df.empty:
        return []
    year_series = pd.to_datetime(rated_df["date"]).dt.year
    best_idx_per_year = rated_df.groupby(year_series)["whs_handicap_index"].idxmin()
    return [
        {
            "year": int(year),
            "round_id": rated_df.loc[idx, "round_id"],
            "date": rated_df.loc[idx, "date"],
            "whs_handicap_index": rated_df.loc[idx, "whs_handicap_index"],
        }
        for year, idx in best_idx_per_year.items()
    ]
