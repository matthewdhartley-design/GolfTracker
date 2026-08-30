import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.calculations.handicap_data import get_full_handicap_history
from app.calculations.whs import compute_handicap_trend
from app.views.course_preview import render_course_preview
from app.views.scoring_trends import render_scoring_trends
from app.views.table_components import expandable_rounds_table_html, round_detail_html
from database.queries import get_all_hole_scores_with_par, get_macro_rounds

_X_AXIS_OPTIONS = {"Date": "date", "Round ID": "round_id"}

_ZOOM_PRESETS = [
    ("Last 20 Rounds", "r20"),
    ("Last 40 Rounds", "r40"),
    ("Last 3 Months", "m3"),
    ("Last 6 Months", "m6"),
    ("Last 12 Months", "m12"),
]
_ZOOM_MONTHS = {"m3": 3, "m6": 6, "m12": 12}

# CCC's own rules: any CCC competition round counts toward the "5 qualifying
# competition rounds in the last 12 months" entry requirement for anything
# else (e.g. Club Champs, Captains Day) -- including Monthly Medal/Monthly
# Stableford. But once you've fallen below the requirement, only Monthly
# Medal/Monthly Stableford rounds are open-entry enough to rebuild it back
# up -- the other competitions require already having 5 to enter.
_MONTHLY_COMPETITIONS = {"Monthly Medal", "Monthly Stableford"}
_QUALIFYING_ROUNDS_REQUIRED = 5


def _ccc_competition_eligibility(full_rounds_df: pd.DataFrame) -> dict:
    """How many CCC competition rounds have been played in the trailing 12
    months, and -- if that currently meets the 5-round entry requirement --
    the date the count will drop below 5 again if no further rounds are
    played.

    Each qualifying round "expires" (drops out of the trailing-12-month
    window) 12 months after it was played. Sorting those expiry dates
    ascending, the count only first falls below the requirement once
    (N - (required - 1)) of them have expired -- i.e. the date returned is
    the (N - required + 1)'th soonest expiry date.
    """
    qualifying = full_rounds_df[
        (full_rounds_df["course_name"] == "CCC") & full_rounds_df["competition_name"].notna()
    ]

    today = pd.Timestamp.today().normalize()
    cutoff = today - pd.DateOffset(months=12)
    recent = qualifying[pd.to_datetime(qualifying["date"]) >= cutoff]
    count = len(recent)

    result = {"count": count, "required": _QUALIFYING_ROUNDS_REQUIRED, "drop_below_date": None}
    if count >= _QUALIFYING_ROUNDS_REQUIRED:
        expiry_dates = sorted(pd.to_datetime(recent["date"]) + pd.DateOffset(months=12))
        idx = count - _QUALIFYING_ROUNDS_REQUIRED
        result["drop_below_date"] = expiry_dates[idx]
    return result


def _rounds_table_component(rated_df: pd.DataFrame, capped_holes_df: pd.DataFrame, global_rated_df: pd.DataFrame):
    """Render the rounds table, most recent first, with a colored dot next
    to the score differential when that round currently counts toward the
    low (green) or high (red) handicap, and a yellow divider marking the
    boundary between the current 20-round window and everything older.

    Clicking a row splits the table and shows that round's scorecard,
    per-round streak callouts, and ranking stats in the gap between it and
    the next row.
    """
    table_df = rated_df.sort_values("date", ascending=False).reset_index(drop=True)

    round_details = {}
    if capped_holes_df is not None and not capped_holes_df.empty:
        for round_id, group in capped_holes_df.groupby("round_id"):
            round_details[int(round_id)] = round_detail_html(int(round_id), group, global_rated_df)

    columns = ["Round ID", "Date", "Course", "Tee", "Score", "Score Differential", "Low Handicap", "High Handicap"]
    rows = []
    for i, row in table_df.iterrows():
        if row["counts_toward_handicap"]:
            dot = " <span style='color:#0ca30c;'>&#9679;</span>"
        elif row["counts_toward_high_handicap"]:
            dot = " <span style='color:#d03b3b;'>&#9679;</span>"
        else:
            dot = ""

        rows.append({
            "_round_id": int(row["round_id"]),
            "_row_style": "border-bottom:2px solid #eda100;" if i == 19 and len(table_df) > 20 else "",
            "Round ID": int(row["round_id"]),
            "Date": pd.Timestamp(row["date"]).strftime("%d-%b-%y"),
            "Course": row["course_name"],
            "Tee": row["tee_color_played"],
            "Score": row["total_score"],
            "Score Differential": f"{row['score_differential']:.1f}{dot}",
            "Low Handicap": f"{row['whs_handicap_index']:.1f}",
            "High Handicap": f"{row['high_handicap_index']:.1f}",
        })

    expandable_rounds_table_html(columns, rows, round_details, table_id="macro_trends_rounds")


