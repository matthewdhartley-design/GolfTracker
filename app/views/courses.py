import plotly.graph_objects as go
import streamlit as st

from app.calculations.scoring import CATEGORY_ORDER, hole_score_distribution
from database.queries import get_courses_with_hole_score_data, get_hole_scores_with_par

_CATEGORY_COLORS = {
    "Birdie or Better": "#0ca30c",
    "Par": "#c3c2b7",
    "Bogey": "#eda100",
    "Double Bogey": "#eb6834",
    "Triple+ Bogey": "#d03b3b",
}


def render_course_analyzer():
    """Render the Course Analyzer tab: a stacked bar chart showing, for a
    single selected course, how every recorded round's score broke down
    (birdie or better / par / bogey / double / triple+) on each hole.
    """
    courses = get_courses_with_hole_score_data()

    if not courses:
        st.info(
            "No rounds yet have both hole-by-hole scores and course hole-by-hole "
            "par data recorded, so there's nothing to analyze."
        )
        return

    selected_course = st.selectbox("Course", courses)

    scores_df = get_hole_scores_with_par(selected_course)
    if scores_df.empty:
        st.info(f"No hole-level scoring data available for {selected_course}.")
        return

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
