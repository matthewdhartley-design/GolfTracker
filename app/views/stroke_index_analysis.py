import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.calculations.handicap_data import get_full_handicap_history


def render_stroke_index_analysis():
    """Render the Stroke Index Analysis tab: average score to par by hole
    stroke index (1-18), using net-double-bogey-capped scores (WHS Rule 3.1)
    -- your original recorded scores are unchanged in the database.
    """
    _, all_holes = get_full_handicap_history()

    if all_holes.empty:
        st.info(
            "No rounds yet have both hole-by-hole scores and course hole-by-hole "
            "par/stroke index data recorded, so there's nothing to analyze."
        )
        return

    course_options = sorted(all_holes["course_name"].dropna().unique().tolist())
    tee_options = sorted(all_holes["tee_color_played"].dropna().unique().tolist())
    year_options = sorted(pd.to_datetime(all_holes["date"]).dt.year.unique().tolist())

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        selected_courses = st.multiselect(
            "Course", course_options, default=course_options, key="stroke_index_course_filter"
        )
    with filter_col2:
        selected_tees = st.multiselect(
            "Tee", tee_options, default=tee_options, key="stroke_index_tee_filter"
        )
    with filter_col3:
        selected_years = st.multiselect(
            "Year", year_options, default=year_options, key="stroke_index_year_filter"
        )

    all_holes = all_holes[
        all_holes["course_name"].isin(selected_courses)
        & all_holes["tee_color_played"].isin(selected_tees)
        & pd.to_datetime(all_holes["date"]).dt.year.isin(selected_years)
    ]

    if all_holes.empty:
        st.info("No rounds match the selected filters.")
        return

    all_holes = all_holes.copy()
    all_holes["to_par"] = all_holes["capped_score"] - all_holes["par"]

    by_si = all_holes.groupby("stroke_index").agg(
        avg_to_par=("to_par", "mean"), count=("to_par", "size")
    ).reindex(range(1, 19))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=by_si.index,
        y=by_si["avg_to_par"],
        mode="lines+markers",
        line=dict(width=2, color="#2a78d6"),
        marker=dict(size=7),
        customdata=by_si["count"],
        hovertemplate="Stroke Index %{x}<br>Avg Score to Par: %{y:.2f}<br>Holes: %{customdata}<extra></extra>",
    ))
    fig.update_layout(
        title="Average Score to Par by Stroke Index",
        xaxis_title="Stroke Index",
        yaxis_title="Avg Score to Par",
        xaxis=dict(tickmode="linear", tick0=1, dtick=1),
        margin=dict(b=60),
    )
    st.plotly_chart(fig, width="stretch")
