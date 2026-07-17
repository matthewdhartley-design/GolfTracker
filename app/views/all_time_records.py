import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from scipy import stats

from app.calculations.handicap_data import get_full_handicap_history
from app.calculations.streaks import STREAK_CATEGORIES, category_streaks
from app.views.table_components import scorecard_html

_BIN_WIDTH = 2.0


def _compute_streaks_by_category(capped_holes_df: pd.DataFrame) -> dict:
    """Every maximal streak run for each category, plus the hole rows used
    to qualify them (score = capped, raw_score = actual strokes) and round
    metadata -- computed once and shared by the table and the histogram.
    """
    holes = capped_holes_df.rename(columns={"score": "raw_score", "capped_score": "score"})
    round_meta = (
        holes[["round_id", "date", "course_name", "tee_color_played"]]
        .drop_duplicates()
        .set_index("round_id")
    )
    runs_by_category = {
        label: category_streaks(holes, max_to_par) for label, max_to_par in STREAK_CATEGORIES
    }
    return {"holes": holes, "round_meta": round_meta, "runs_by_category": runs_by_category}


def _streak_table_rows(streaks: dict) -> list[dict]:
    """One row per streak category: the longest run of consecutive holes
    ever achieved at or better than that category, how many times that
    exact length has been reached, and the details of the most recent one.

    Streaks qualify on net-double-bogey-capped scores (WHS Rule 3.1), same
    as everywhere else in this app, but "Gross Score" below reports the
    real, uncapped strokes actually taken over those holes.
    """
    holes = streaks["holes"]
    round_meta = streaks["round_meta"]

    rows = []
    for label, _ in STREAK_CATEGORIES:
        runs = streaks["runs_by_category"][label]
        if not runs:
            rows.append({
                "Category": label, "Longest Streak": "-", "Times Achieved": 0,
                "Most Recent Date": "-", "Course": "-", "Holes": "-",
                "Gross Score": "-", "To Par": "-",
            })
            continue

        best_length = max(r["length"] for r in runs)
        best_runs = [r for r in runs if r["length"] == best_length]
        for r in best_runs:
            r["date"] = round_meta.loc[r["round_id"], "date"]
        best_runs.sort(key=lambda r: r["date"], reverse=True)
        most_recent = best_runs[0]

        round_holes = holes[holes["round_id"] == most_recent["round_id"]]
        segment = round_holes[
            (round_holes["hole_number"] >= most_recent["start_hole"])
            & (round_holes["hole_number"] <= most_recent["end_hole"])
        ]
        gross = int(segment["raw_score"].sum())
        to_par = gross - int(segment["par"].sum())

        rows.append({
            "Category": label,
            "Longest Streak": f"{best_length} holes",
            "Times Achieved": len(best_runs),
            "Most Recent Date": pd.Timestamp(most_recent["date"]).strftime("%d-%b-%y"),
            "Course": round_meta.loc[most_recent["round_id"], "course_name"],
            "Holes": f"{most_recent['start_hole']}-{most_recent['end_hole']}",
            "Gross Score": gross,
            "To Par": f"{to_par:+d}" if to_par != 0 else "E",
        })
    return rows


def _render_scorecard(round_holes: pd.DataFrame, start_hole: int, end_hole: int):
    """Render a classic horizontal scorecard (Hole/Par/Handicap/Score rows,
    front 9 then back 9), highlighting the Score cells for holes in
    [start_hole, end_hole] -- the holes that made up the selected streak.
    """
    # round_holes has capped score in "score" and real strokes in "raw_score"
    # (see _compute_streaks_by_category) -- the scorecard itself should show
    # real, uncapped strokes.
    display_holes = round_holes.assign(score=round_holes["raw_score"])

    html = f"""
    <style>
        html, body {{
            margin: 0;
            background-color: #ffffff;
            color: #31333f;
            font-family: system-ui,-apple-system,'Segoe UI',sans-serif;
        }}
        @media (prefers-color-scheme: dark) {{
            html, body {{ background-color: #0e1117; color: #fafafa; }}
        }}
    </style>
    <div>
    {scorecard_html(display_holes, start_hole, end_hole)}
    </div>
    """
    components.html(html, height=310)


