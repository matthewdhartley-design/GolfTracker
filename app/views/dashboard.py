import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.calculations.whs import compute_handicap_trend
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


def _rounds_table_html(rated_df: pd.DataFrame) -> str:
    """Build an HTML table of rounds, most recent first, with a colored dot
    next to the score differential when that round currently counts toward
    the low (green) or high (red) handicap, and a yellow divider marking the
    boundary between the current 20-round window and everything older.
    """
    table_df = rated_df.sort_values("date", ascending=False).reset_index(drop=True)

    header = (
        "<tr>"
        "<th style='text-align:left;padding:4px 8px;'>Round ID</th>"
        "<th style='text-align:left;padding:4px 8px;'>Date</th>"
        "<th style='text-align:left;padding:4px 8px;'>Course</th>"
        "<th style='text-align:left;padding:4px 8px;'>Tee</th>"
        "<th style='text-align:right;padding:4px 8px;'>Score</th>"
        "<th style='text-align:right;padding:4px 8px;'>Score Differential</th>"
        "<th style='text-align:right;padding:4px 8px;'>Low Handicap</th>"
        "<th style='text-align:right;padding:4px 8px;'>High Handicap</th>"
        "</tr>"
    )

    rows = []
    for i, row in table_df.iterrows():
        if row["counts_toward_handicap"]:
            dot = " <span style='color:#0ca30c;'>&#9679;</span>"
        elif row["counts_toward_high_handicap"]:
            dot = " <span style='color:#d03b3b;'>&#9679;</span>"
        else:
            dot = ""

        date_str = pd.Timestamp(row["date"]).strftime("%d-%b-%y")
        row_style = "border-bottom:2px solid #eda100;" if i == 19 and len(table_df) > 20 else ""

        rows.append(
            f"<tr style='{row_style}'>"
            f"<td style='padding:4px 8px;'>{row['round_id']}</td>"
            f"<td style='padding:4px 8px;'>{date_str}</td>"
            f"<td style='padding:4px 8px;'>{row['course_name']}</td>"
            f"<td style='padding:4px 8px;'>{row['tee_color_played']}</td>"
            f"<td style='text-align:right;padding:4px 8px;'>{row['total_score']}</td>"
            f"<td style='text-align:right;padding:4px 8px;'>{row['score_differential']:.1f}{dot}</td>"
            f"<td style='text-align:right;padding:4px 8px;'>{row['whs_handicap_index']:.1f}</td>"
            f"<td style='text-align:right;padding:4px 8px;'>{row['high_handicap_index']:.1f}</td>"
            "</tr>"
        )

    return (
        "<div style='max-height:500px;overflow-y:auto;'>"
        "<table style='width:100%;border-collapse:collapse;font-size:0.9rem;'>"
        f"<thead>{header}</thead><tbody>{''.join(rows)}</tbody>"
        "</table></div>"
    )


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


def render_dashboard():
    """Render the Macro Trends tab."""
    rounds_df = get_macro_rounds()

    if rounds_df.empty:
        st.info("No rounds found yet. Log a round to see your macro trends.")
        return

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
            if st.button(label, use_container_width=True, key=f"zoom_btn_{key}"):
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
        st.plotly_chart(fig, use_container_width=True)

    st.markdown(_rounds_table_html(rated_df), unsafe_allow_html=True)
