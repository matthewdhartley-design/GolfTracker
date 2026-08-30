import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.calculations.handicap_data import get_full_handicap_history
from app.calculations.scoring import CATEGORY_ORDER, round_score_distribution

_CATEGORY_COLORS = {
    "Birdie or Better": "#0ca30c",
    "Par": "#c3c2b7",
    "Bogey": "#eda100",
    "Double Bogey": "#eb6834",
    "Triple+ Bogey": "#d03b3b",
}

_WINDOW_PRESETS = [
    ("Last 20 Rounds", "r20"),
    ("Last 40 Rounds", "r40"),
    ("Last 3 Months", "m3"),
    ("Last 6 Months", "m6"),
    ("Last 12 Months", "m12"),
    ("All Time", "all"),
]
_WINDOW_MONTHS = {"m3": 3, "m6": 6, "m12": 12}


def _filter_rated_by_window(rated_df: pd.DataFrame, window: str) -> pd.DataFrame:
    """Filter a date-sorted rated_df down to whole rounds within the given
    window -- same "Zoom to" preset semantics used on the Handicap Over Time
    chart and Course Preview (Last 20/40 Rounds, Last 3/6/12 Months), plus
    "all" for the full history unfiltered.
    """
    if window == "all":
        return rated_df
    if window in ("r20", "r40"):
        n = min(20 if window == "r20" else 40, len(rated_df))
        return rated_df.tail(n)
    max_date = pd.to_datetime(rated_df["date"]).max()
    cutoff = max_date - pd.DateOffset(months=_WINDOW_MONTHS[window])
    return rated_df[pd.to_datetime(rated_df["date"]) >= cutoff]


def _stats_table(rated_df: pd.DataFrame, plot_df: pd.DataFrame, current_handicap: float) -> pd.DataFrame:
    """One row per stat, one column per window preset, cells formatted as
    'N (P%)' -- count of rounds meeting the stat's condition, and what
    percentage of that window's rounds that represents.

    The handicap-based stats are computed against rated_df (every round
    with a score differential); the front/back comparison stats are
    computed against plot_df (only rounds with full front-and-back 9
    hole-level data -- a stricter subset), so "Last 20 Rounds" etc. can mean
    a slightly different set of rounds between the two groups of stats.
    """
    def _fmt(count: int, total: int) -> str:
        pct = round(100 * count / total) if total else 0
        return f"{count} ({pct}%)"

    row_defs = [
        (f"Rounds Below Current HCP ({current_handicap:.1f})",
         rated_df, lambda df: df["score_differential"] < current_handicap),
        ("Rounds Below 20 HCP", rated_df, lambda df: df["score_differential"] < 20),
        ("Rounds Below 25 HCP", rated_df, lambda df: df["score_differential"] < 25),
        ("Front 9 Better Than Back", plot_df, lambda df: df["front"] < df["back"]),
        ("Back 9 Better Than Front", plot_df, lambda df: df["back"] < df["front"]),
        ("Front 9 = Back 9", plot_df, lambda df: df["front"] == df["back"]),
    ]

    columns = {}
    for label, key in _WINDOW_PRESETS:
        col = {}
        for row_label, source_df, condition in row_defs:
            subset = _filter_rated_by_window(source_df, key)
            total = len(subset)
            count = int(condition(subset).sum()) if total else 0
            col[row_label] = _fmt(count, total)
        columns[label] = col

    labels = [label for label, _ in _WINDOW_PRESETS]
    row_labels = [r[0] for r in row_defs]
    return pd.DataFrame(columns)[labels].loc[row_labels]


def render_scoring_trends():
    """Render the Scoring Trends sub-tab: a rolling average of how many
    holes per round fall into each scoring category (birdie or better, par,
    bogey, double bogey, triple+ bogey), stacked so the total at any point
    always sums to 18 -- every hole in a round belongs to exactly one
    category, and averaging category counts across rounds preserves that.

    Uses net-double-bogey-capped scores (WHS Rule 3.1), same convention as
    the rest of this app.
    """
    rated_df, capped_holes_df = get_full_handicap_history()

    if capped_holes_df.empty:
        st.info("No rounds yet have both hole-by-hole scores and course hole-by-hole par data recorded.")
        return

    holes = capped_holes_df.rename(columns={"score": "raw_score", "capped_score": "score"})

    window = st.slider(
        "Rolling average window (rounds)", min_value=1, max_value=20, value=10, step=1,
        key="scoring_trends_window",
    )

    round_meta = (
        holes[["round_id", "date", "course_name"]].drop_duplicates().sort_values("date").reset_index(drop=True)
    )
    counts = round_score_distribution(holes).reindex(round_meta["round_id"])
    counts.index = pd.to_datetime(round_meta["date"])

    rolling = counts.rolling(window=window, min_periods=1).mean()

    fig = go.Figure()
    for category in CATEGORY_ORDER:
        fig.add_trace(go.Scatter(
            x=rolling.index,
            y=rolling[category],
            mode="lines",
            name=category,
            stackgroup="one",
            line=dict(width=0.5, color=_CATEGORY_COLORS[category]),
        ))
    fig.update_layout(
        title=f"Rolling {window}-Round Average Score Distribution",
        xaxis_title="Date",
        yaxis_title="Avg Holes per Category",
        yaxis=dict(range=[0, 18]),
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, traceorder="reversed"),
        margin=dict(b=100),
    )
    st.plotly_chart(fig, width="stretch")

    current_handicap = rated_df.iloc[-1]["whs_handicap_index"] if not rated_df.empty else None
    _render_front_back_scatter(holes, round_meta, rated_df, current_handicap)


