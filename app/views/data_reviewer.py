import pandas as pd
import streamlit as st

from database.queries import (
    get_hole_info,
    get_incomplete_hole_data,
    get_rounds_with_hole_counts,
    upsert_hole_info,
)


_COMPLETENESS_OPTIONS = {
    "All": None,
    "Complete (18/18)": lambda s: s >= 18,
    "Incomplete (1-17)": lambda s: (s > 0) & (s < 18),
    "None (0/18)": lambda s: s == 0,
}


def _render_rounds_overview():
    rounds_df = get_rounds_with_hole_counts()

    if rounds_df.empty:
        st.info("No rounds found yet.")
        return

    total_rounds = len(rounds_df)
    with_any_holes = (rounds_df["hole_scores_recorded"] > 0).sum()
    with_full_18 = (rounds_df["hole_scores_recorded"] >= 18).sum()

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Rounds", total_rounds)
    col2.metric("Rounds With Any Hole Detail", with_any_holes)
    col3.metric("Rounds With Full 18 Holes", with_full_18)

    course_options = sorted(rounds_df["course_name"].dropna().unique().tolist())
    tee_options = sorted(rounds_df["tee_color_played"].dropna().unique().tolist())

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        selected_courses = st.multiselect(
            "Course", course_options, default=course_options, key="data_reviewer_course_filter"
        )
    with filter_col2:
        selected_tees = st.multiselect(
            "Tee", tee_options, default=tee_options, key="data_reviewer_tee_filter"
        )
    with filter_col3:
        selected_completeness = st.selectbox(
            "Hole Scores Recorded", list(_COMPLETENESS_OPTIONS.keys()), key="data_reviewer_completeness_filter"
        )

    filtered_df = rounds_df[
        rounds_df["course_name"].isin(selected_courses) & rounds_df["tee_color_played"].isin(selected_tees)
    ]
    completeness_predicate = _COMPLETENESS_OPTIONS[selected_completeness]
    if completeness_predicate is not None:
        filtered_df = filtered_df[completeness_predicate(filtered_df["hole_scores_recorded"])]

    if filtered_df.empty:
        st.info("No rounds match the selected filters.")
        return

    table_df = filtered_df.sort_values("date", ascending=False).copy()
    table_df["date"] = pd.to_datetime(table_df["date"]).dt.strftime("%d-%b-%y")
    table_df["hole_scores_recorded"] = table_df["hole_scores_recorded"].astype(str) + " / 18"
    table_df = table_df.rename(columns={
        "round_id": "Round ID",
        "date": "Date",
        "course_name": "Course",
        "tee_color_played": "Tee",
        "total_score": "Score",
        "hole_scores_recorded": "Hole Scores Recorded",
    })

    st.dataframe(table_df, use_container_width=True, hide_index=True)


def _render_scorecards():
    hole_info = get_hole_info()

    if hole_info.empty:
        st.info("No hole-by-hole course data recorded yet.")
        return

    hole_info["course_tee"] = hole_info["course_name"] + " (" + hole_info["tee_color"] + ")"
    options = sorted(hole_info["course_tee"].unique().tolist())
    selected = st.selectbox("Course / Tee", options)

    scorecard = hole_info[hole_info["course_tee"] == selected].sort_values("hole_number")

    hole_cols = [str(h) for h in scorecard["hole_number"]] + ["Total"]
    par_row = scorecard["par"].tolist() + [scorecard["par"].sum()]
    yardage_row = scorecard["yardage"].tolist() + [scorecard["yardage"].sum()]
    stroke_index_row = scorecard["stroke_index"].tolist() + [""]

    scorecard_wide = pd.DataFrame(
        [par_row, yardage_row, stroke_index_row],
        index=pd.Index(["Par", "Yardage", "Stroke Index"], name="Hole"),
        columns=hole_cols,
    ).astype(str)
    st.dataframe(scorecard_wide, use_container_width=True)

    st.subheader("Courses Missing Hole-by-Hole Data")
    st.caption(
        "Every course/tee from golf_course_tees that doesn't yet have a complete "
        "18-hole entry in golf_hole_info -- send over the missing scorecards to fill these in."
    )

    incomplete = get_incomplete_hole_data()
    if incomplete.empty:
        st.success("Every course/tee has a complete 18-hole data set.")
    else:
        incomplete_display = incomplete.copy()
        incomplete_display["hole_count"] = incomplete_display["hole_count"].astype(str) + " / 18"
        incomplete_display = incomplete_display.rename(columns={
            "course_name": "Course",
            "tee_color": "Tee",
            "hole_count": "Holes Recorded",
        })
        st.warning(f"{len(incomplete_display)} course/tee row(s) need hole-by-hole data.")
        st.dataframe(incomplete_display, use_container_width=True, hide_index=True)

        st.subheader("Add Hole-by-Hole Data")
        _render_hole_entry_form(incomplete)


def _render_hole_entry_form(incomplete: pd.DataFrame):
    incomplete = incomplete.copy()
    incomplete["label"] = (
        incomplete["course_name"] + " (" + incomplete["tee_color"] + ") - "
        + incomplete["hole_count"].astype(str) + "/18"
    )
    selected_label = st.selectbox("Course / tee to enter", incomplete["label"].tolist())
    selected_row = incomplete[incomplete["label"] == selected_label].iloc[0]
    course_name, tee_color = selected_row["course_name"], selected_row["tee_color"]

    default_editor_df = pd.DataFrame({
        "Hole": list(range(1, 19)),
        "Par": [4] * 18,
        "Yardage": [0] * 18,
        "Stroke Index": list(range(1, 19)),
    })

    with st.form(key=f"hole_entry_form_{course_name}_{tee_color}"):
        edited = st.data_editor(
            default_editor_df,
            hide_index=True,
            num_rows="fixed",
            disabled=["Hole"],
            use_container_width=True,
        )
        submitted = st.form_submit_button("Submit")

    if not submitted:
        return

    pars = edited["Par"].tolist()
    yardages = edited["Yardage"].tolist()
    stroke_indices = edited["Stroke Index"].tolist()

    errors = []
    if sorted(stroke_indices) != list(range(1, 19)):
        errors.append("Stroke Index must use each number 1-18 exactly once.")
    if any(p <= 0 for p in pars):
        errors.append("All Par values must be greater than 0.")
    if any(y <= 0 for y in yardages):
        errors.append("All Yardage values must be greater than 0.")

    if errors:
        for error in errors:
            st.error(error)
        return

    holes = [
        {"hole_number": i + 1, "par": pars[i], "yardage": yardages[i], "stroke_index": stroke_indices[i]}
        for i in range(18)
    ]
    upsert_hole_info(course_name, tee_color, holes)
    st.success(f"Saved hole-by-hole data for {course_name} ({tee_color}).")
    st.rerun()


def render_data_reviewer():
    """Render the Data Reviewer tab."""
    tab_rounds, tab_scorecards = st.tabs(["Rounds Overview", "Scorecards"])

    with tab_rounds:
        _render_rounds_overview()

    with tab_scorecards:
        _render_scorecards()
