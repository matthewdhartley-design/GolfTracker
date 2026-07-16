import sys
from pathlib import Path

# Streamlit only puts this script's own folder on sys.path, so add the
# project root explicitly to make the `app` and `database` packages importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from app.views.courses import render_course_analyzer
from app.views.dashboard import render_dashboard
from app.views.data_reviewer import render_data_reviewer
from app.views.scorecard_ai import render_scorecard_ai
from app.views.stroke_index_analysis import render_stroke_index_analysis
from app.views.yardage_analysis import render_yardage_analysis

st.set_page_config(page_title="Golf Analytics", layout="wide")

st.title("Golf Analytics")

tab_macro, tab_courses, tab_scorecard, tab_data_reviewer, tab_yardage, tab_stroke_index = st.tabs(
    ["Macro Trends", "Course Analyzer", "Scorecard AI", "Data Reviewer", "Yardage Analysis", "Stroke Index Analysis"]
)

with tab_macro:
    render_dashboard()

with tab_courses:
    render_course_analyzer()

with tab_scorecard:
    render_scorecard_ai()

with tab_data_reviewer:
    render_data_reviewer()

with tab_yardage:
    render_yardage_analysis()

with tab_stroke_index:
    render_stroke_index_analysis()
