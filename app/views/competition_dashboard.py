import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.calculations.handicap_data import get_full_handicap_history
from app.calculations.knockouts import build_knockout_grid, stage_rank
from app.calculations.scoring import CATEGORY_ORDER, categorize_score
from app.calculations.streaks import STREAK_CATEGORIES, category_streaks
from app.views.table_components import expandable_rounds_table_html, round_detail_html
from database.queries import get_knockout_competitions, get_knockout_matches


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


def _render_stroke_play():
    """Render the Stroke Play sub-tab: performance specifically in rounds
    tagged with a competition_name (see database/queries.py --
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


def _format_handicap(index_val, playing_val) -> str:
    if pd.isna(index_val) or pd.isna(playing_val):
        return ""
    return f"{index_val:.1f} / {int(playing_val)}"


def _match_result_label(row) -> str:
    if row.is_bye:
        return "Bye"
    if row.won is None or pd.isna(row.won):
        return "-"
    return "Won" if row.won else "Lost"


def _render_knockout_grid(filtered: pd.DataFrame, competitions_df: pd.DataFrame):
    grid, row_labels = build_knockout_grid(filtered, competitions_df)
    if grid.empty:
        return

    display_df = grid.reset_index(drop=True).fillna("")
    display_df.insert(0, "Stage", [row_labels[d] for d in grid.index])
    st.dataframe(display_df, hide_index=True, width="stretch")


def _render_knockout_match_log(filtered: pd.DataFrame):
    sort_helper = filtered.assign(_stage_rank=filtered["stage"].map(stage_rank))
    sort_helper = sort_helper.sort_values(
        ["year", "competition_name", "_stage_rank"], ascending=[False, True, True]
    )

    rows = []
    for row in sort_helper.itertuples():
        opponents = row.opponent1_name or ""
        if pd.notna(row.opponent2_name) and row.opponent2_name:
            opponents += f" / {row.opponent2_name}"

        opponent_handicaps = [
            h for h in [
                _format_handicap(row.opponent1_handicap_index, row.opponent1_playing_handicap),
                _format_handicap(row.opponent2_handicap_index, row.opponent2_playing_handicap),
            ] if h
        ]

        rows.append({
            "Competition": row.competition_name,
            "Year": str(row.season_label) if pd.notna(row.season_label) else str(row.year),
            "Stage": row.stage,
            "Date": pd.Timestamp(row.match_date).strftime("%d-%b-%y") if pd.notna(row.match_date) else "TBC",
            "My HI / PH": _format_handicap(row.my_handicap_index, row.my_playing_handicap),
            "Partner": row.partner_name or "",
            "Partner HI / PH": _format_handicap(row.partner_handicap_index, row.partner_playing_handicap),
            "Opponent(s)": opponents,
            "Opponent HI / PH": " / ".join(opponent_handicaps),
            "Result": _match_result_label(row),
            "Margin": row.margin or "",
        })

    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _render_knockouts():
    """Render the Knockouts sub-tab: matchplay knockout competitions
    (Charlotte Cup, Barham Trophy, Parish Trophy, Parish Plate), shown as a
    Final-anchored grid -- one column per (competition, year) edition, one
    row per distance-from-final (see app/calculations/knockouts.py), so an
    edition with fewer rounds (a smaller draw, or an early exit) simply
    starts further down the table instead of misaligning with the Final row.
    """
    competitions_df = get_knockout_competitions()
    matches_df = get_knockout_matches()

    if matches_df.empty:
        st.info("No knockout matches recorded yet.")
        return

    year_options = sorted(matches_df["year"].unique().tolist(), reverse=True)
    competition_options = competitions_df["competition_name"].tolist()

    col1, col2 = st.columns(2)
    with col1:
        selected_years = st.multiselect(
            "Year", year_options, default=year_options, key="knockout_year_filter"
        )
    with col2:
        selected_competitions = st.multiselect(
            "Competition", competition_options, default=competition_options, key="knockout_competition_filter"
        )

    filtered = matches_df[
        matches_df["year"].isin(selected_years) & matches_df["competition_name"].isin(selected_competitions)
    ]

    if filtered.empty:
        st.warning("No knockout matches match the selected filter(s).")
        return

    _render_knockout_grid(filtered, competitions_df)

    st.markdown("**Match Details**")
    _render_knockout_match_log(filtered)


def render_competition_dashboard():
    """Render the Competition Dashboard tab: Stroke Play (Monthly Medal,
    Stableford, Club Champs, etc. -- see competition_name on golf_rounds)
    and Knockouts (Charlotte Cup, Barham/Parish Trophy, etc. -- matchplay,
    tracked separately in golf.knockout_matches since it doesn't produce a
    stroke-play score differential).
    """
    tab_stroke_play, tab_knockouts = st.tabs(["Stroke Play", "Knockouts"])

    with tab_stroke_play:
        _render_stroke_play()

    with tab_knockouts:
        _render_knockouts()
