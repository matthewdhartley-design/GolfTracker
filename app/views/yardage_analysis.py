import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.calculations.handicap_data import get_full_handicap_history
from app.calculations.yardage import yardage_moving_average


def render_yardage_analysis():
    """Render the Yardage Analysis tab: score-to-par vs. hole yardage across
    every recorded hole, smoothed with a 50-yard centered moving average.

    Uses net-double-bogey-capped scores (WHS Rule 3.1), same as the rest of
    the dashboard -- your original recorded scores are unchanged in the
    database.
    """
    _, all_holes = get_full_handicap_history()

    if all_holes.empty:
        st.info(
            "No rounds yet have both hole-by-hole scores and course hole-by-hole "
            "par/yardage data recorded, so there's nothing to analyze."
        )
        return

    course_options = sorted(all_holes["course_name"].dropna().unique().tolist())
    tee_options = sorted(all_holes["tee_color_played"].dropna().unique().tolist())
    year_options = sorted(pd.to_datetime(all_holes["date"]).dt.year.unique().tolist())

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        selected_courses = st.multiselect(
            "Course", course_options, default=course_options, key="yardage_analysis_course_filter"
        )
    with filter_col2:
        selected_tees = st.multiselect(
            "Tee", tee_options, default=tee_options, key="yardage_analysis_tee_filter"
        )
    with filter_col3:
        selected_years = st.multiselect(
            "Year", year_options, default=year_options, key="yardage_analysis_year_filter"
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

    window = st.slider("Moving average window (yards)", min_value=25, max_value=100, value=50, step=5)
    moving_avg = yardage_moving_average(all_holes, window=window)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=all_holes["yardage"],
        y=all_holes["to_par"],
        mode="markers",
        name="Individual Holes Played",
        marker=dict(size=6, symbol="x-thin", line=dict(width=1, color="#898781"), opacity=0.5),
    ))
    fig.add_trace(go.Scatter(
        x=moving_avg["yardage"],
        y=moving_avg["avg_to_par"],
        mode="lines",
        name=f"{window}yd Moving Average",
        line=dict(width=2, color="#2a78d6"),
    ))
    fig.update_layout(
        title=f"Score to Par vs. Hole Yardage ({window}-Yard Moving Average)",
        xaxis_title="Yardage",
        yaxis_title="Score to Par",
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
        margin=dict(b=100),
    )
    st.plotly_chart(fig, use_container_width=True)