def render_all_time_records():
    """Render the All Time Records tab: a histogram of score differentials
    across your entire recorded history, with a fitted normal ("bell curve")
    overlay for reference.
    """
    rated_df, _ = get_full_handicap_history()

    if rated_df.empty:
        st.info("No rated rounds yet -- nothing to show here.")
        return

    diffs = rated_df["score_differential"]

    bin_edges = np.arange(
        np.floor(diffs.min() / _BIN_WIDTH) * _BIN_WIDTH,
        np.ceil(diffs.max() / _BIN_WIDTH) * _BIN_WIDTH + _BIN_WIDTH,
        _BIN_WIDTH,
    )
    counts, edges = np.histogram(diffs, bins=bin_edges)
    bin_centers = (edges[:-1] + edges[1:]) / 2

    mean, std = diffs.mean(), diffs.std()
    x_curve = np.linspace(edges[0], edges[-1], 200)
    y_curve = stats.norm.pdf(x_curve, mean, std) * len(diffs) * _BIN_WIDTH

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=bin_centers,
        y=counts,
        width=_BIN_WIDTH * 0.9,
        name="Rounds",
        marker_color="#2a78d6",
    ))
    fig.add_trace(go.Scatter(
        x=x_curve,
        y=y_curve,
        mode="lines",
        name=f"Normal Fit (μ={mean:.1f}, σ={std:.1f})",
        line=dict(width=2, color="#d03b3b"),
    ))
    fig.update_layout(
        title="Distribution of Score Differentials",
        xaxis_title="Score Differential",
        yaxis_title="Count",
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
        margin=dict(b=100),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Longest Streaks")
    st.caption(
        "Streaks qualify on net-double-bogey-capped scores (WHS Rule 3.1); "
        "Gross Score and To Par below are the real, uncapped strokes taken over those holes."
    )
    _, capped_holes_df = get_full_handicap_history()
    if capped_holes_df.empty:
        st.info("No hole-by-hole data recorded yet.")
        return

    streaks = _compute_streaks_by_category(capped_holes_df)

    event = st.dataframe(
        pd.DataFrame(_streak_table_rows(streaks)),
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row-required",
    )

    selected_idx = event.selection.rows[0] if event.selection.rows else 0
    selected_label, _ = STREAK_CATEGORIES[selected_idx]
    # A "streak" of a single hole isn't really a streak -- exclude it so the
    # chart focuses on genuine runs of 2+ consecutive holes.
    lengths = [
        run["length"] for run in streaks["runs_by_category"][selected_label] if run["length"] > 1
    ]

    if not lengths:
        st.info(f"No '{selected_label}' streaks of more than 1 hole recorded yet.")
        return

    length_counts = pd.Series(lengths).value_counts().sort_index()
    length_counts = length_counts.reindex(range(2, max(lengths) + 1), fill_value=0)

    streak_fig = go.Figure()
    streak_fig.add_trace(go.Bar(
        x=list(length_counts.index),
        y=length_counts.values,
        marker_color="#2a78d6",
    ))
    streak_fig.update_layout(
        title=f"Distribution of '{selected_label}' Streak Lengths",
        xaxis_title="Streak Length (holes)",
        yaxis_title="Count",
        xaxis=dict(tickmode="linear", tick0=2, dtick=1),
    )
    streak_event = st.plotly_chart(
        streak_fig, use_container_width=True, on_select="rerun", selection_mode="points"
    )

    selected_points = streak_event.selection.points if streak_event.selection else []
    if not selected_points:
        st.caption("Click a bar above to list every round with a streak of that length.")
        return

    clicked_length = int(selected_points[0]["x"])
    holes = streaks["holes"]
    round_meta = streaks["round_meta"]

    matching_runs = [
        run for run in streaks["runs_by_category"][selected_label] if run["length"] == clicked_length
    ]
    matching_runs.sort(key=lambda r: round_meta.loc[r["round_id"], "date"], reverse=True)

    detail_rows = []
    for run in matching_runs:
        round_holes = holes[holes["round_id"] == run["round_id"]]
        segment = round_holes[
            (round_holes["hole_number"] >= run["start_hole"])
            & (round_holes["hole_number"] <= run["end_hole"])
        ]
        gross = int(segment["raw_score"].sum())
        to_par = gross - int(segment["par"].sum())
        meta = round_meta.loc[run["round_id"]]

        detail_rows.append({
            "Date": pd.Timestamp(meta["date"]).strftime("%d-%b-%y"),
            "Course": meta["course_name"],
            "Tee": meta["tee_color_played"],
            "Holes": f"{run['start_hole']}-{run['end_hole']}",
            "Gross Score": gross,
            "To Par": f"{to_par:+d}" if to_par != 0 else "E",
        })

    st.subheader(f"Rounds with a {clicked_length}-hole '{selected_label}' streak")
    detail_event = st.dataframe(
        pd.DataFrame(detail_rows),
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row-required",
    )

    detail_selected_idx = detail_event.selection.rows[0] if detail_event.selection.rows else 0
    selected_run = matching_runs[detail_selected_idx]

    round_holes = holes[holes["round_id"] == selected_run["round_id"]].sort_values("hole_number")
    meta = round_meta.loc[selected_run["round_id"]]

    st.subheader(
        f"Scorecard -- {meta['course_name']} ({meta['tee_color_played']}), "
        f"{pd.Timestamp(meta['date']).strftime('%d-%b-%y')}"
    )
    st.caption(
        f"Holes {selected_run['start_hole']}-{selected_run['end_hole']} (highlighted) "
        f"made up this {clicked_length}-hole '{selected_label}' streak."
    )
    _render_scorecard(round_holes, selected_run["start_hole"], selected_run["end_hole"])
