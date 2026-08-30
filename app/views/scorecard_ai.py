from datetime import date as date_cls

import pandas as pd
import streamlit as st

from app.calculations.scorecard_ai import analyze_scorecard_image
from database.queries import (
    create_round,
    find_round_by_course_and_date,
    get_known_course_tees,
    upsert_hole_details,
)


def render_scorecard_ai():
    """Render the Scorecard AI tab: upload a played round's scorecard photo,
    let Gemini read the hole-by-hole scores, review/correct them, then either
    attach them to a matching golf_rounds entry or create a new one.
    """
    st.write(
        "Upload a photo of a scorecard from a round you've played. It'll be read "
        "automatically -- review and correct anything before saving."
    )

    uploaded = st.file_uploader("Scorecard photo", type=["png", "jpg", "jpeg"])

    if uploaded is not None and st.button("Analyze"):
        with st.spinner("Reading scorecard..."):
            try:
                extraction = analyze_scorecard_image(uploaded.getvalue(), mime_type=uploaded.type)
            except Exception as e:
                st.error(f"Couldn't analyze the image: {e}")
            else:
                st.session_state["scorecard_ai_extraction"] = extraction.model_dump()
                st.session_state["scorecard_ai_image"] = uploaded.getvalue()

    extraction = st.session_state.get("scorecard_ai_extraction")
    if not extraction:
        return

    if st.session_state.get("scorecard_ai_image"):
        st.image(st.session_state["scorecard_ai_image"], caption="Uploaded scorecard", width=300)

    st.subheader("Review Extracted Data")

    known = get_known_course_tees()
    course_options = sorted(known["course_name"].unique().tolist())

    default_course = extraction["course_name"]
    course_index = course_options.index(default_course) if default_course in course_options else 0
    course_name = st.selectbox("Course", course_options, index=course_index)

    tee_options = sorted(known[known["course_name"] == course_name]["tee_color"].unique().tolist())
    default_tee = extraction.get("tee_color")
    tee_index = tee_options.index(default_tee) if default_tee in tee_options else 0
    tee_color = st.selectbox("Tee", tee_options, index=tee_index)

    extracted_date = extraction.get("date")
    try:
        parsed_date = pd.to_datetime(extracted_date).date() if extracted_date else date_cls.today()
    except (ValueError, TypeError):
        parsed_date = date_cls.today()
    round_date = st.date_input("Date", value=parsed_date)

    holes_df = pd.DataFrame(extraction["holes"])
    full_holes = pd.DataFrame({"hole_number": range(1, 19)})
    if not holes_df.empty:
        full_holes = full_holes.merge(holes_df, on="hole_number", how="left")
    else:
        full_holes["score"] = pd.NA
    full_holes = full_holes.rename(columns={"hole_number": "Hole", "score": "Score"})

    edited = st.data_editor(
        full_holes, hide_index=True, num_rows="fixed", disabled=["Hole"], width="stretch",
    )

    if edited["Score"].isna().any():
        st.warning("Some holes are missing a score -- fill them in before saving.")
        return

    total_score = int(edited["Score"].sum())
    st.metric("Total Score", total_score)

    match = find_round_by_course_and_date(course_name, round_date)
    holes = [{"hole_number": int(r.Hole), "score": int(r.Score)} for r in edited.itertuples()]

    if match:
        if match["total_score"] == total_score:
            st.success(f"Matches existing round #{match['round_id']} -- scores agree ({total_score}).")
        else:
            st.warning(
                f"Found round #{match['round_id']} on {round_date} at {course_name}, but its "
                f"stored total_score ({match['total_score']}) doesn't match the scorecard total "
                f"({total_score}). Check the extracted scores above, or the stored round, before saving."
            )
        if st.button("Save hole-by-hole scores to this round"):
            upsert_hole_details(match["round_id"], holes)
            st.success("Hole-by-hole scores saved.")
    else:
        st.info(f"No existing round found for {course_name} on {round_date}.")
        if st.button("Create new round and save scores"):
            round_id = create_round(round_date, course_name, tee_color, total_score)
            upsert_hole_details(round_id, holes)
            st.success(f"Created round #{round_id} and saved hole-by-hole scores.")