def _zoom_x_range(rated_df: pd.DataFrame, x_col: str, zoom: str | None):
    """Return (x_min, x_max) for the given zoom preset and x-axis column,
    or None to use the full history range.
    """
    if zoom in ("r20", "r40"):
        n = min(20 if zoom == "r20" else 40, len(rated_df))
        x_min, x_max = rated_df.iloc[-n][x_col], rated_df.iloc[-1][x_col]
    elif zoom in _ZOOM_MONTHS:
        date_series = pd.to_datetime(rated_df["date"])
        max_date = date_series.max()
        cutoff = max_date - pd.DateOffset(months=_ZOOM_MONTHS[zoom])
        if x_col == "date":
            x_min, x_max = cutoff, max_date
        else:
            subset = rated_df[date_series >= cutoff]
            x_min = subset["round_id"].min() if not subset.empty else rated_df["round_id"].min()
            x_max = rated_df["round_id"].max()
    else:
        return None

    if x_col == "date":
        x_min, x_max = pd.Timestamp(x_min), pd.Timestamp(x_max)
    return x_min, x_max


def _render_competition_eligibility(full_rounds_df: pd.DataFrame):
    """Show whether the CCC "5 qualifying competition rounds in the last 12
    months" entry requirement is currently met, and if so, the date it'll
    stop being met (assuming no further qualifying rounds are played).
    Uses the full, unfiltered round history -- independent of the course/
    tee/year filters below, since eligibility is a real-world fact, not a
    view of the chart.
    """
    eligibility = _ccc_competition_eligibility(full_rounds_df)
    count, required = eligibility["count"], eligibility["required"]

    col1, col2 = st.columns(2)
    col1.metric(
        "CCC Qualifying Competition Rounds (Last 12mo)",
        f"{count} / {required}",
        help="Any CCC competition round in the last 12 months, including Monthly Medal/Monthly "
             "Stableford -- the requirement to enter anything else (Club Champs, Captains Day, etc.).",
    )
    if eligibility["drop_below_date"] is not None:
        col2.metric(
            "Qualifying Drops Below 5 On",
            eligibility["drop_below_date"].strftime("%d-%b-%y"),
            help="The date your oldest currently-counting round ages out of the trailing 12-month "
                 "window, assuming no new competition rounds are played before then.",
        )
    else:
        col2.warning(
            f"Not enough qualifying rounds -- need {required - count} more. "
            "Only Monthly Medal/Monthly Stableford rounds are open-entry enough to rebuild this "
            "from below the requirement."
        )


