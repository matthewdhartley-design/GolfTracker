import pandas as pd

from app.calculations.whs import compute_handicap_trend
from database.queries import get_all_hole_scores_with_par, get_macro_rounds


def get_full_handicap_history() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch every round and hole score, and run the full (unfiltered)
    sequential WHS + net-double-bogey-capping engine over all of it.

    Returns (rated_df, capped_holes_df) -- see compute_handicap_trend for
    columns. Rounds with placeholder/missing course_rating, slope_rating, or
    course_par are excluded from rated_df (same treatment as Macro Trends).

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
    ].sort_values("date")

    if rated_df.empty:
        return rated_df, pd.DataFrame()

    hole_df = hole_df[hole_df["round_id"].isin(rated_df["round_id"])]
    return compute_handicap_trend(rated_df, hole_df)