def _render_front_back_scatter(
    holes: pd.DataFrame, round_meta: pd.DataFrame, rated_df: pd.DataFrame, current_handicap: float | None
):
    """Scatter of front 9 score-to-par (x) vs back 9 score-to-par (y), one
    point per round, with the 5 most recent rounds highlighted. Uses the
    same net-double-bogey-capped scores as the rest of this tab.
    """
    holes = holes.copy()
    holes["to_par"] = holes["score"] - holes["par"]
    holes["half"] = holes["hole_number"].apply(lambda h: "front" if h <= 9 else "back")

    half_sums = holes.groupby(["round_id", "half"])["to_par"].sum().unstack()
    # Only plot rounds with both halves present (18 holes) -- half_sums has
    # NaN for a round missing either half, and those aren't meaningfully
    # comparable front-vs-back.
    half_sums = half_sums.dropna(subset=["front", "back"])

    meta = round_meta.set_index("round_id")
    plot_df = half_sums.join(meta).sort_values("date")

    if plot_df.empty:
        st.info("No rounds with both a front and back 9 recorded yet.")
        return

    recent_ids = set(plot_df.tail(5).index)
    older = plot_df[~plot_df.index.isin(recent_ids)]
    recent = plot_df[plot_df.index.isin(recent_ids)]

    # Anchored at the origin (0, 0) by default so the plot is always a
    # perfect square, but extends below 0 if a half is ever actually under
    # par -- never clip a real data point just to keep the origin fixed.
    axis_min = min(0, plot_df["front"].min(), plot_df["back"].min())
    axis_max = max(plot_df["front"].max(), plot_df["back"].max())

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=[axis_min, axis_max],
        y=[axis_min, axis_max],
        mode="lines",
        name="Even (Front = Back)",
        line=dict(width=1, dash="dash", color="#898781"),
        hoverinfo="skip",
    ))
    if current_handicap is not None:
        # "On handicap" line: every point where front-to-par + back-to-par
        # equals your current Handicap Index (a round played exactly to
        # your handicap, ignoring course rating/slope for this cross-course
        # view). Clipped to whatever segment of x + y = H actually falls
        # inside the square axis range.
        h = current_handicap
        x1 = max(axis_min, h - axis_max)
        x2 = min(axis_max, h - axis_min)
        if x1 <= x2:
            fig2.add_trace(go.Scatter(
                x=[x1, x2],
                y=[h - x1, h - x2],
                mode="lines",
                name=f"On Handicap ({h:.1f})",
                line=dict(width=1.5, dash="dot", color="#2a78d6"),
                hoverinfo="skip",
            ))
    fig2.add_trace(go.Scatter(
        x=older["front"],
        y=older["back"],
        mode="markers",
        name="Earlier Rounds",
        marker=dict(size=8, color="#898781", opacity=0.6),
        customdata=older[["date", "course_name"]],
        hovertemplate="Front %{x:+.0f} / Back %{y:+.0f}<br>%{customdata[1]}, %{customdata[0]|%d-%b-%y}<extra></extra>",
    ))
    fig2.add_trace(go.Scatter(
        x=recent["front"],
        y=recent["back"],
        mode="markers",
        name="Last 5 Rounds",
        marker=dict(size=12, color="#2a78d6", line=dict(width=2, color="#0e1117")),
        customdata=recent[["date", "course_name"]],
        hovertemplate="Front %{x:+.0f} / Back %{y:+.0f}<br>%{customdata[1]}, %{customdata[0]|%d-%b-%y}<extra></extra>",
    ))
    fig2.update_layout(
        title="Front 9 vs Back 9 Scoring (to Par)",
        xaxis_title="Front 9 Score to Par",
        yaxis_title="Back 9 Score to Par",
        xaxis=dict(range=[axis_min, axis_max], constrain="domain"),
        yaxis=dict(range=[axis_min, axis_max], scaleanchor="x", scaleratio=1),
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
        margin=dict(b=100),
        width=600,
        height=600,
    )
    chart_col, stats_col = st.columns([1, 1])
    with chart_col:
        # A fixed pixel width/height (not width="stretch") so the chart
        # itself stays a true 1:1 square, not just equally-scaled axes
        # inside a wide box.
        st.plotly_chart(fig2, width="content")

    if current_handicap is not None:
        with stats_col:
            st.dataframe(_stats_table(rated_df, plot_df, current_handicap), width="stretch")