def _render_trends():
    """Render the Trends sub-tab (the original Macro Trends content)."""
    rounds_df = get_macro_rounds()

    if rounds_df.empty:
        st.info("No rounds found yet. Log a round to see your macro trends.")
        return

    _render_competition_eligibility(rounds_df)

    course_options = sorted(rounds_df["course_name"].dropna().unique().tolist())
    tee_options = sorted(rounds_df["tee_color_played"].dropna().unique().tolist())
    year_options = sorted(pd.to_datetime(rounds_df["date"]).dt.year.unique().tolist())

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        selected_courses = st.multiselect(
            "Course", course_options, default=course_options, key="macro_trends_course_filter"
        )
    with filter_col2:
        selected_tees = st.multiselect(
            "Tee", tee_options, default=tee_options, key="macro_trends_tee_filter"
        )
    with filter_col3:
        selected_years = st.multiselect(
            "Year", year_options, default=year_options, key="macro_trends_year_filter"
        )

    # Filtering (not just re-plotting) the underlying rounds so every rolling
    # WHS/High Handicap calculation below recomputes as if only the selected
    # course/tee/year combinations were ever played.
    rounds_df = rounds_df[
        rounds_df["course_name"].isin(selected_courses)
        & rounds_df["tee_color_played"].isin(selected_tees)
        & pd.to_datetime(rounds_df["date"]).dt.year.isin(selected_years)
    ]

    if rounds_df.empty:
        st.warning("No rounds match the selected filters.")
        return

    # course_rating/slope_rating of exactly 0 is this project's placeholder sentinel for
    # "not yet rated" (e.g. a brand-new tee with no real course rating supplied yet) --
    # treat it the same as missing/null, since 113/0 in the WHS differential formula
    # produces inf and corrupts the rolling handicap average for every round that follows
    # it into the 20-round window.
    rated_df = rounds_df[
        rounds_df["course_rating"].notna() & (rounds_df["course_rating"] != 0)
        & rounds_df["slope_rating"].notna() & (rounds_df["slope_rating"] != 0)
        & ~rounds_df["excluded_from_handicap"]
    ].sort_values("date")

    if not rated_df.empty:
        hole_df = get_all_hole_scores_with_par()
        hole_df = hole_df[hole_df["round_id"].isin(rated_df["round_id"])]
        rated_df, capped_holes_df = compute_handicap_trend(rated_df, hole_df)

    total_rounds = len(rounds_df)
    best_score = rounds_df["total_score"].min()
    current_handicap = rated_df.iloc[-1]["whs_handicap_index"] if not rated_df.empty else None

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Rounds Played", total_rounds)
    col2.metric("Best Score", best_score)
    col3.metric(
        "Current Handicap",
        f"{current_handicap:.1f}" if pd.notnull(current_handicap) else "N/A",
    )

    if rated_df.empty:
        st.warning("No course rating/slope data available yet to calculate handicap.")
        return

    x_axis_label = st.radio(
        "X-axis", options=list(_X_AXIS_OPTIONS.keys()), horizontal=True, key="macro_trends_x_axis"
    )
    x_col = _X_AXIS_OPTIONS[x_axis_label]

    # Reserve the layout now so buttons render to the right of the chart, but
    # populate the buttons first so a click updates session_state before the
    # figure/range below is computed in this same script run.
    chart_col, button_col = st.columns([5, 1])
    with button_col:
        st.write("Zoom to:")
        for label, key in _ZOOM_PRESETS:
            if st.button(label, width="stretch", key=f"zoom_btn_{key}"):
                st.session_state["macro_trends_zoom"] = key

    low_counting = rated_df[rated_df["counts_toward_handicap"]]
    high_counting = rated_df[rated_df["counts_toward_high_handicap"]]
    excluded = rated_df[
        ~rated_df["counts_toward_handicap"] & ~rated_df["counts_toward_high_handicap"]
    ]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=excluded[x_col],
        y=excluded["score_differential"],
        mode="markers",
        name="Score Differential",
        marker=dict(size=9, symbol="x-thin", line=dict(width=1, color="#898781")),
    ))
    fig.add_trace(go.Scatter(
        x=low_counting[x_col],
        y=low_counting["score_differential"],
        mode="markers",
        name="Counts Toward Low Handicap",
        marker=dict(size=9, symbol="x-thin", line=dict(width=1, color="#0ca30c")),
    ))
    fig.add_trace(go.Scatter(
        x=high_counting[x_col],
        y=high_counting["score_differential"],
        mode="markers",
        name="Counts Toward High Handicap",
        marker=dict(size=9, symbol="x-thin", line=dict(width=1, color="#d03b3b")),
    ))
    fig.add_trace(go.Scatter(
        x=rated_df[x_col],
        y=rated_df["counting_low"],
        mode="lines",
        name="Low Handicap - Lowest Counting Differential",
        line=dict(width=1, dash="dot", color="#6da7ec"),
        opacity=0.8,
    ))
    fig.add_trace(go.Scatter(
        x=rated_df[x_col],
        y=rated_df["counting_high"],
        mode="lines",
        name="Low Handicap - Highest Counting Differential",
        line=dict(width=1, dash="dot", color="#6da7ec"),
        opacity=0.8,
    ))
    fig.add_trace(go.Scatter(
        x=rated_df[x_col],
        y=rated_df["whs_handicap_index"],
        mode="lines",
        name="WHS Handicap Index",
        line=dict(width=2, color="#2a78d6"),
    ))
    fig.add_trace(go.Scatter(
        x=rated_df[x_col],
        y=rated_df["high_counting_low"],
        mode="lines",
        name="High Handicap - Lowest Counting Differential",
        line=dict(width=1, dash="dot", color="#d03b3b"),
        opacity=0.5,
    ))
    fig.add_trace(go.Scatter(
        x=rated_df[x_col],
        y=rated_df["high_counting_high"],
        mode="lines",
        name="High Handicap - Highest Counting Differential",
        line=dict(width=1, dash="dot", color="#d03b3b"),
        opacity=0.5,
    ))
    fig.add_trace(go.Scatter(
        x=rated_df[x_col],
        y=rated_df["high_handicap_index"],
        mode="lines",
        name="High Handicap Index",
        line=dict(width=2, color="#d03b3b"),
    ))

    if len(rated_df) >= 20:
        next_to_fall_off = rated_df.iloc[-20]
        fall_off_x = next_to_fall_off[x_col]
        if x_col == "date":
            fall_off_x = pd.Timestamp(fall_off_x)
        fig.add_vline(
            x=fall_off_x,
            line_width=1,
            line_dash="dash",
            line_color="#898781",
            opacity=0.7,
            annotation_text=f"Next round to fall off ({next_to_fall_off['score_differential']:.1f})",
            annotation_position="top",
        )

    x_min, x_max = rated_df[x_col].min(), rated_df[x_col].max()
    if x_col == "date":
        x_min, x_max = pd.Timestamp(x_min), pd.Timestamp(x_max)

    zoom = st.session_state.get("macro_trends_zoom")
    zoom_range = _zoom_x_range(rated_df, x_col, zoom)
    if zoom_range is not None:
        x_min, x_max = zoom_range

    fig.update_layout(
        title="Handicap Over Time",
        xaxis_title=x_axis_label,
        yaxis_title="Handicap",
        xaxis=dict(range=[x_min, x_max]),
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
        margin=dict(b=100),
    )

    with chart_col:
        st.plotly_chart(fig, width="stretch")

    global_rated_df, _ = get_full_handicap_history()
    _rounds_table_component(rated_df, capped_holes_df, global_rated_df)


def render_dashboard():
    """Render the Macro Trends tab."""
    tab_trends, tab_course_preview, tab_scoring_trends = st.tabs(
        ["Trends", "Course Preview", "Scoring Trends"]
    )

    with tab_trends:
        _render_trends()

    with tab_course_preview:
        render_course_preview()

    with tab_scoring_trends:
        render_scoring_trends()
