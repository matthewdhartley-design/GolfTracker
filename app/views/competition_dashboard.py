import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.calculations.handicap_data import get_full_handicap_history
from app.calculations.scoring import CATEGORY_ORDER, categorize_score
from app.calculations.streaks import STREAK_CATEGORIES, category_streaks
from app.views.table_components import expandable_rounds_table_html, round_detail_html


def _best_worst_rows(comp_rated: pd.DataFrame, n: int, ascending: bool) -> list[dict]:
    subset = comp_rated.sort_values("score_differential", ascending=ascending).head(n)
    return [
        {
            "Date": pd.Timestamp(row.date).strftime("%d-%b-%y"),
            "Competition": row.competition_name,
            "Course": row.course_name,
            "Tee": row.tee_color_played,
            "Score": int(row.total_score),
            "Score Differential": row.score_differential,
        }
        for row in subset.itertuples()
    ]


def _longest_streaks(comp_holes: pd.DataFrame) -> list[dict]:
    """Longest streak achieved in a competition round for each category,
    same style as the All Time Records / Yearly Performance tabs, but
    scoped to just the currently-selected competition rounds.
    """
    holes = comp_holes.rename(columns={"score": "raw_score", "capped_score": "score"})
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


def _render_rounds_table(comp_rated: pd.DataFrame, comp_holes: pd.DataFrame, global_rated_df: pd.DataFrame):
    table_df = comp_rated.sort_values("date", ascending=False).reset_index(drop=True)

    round_details = {}
    if comp_holes is not None and not comp_holes.empty:
        for round_id, group in comp_holes.groupby("round_id"):
            round_details[int(round_id)] = round_detail_html(int(round_id), group, global_rated_df)

    columns = ["Date", "Competition", "Course", "Tee", "Score", "Score Differential"]
    rows = []
    for _, row in table_df.iterrows():
        rows.append({
            "_round_id": int(row["round_id"]),
            "Date": pd.Timestamp(row["date"]).strftime("%d-%b-%y"),
            "Competition": row["competition_name"],
            "Course": row["course_name"],
            "Tee": row["tee_color_played"],
            "Score": row["total_score"],
            "Score Differential": f"{row['score_differential']:.1f}",
        })

    expandable_rounds_table_html(columns, rows, round_details, table_id="competition_dashboard_rounds")


def render_competition_dashboard():
    """Render the Competition Dashboard tab: performance specifically in
    rounds tagged with a competition_name (see database/queries.py --
    ALTER TABLE golf.golf_rounds ADD COLUMN competition_name), benchmarked
    against casual (untagged) rounds over the same full history.
    """
    rated_df, capped_holes_df = get_full_handicap_history()

    if rated_df.empty or rated_df["competition_name"].notna().sum() == 0:
        st.info("No competition rounds tagged yet.")
        return

    competition_options = sorted(
        rated_df.loc[rated_df["competition_name"].notna(), "competition_name"].unique().tolist()
    )
    selected_competitions = st.multiselect(
        "Competition", competition_options, default=competition_options, key="competition_dashboard_filter"
    )

    comp_rated = rated_df[rated_df["competition_name"].isin(selected_competitions)]
    casual_rated = rated_df[rated_df["competition_name"].isna()]

    if comp_rated.empty:
        st.warning("No rounds match the selected competition(s).")
        return

    comp_round_ids = set(comp_rated["round_id"])
    comp_holes = (
        capped_holes_df[capped_holes_df["round_id"].isin(comp_round_ids)]
        if not capped_holes_df.empty else capped_holes_df
    )

    total_rounds = len(comp_rated)
    best_score = int(comp_rated["total_score"].min())
    avg_score = round(comp_rated["total_score"].mean(), 1)
    avg_diff_comp = comp_rated["score_differential"].mean()
    avg_diff_casual = casual_rated["score_differential"].mean() if not casual_rated.empty else None

    col1, col2, col3 = st.columns(3)
    col1.metric("Competition Rounds Played", total_rounds)
    col2.metric("Best Competition Score", best_score)
    col3.metric("Average Competition Score", avg_score)

    col4, col5 = st.columns(2)
    col4.metric("Avg Competition Score Differential", round(avg_diff_comp, 1))
    if avg_diff_casual is not None:
        delta = avg_diff_comp - avg_diff_casual
        col5.metric(
            "Vs. Casual Rounds",
            round(avg_diff_casual, 1),
            delta=f"{delta:+.1f}",
            delta_color="inverse",
            help="Average score differential in casual (non-competition) rounds, for comparison. "
                 "The delta is how much higher/lower your competition average is (lower is better).",
        )

    st.markdown("**Performance by Competition**")
    by_comp = comp_rated.groupby("competition_name").agg(
        Rounds=("round_id", "count"),
        Avg_Score=("total_score", "mean"),
        Best_Score=("total_score", "min"),
        Worst_Score=("total_score", "max"),
        Avg_Differential=("score_differential", "mean"),
    ).reset_index().rename(columns={
        "competition_name": "Competition",
        "Avg_Score": "Avg Score",
        "Best_Score": "Best Score",
        "Worst_Score": "Worst Score",
        "Avg_Differential": "Avg Differential",
    })
    by_comp["Avg Score"] = by_comp["Avg Score"].round(1)
    by_comp["Avg Differential"] = by_comp["Avg Differential"].round(1)
    by_comp = by_comp.sort_values("Rounds", ascending=False)
    st.dataframe(by_comp, hide_index=True, width="stretch")

    st.markdown("**Score Differential Over Time**")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=pd.to_datetime(comp_rated["date"]),
        y=comp_rated["score_differential"],
        mode="markers",
        marker=dict(size=9, color="#2a78d6"),
        customdata=comp_rated[["competition_name", "course_name"]],
        hovertemplate="%{customdata[0]}<br>%{customdata[1]}<br>Differential: %{y:.1f}<extra></extra>",
        name="Competition Rounds",
    ))
    fig.update_layout(xaxis_title="Date", yaxis_title="Score Differential", margin=dict(b=40))
    st.plotly_chart(fig, width="stretch")

    if not comp_holes.empty:
        holes = comp_holes.rename(columns={"score": "raw_score", "capped_score": "score"})
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

        st.markdown("**Longest Streaks in Competition Rounds**")
        st.dataframe(pd.DataFrame(_longest_streaks(comp_holes)), hide_index=True, width="stretch")

    col_best, col_worst = st.columns(2)
    with col_best:
        st.markdown("**5 Best Competition Rounds**")
        st.dataframe(pd.DataFrame(_best_worst_rows(comp_rated, 5, ascending=True)), hide_index=True, width="stretch")
    with col_worst:
        st.markdown("**5 Worst Competition Rounds**")
        st.dataframe(pd.DataFrame(_best_worst_rows(comp_rated, 5, ascending=False)), hide_index=True, width="stretch")

    st.markdown("**All Competition Rounds**")
    _render_rounds_table(comp_rated, comp_holes, rated_df)
