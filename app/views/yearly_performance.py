import pandas as pd
import streamlit as st

from app.calculations.handicap_data import get_full_handicap_history
from app.calculations.scoring import CATEGORY_ORDER, categorize_score
from app.calculations.streaks import STREAK_CATEGORIES, category_streaks
from database.queries import get_macro_rounds

_SEASON_START = (4, 1)   # April 1
_SEASON_END = (9, 30)    # September 30, inclusive


def _filter_period(
    df: pd.DataFrame, year: int, in_season: bool, competitions_only: bool = False
) -> pd.DataFrame:
    """Rows from `df` (must have a 'date' column) falling in the given
    calendar year, optionally restricted to the Apr 1 - Sep 30 "season"
    and/or to rounds with a competition_name set."""
    dates = pd.to_datetime(df["date"])
    mask = dates.dt.year == year
    if in_season:
        season_start = pd.Timestamp(year, *_SEASON_START)
        season_end = pd.Timestamp(year, *_SEASON_END)
        mask &= (dates >= season_start) & (dates <= season_end)
    if competitions_only:
        mask &= df["competition_name"].notna()
    return df[mask]


def _best_worst_rows(period_rated: pd.DataFrame, n: int, ascending: bool) -> list[dict]:
    subset = period_rated.sort_values("score_differential", ascending=ascending).head(n)
    return [
        {
            "Date": pd.Timestamp(row.date).strftime("%d-%b-%y"),
            "Course": row.course_name,
            "Tee": row.tee_color_played,
            "Score": int(row.total_score),
            "Score Differential": row.score_differential,
        }
        for row in subset.itertuples()
    ]


def _longest_streaks(period_holes: pd.DataFrame) -> list[dict]:
    """Longest streak achieved in this period for each category, in the
    same style as the All Time Records tab, but scoped to just this
    year/season's rounds."""
    holes = period_holes.rename(columns={"score": "raw_score", "capped_score": "score"})
    round_meta = holes[["round_id", "date", "course_name"]].drop_duplicates().set_index("round_id")

    rows = []
    for label, max_to_par in STREAK_CATEGORIES:
        runs = category_streaks(holes, max_to_par)
        if not runs:
            rows.append({"Category": label, "Longest Streak": "-", "Course": "-", "Date": "-"})
            continue
        best = max(runs, key=lambda r: r["length"])
        meta = round_meta.loc[best["round_id"]]
        rows.append({
            "Category": label,
            "Longest Streak": f"{best['length']} holes",
            "Course": meta["course_name"],
            "Date": pd.Timestamp(meta["date"]).strftime("%d-%b-%y"),
        })
    return rows


