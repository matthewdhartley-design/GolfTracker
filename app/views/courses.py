import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.calculations.handicap_data import get_full_handicap_history
from app.calculations.scoring import CATEGORY_ORDER, hole_score_distribution
from app.calculations.streaks import best_streak, best_streaks_by_round, max_consecutive_holes
from app.views.table_components import render_table_with_fixed_total
from database.queries import get_courses_with_hole_score_data, get_hole_info

_CATEGORY_COLORS = {
    "Birdie or Better": "#0ca30c",
    "Par": "#c3c2b7",
    "Bogey": "#eda100",
    "Double Bogey": "#eb6834",
    "Triple+ Bogey": "#d03b3b",
}
_CATEGORY_TABLE_LABELS = {
    "Birdie or Better": "Birdies",
    "Par": "Pars",
    "Bogey": "Bogeys",
    "Double Bogey": "Doubles",
    "Triple+ Bogey": "Triple+",
}
_DEFAULT_COURSE = "CCC"


def _use_capped_scores(holes_df: pd.DataFrame) -> pd.DataFrame:
    """Swap in the net-double-bogey-capped score as 'score' (keeping the
    original real score as 'raw_score') so downstream categorization/avg
    calculations use capped values without needing to know about capping.
    """
    return holes_df.rename(columns={"score": "raw_score", "capped_score": "score"})


def _distinct_or_joined(values) -> str:
    """Collapse a hole's per-tee values (e.g. par, stroke index) into a single
    display string -- the plain value if every tee agrees, or all distinct
    values joined with '/' if they don't (this genuinely happens: CCC's
    stroke index differs between tees on holes 12 and 14).
    """
    distinct = sorted(set(values))
    return str(distinct[0]) if len(distinct) == 1 else " / ".join(str(v) for v in distinct)


def _count_with_pct(counts: pd.DataFrame, key, category: str, total: int) -> str:
    count = int(counts.loc[key, category]) if key in counts.index else 0
    pct = round(100 * count / total) if total else 0
    return f"{count} ({pct}%)"


def _no_data_message():
    st.info(
        "No rounds yet have both hole-by-hole scores and course hole-by-hole "
        "par data recorded, so there's nothing to analyze."
    )


def _render_by_hole(capped_holes_df: pd.DataFrame):
    courses = get_courses_with_hole_score_data()

    if not courses:
        _no_data_message()
        return

    default_index = courses.index(_DEFAULT_COURSE) if _DEFAULT_COURSE in courses else 0
    selected_course = st.selectbox("Course", courses, index=default_index)

    scores_df = capped_holes_df[capped_holes_df["course_name"] == selected_course].copy()
    if scores_df.empty:
        st.info(f"No hole-level scoring data available for {selected_course}.")
        return

    available_tees = sorted(scores_df["tee_color_played"].unique().tolist())
    selected_tees = st.multiselect("Tee", available_tees, default=available_tees)
    scores_df = scores_df[scores_df["tee_color_played"].isin(selected_tees)]
    if scores_df.empty:
        st.info("No hole-level scoring data available for the selected tee(s).")
        return

    scores_df = _use_capped_scores(scores_df)
    scores_df["to_par"] = scores_df["score"] - scores_df["par"]
    st.caption(
        "Scores below are net-double-bogey capped for handicap purposes (WHS Rule 3.1) -- "
        "your original recorded scores are unchanged in the database."
    )

    hole_info = get_hole_info()
    hole_info = hole_info[
        (hole_info["course_name"] == selected_course) & (hole_info["tee_color"].isin(selected_tees))
    ]

    counts = hole_score_distribution(scores_df)

    fig = go.Figure()
    for category in CATEGORY_ORDER:
        fig.add_trace(go.Bar(
            x=counts.index,
            y=counts[category],
            name=category,
            marker_color=_CATEGORY_COLORS[category],
        ))
    fig.update_layout(
        barmode="stack",
        title=f"Score Distribution by Hole -- {selected_course}",
        xaxis_title="Hole",
        yaxis_title="Rounds",
        xaxis=dict(tickmode="linear", tick0=1, dtick=1),
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
        margin=dict(b=100),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Hole-by-Hole Performance")

    par_by_hole = hole_info.groupby("hole_number")["par"].apply(_distinct_or_joined)
    stroke_index_by_hole = hole_info.groupby("hole_number")["stroke_index"].apply(_distinct_or_joined)
    avg_to_par_by_hole = scores_df.groupby("hole_number")["to_par"].mean()
    row_totals = counts.sum(axis=1)

    rows = []
    for hole in range(1, 19):
        total = int(row_totals.get(hole, 0))
        row = {
            "Hole": str(hole),
            "Par": par_by_hole.get(hole, ""),
            "Stroke Index": stroke_index_by_hole.get(hole, ""),
            "Avg Score to Par": round(avg_to_par_by_hole[hole], 2) if hole in avg_to_par_by_hole.index else None,
        }
        for category in CATEGORY_ORDER:
            row[_CATEGORY_TABLE_LABELS[category]] = _count_with_pct(counts, hole, category, total)
        rows.append(row)

    grand_total = int(row_totals.sum())
    total_par = hole_info.groupby("hole_number")["par"].first()
    total_row = {
        "Hole": "Total",
        "Par": str(int(total_par.sum())) if not total_par.empty else "",
        "Stroke Index": "",
        "Avg Score to Par": round(scores_df["to_par"].mean(), 2),
    }
    for category in CATEGORY_ORDER:
        count = int(counts[category].sum())
        pct = round(100 * count / grand_total) if grand_total else 0
        total_row[_CATEGORY_TABLE_LABELS[category]] = f"{count} ({pct}%)"

    render_table_with_fixed_total(rows, total_row, table_id="by_hole")

    st.subheader("Score Summary by Par Type")

    par_lookup = hole_info.groupby("hole_number")["par"].first()
    scores_df["hole_par_type"] = scores_df["hole_number"].map(par_lookup)
    par_counts = hole_score_distribution_by_group(scores_df, "hole_par_type")
    par_row_totals = par_counts.sum(axis=1)

    par_rows = []
    for par_type in sorted(par_counts.index):
        total = int(par_row_totals.get(par_type, 0))
        subset = scores_df[scores_df["hole_par_type"] == par_type]
        row = {
            "Hole": f"Par {int(par_type)}",
            "Par": str(int(par_type)),
            "Stroke Index": "",
            "Avg Score to Par": round(subset["to_par"].mean(), 2),
        }
        for category in CATEGORY_ORDER:
            row[_CATEGORY_TABLE_LABELS[category]] = _count_with_pct(par_counts, par_type, category, total)
        par_rows.append(row)

    par_grand_total = int(par_row_totals.sum())
    par_total_row = {
        "Hole": "Total",
        "Par": "",
        "Stroke Index": "",
        "Avg Score to Par": round(scores_df["to_par"].mean(), 2),
    }
    for category in CATEGORY_ORDER:
        count = int(par_counts[category].sum())
        pct = round(100 * count / par_grand_total) if par_grand_total else 0
        par_total_row[_CATEGORY_TABLE_LABELS[category]] = f"{count} ({pct}%)"

    render_table_with_fixed_total(par_rows, par_total_row, table_id="par_type")


def hole_score_distribution_by_group(scores_df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """Like hole_score_distribution, but grouped by an arbitrary column
    (e.g. par type) instead of hole_number, with no fixed 1-18 row range.
    """
    from app.calculations.scoring import categorize_score

    df = scores_df.copy()
    df["category"] = [categorize_score(s, p) for s, p in zip(df["score"], df["par"])]
    counts = df.groupby([group_col, "category"]).size().unstack(fill_value=0)
    counts = counts.reindex(columns=CATEGORY_ORDER, fill_value=0)
    return counts


def _render_streaks(capped_holes_df: pd.DataFrame):
    if capped_holes_df.empty:
        _no_data_message()
        return

    all_holes = _use_capped_scores(capped_holes_df)
    st.caption(
        "Streaks are computed on net-double-bogey-capped scores (WHS Rule 3.1) -- "
        "your original recorded scores are unchanged in the database."
    )

    round_meta = (
        all_holes[["round_id", "date", "course_name", "tee_color_played", "total_score"]]
        .drop_duplicates()
        .sort_values("date", ascending=False)
    )
    round_meta["label"] = (
        pd.to_datetime(round_meta["date"]).dt.strftime("%d-%b-%y") + " -- "
        + round_meta["course_name"] + " (" + round_meta["tee_color_played"] + ") -- "
        + round_meta["total_score"].astype(str)
    )

    selected_label = st.selectbox("Round", round_meta["label"].tolist())
    selected_round_id = round_meta.loc[round_meta["label"] == selected_label, "round_id"].iloc[0]

    length = st.slider("Streak length (holes)", min_value=1, max_value=18, value=6)

    selected_round_holes = all_holes[all_holes["round_id"] == selected_round_id]
    selected_result = best_streak(selected_round_holes, length)

    if selected_result is None:
        longest = max_consecutive_holes(selected_round_holes)
        st.warning(
            f"This round doesn't have {length} consecutive holes recorded -- "
            f"the longest consecutive run available is {longest} holes."
        )
    else:
        sign = "+" if selected_result["to_par"] > 0 else ""
        st.metric(
            f"Best {length}-Hole Streak",
            f"{sign}{selected_result['to_par']} to par",
            help=f"Holes {selected_result['start_hole']}-{selected_result['end_hole']}",
        )
        st.caption(f"Holes {selected_result['start_hole']} to {selected_result['end_hole']}")

    all_best = best_streaks_by_round(all_holes, length)
    if not all_best:
        st.info(f"No round has {length} consecutive holes recorded yet.")
        return

    to_par_values = pd.Series([v["to_par"] for v in all_best.values()])
    value_counts = to_par_values.value_counts().sort_index()
    full_range = range(int(value_counts.index.min()), int(value_counts.index.max()) + 1)
    value_counts = value_counts.reindex(full_range, fill_value=0)

    bar_colors = [
        "#0ca30c" if (selected_result is not None and x == selected_result["to_par"]) else "#2a78d6"
        for x in value_counts.index
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[str(x) for x in value_counts.index],
        y=value_counts.values,
        marker_color=bar_colors,
    ))
    fig.update_layout(
        title=f"Best {length}-Hole Streak Distribution -- All Rounds ({len(all_best)} rounds)",
        xaxis_title="Best Streak (Strokes to Par)",
        yaxis_title="Number of Rounds",
    )
    st.plotly_chart(fig, use_container_width=True)
    if selected_result is not None:
        st.caption(
            f"This round's best {length}-hole streak ({selected_result['to_par']:+d}) "
            "is highlighted in green above."
        )


def render_course_analyzer():
    """Render the Course Analyzer tab."""
    _, capped_holes_df = get_full_handicap_history()

    tab_by_hole, tab_streaks = st.tabs(["By Hole", "Streaks"])

    with tab_by_hole:
        _render_by_hole(capped_holes_df)

    with tab_streaks:
        _render_streaks(capped_holes_df)