def _render_period_column(
    rounds_df: pd.DataFrame, rated_df: pd.DataFrame, capped_holes_df: pd.DataFrame, key_prefix: str
):
    years = sorted(pd.to_datetime(rounds_df["date"]).dt.year.unique().tolist(), reverse=True)
    year = st.selectbox("Year", years, key=f"{key_prefix}_year")
    in_season = st.checkbox(
        "In-season only (Apr 1 - Sep 30)", key=f"{key_prefix}_in_season"
    )
    competitions_only = st.checkbox(
        "Competition rounds only", key=f"{key_prefix}_competitions_only"
    )

    period_rounds = _filter_period(rounds_df, year, in_season, competitions_only)
    # rated_df/capped_holes_df don't carry competition_name (capped_holes_df
    # comes from a separate hole-level query), so once period_rounds has the
    # right round_id set (year + season + competition filters all applied),
    # filter the other two frames by membership in that set rather than
    # re-checking competition_name on them directly.
    qualifying_ids = set(period_rounds["round_id"])
    period_rated = (
        rated_df[rated_df["round_id"].isin(qualifying_ids)] if not rated_df.empty else rated_df
    )
    period_holes = (
        capped_holes_df[capped_holes_df["round_id"].isin(qualifying_ids)]
        if not capped_holes_df.empty else capped_holes_df
    )

    label = f"{year}" + (" (In-Season)" if in_season else " (Full Year)")
    if competitions_only:
        label += " -- Competitions Only"
    st.subheader(label)

    if period_rounds.empty:
        st.info("No rounds recorded in this period.")
        return

    total_rounds = len(period_rounds)
    best_gross = int(period_rounds["total_score"].min())
    worst_gross = int(period_rounds["total_score"].max())
    avg_gross = round(period_rounds["total_score"].mean(), 1)

    col1, col2 = st.columns(2)
    col1.metric("Rounds Played", total_rounds)
    col2.metric("Average Score", avg_gross)
    col3, col4 = st.columns(2)
    col3.metric("Best Score", best_gross)
    col4.metric("Worst Score", worst_gross)

    if not period_rated.empty:
        avg_diff = round(period_rated["score_differential"].mean(), 1)
        start_hcp = period_rated.sort_values("date").iloc[0]["whs_handicap_index"]
        end_hcp = period_rated.sort_values("date").iloc[-1]["whs_handicap_index"]
        col5, col6 = st.columns(2)
        col5.metric("Avg Score Differential", avg_diff)
        col6.metric(
            "Handicap: Start to End",
            f"{end_hcp:.1f}",
            delta=f"{end_hcp - start_hcp:+.1f} from {start_hcp:.1f}",
            delta_color="inverse",
        )

    st.markdown("**Top 5 Courses by Rounds Played**")
    top_courses = period_rounds.groupby("course_name").size().sort_values(ascending=False).head(5)
    st.dataframe(
        pd.DataFrame({"Course": top_courses.index, "Rounds": top_courses.values}),
        hide_index=True, width="stretch",
    )

    if not period_holes.empty:
        holes = period_holes.rename(columns={"score": "raw_score", "capped_score": "score"})
        holes["category"] = [categorize_score(s, p) for s, p in zip(holes["score"], holes["par"])]
        category_counts = holes["category"].value_counts().reindex(CATEGORY_ORDER, fill_value=0)
        total_holes = int(category_counts.sum())

        st.markdown("**Score Distribution (Net-Double-Bogey Capped)**")
        st.dataframe(
            pd.DataFrame({
                "Category": CATEGORY_ORDER,
                "Count": [int(category_counts[c]) for c in CATEGORY_ORDER],
                "% of Holes": [
                    f"{round(100 * category_counts[c] / total_holes)}%" if total_holes else "0%"
                    for c in CATEGORY_ORDER
                ],
            }),
            hide_index=True, width="stretch",
        )

        st.markdown("**Longest Streaks This Period**")
        st.dataframe(pd.DataFrame(_longest_streaks(period_holes)), hide_index=True, width="stretch")

    if not period_rated.empty:
        st.markdown("**5 Best Rounds**")
        st.dataframe(
            pd.DataFrame(_best_worst_rows(period_rated, 5, ascending=True)),
            hide_index=True, width="stretch",
        )

        st.markdown("**5 Worst Rounds**")
        st.dataframe(
            pd.DataFrame(_best_worst_rows(period_rated, 5, ascending=False)),
            hide_index=True, width="stretch",
        )


def render_yearly_performance():
    """Render the Yearly/Seasonal Performance tab: two side-by-side columns,
    each an independently-selected year (optionally restricted to the
    Apr 1 - Sep 30 "season"), with a broad set of comparison stats.
    """
    rounds_df = get_macro_rounds()
    if rounds_df.empty:
        st.info("No rounds recorded yet.")
        return

    rated_df, capped_holes_df = get_full_handicap_history()

    left_col, right_col = st.columns(2)
    with left_col:
        _render_period_column(rounds_df, rated_df, capped_holes_df, key_prefix="yearly_left")
    with right_col:
        _render_period_column(rounds_df, rated_df, capped_holes_df, key_prefix="yearly_right")
