import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from scipy.stats import linregress

from app.calculations.handicap_data import get_full_handicap_history, yearly_handicap_lows
from app.calculations.scoring import CATEGORY_ORDER, round_score_distribution

_CATEGORY_COLORS = {
    "Birdie or Better": "#0ca30c",
    "Par": "#c3c2b7",
    "Bogey": "#eda100",
    "Double Bogey": "#eb6834",
    "Triple+ Bogey": "#d03b3b",
}

_CORRELATION_WINDOW = 20
_EXTRAPOLATE_TO_HANDICAP = 10.0

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
    # Cumulative through each category and everything better than it (CATEGORY_ORDER
    # runs best-to-worst, so a running cumsum at "Par" = Birdie or Better + Par) --
    # shown in the tooltip alongside that category's own average.
    cumulative = rolling[CATEGORY_ORDER].cumsum(axis=1)

    fig = go.Figure()
    for category in CATEGORY_ORDER:
        fig.add_trace(go.Scatter(
            x=rolling.index,
            y=rolling[category],
            mode="lines",
            name=category,
            stackgroup="one",
            line=dict(width=0.5, color=_CATEGORY_COLORS[category]),
            customdata=cumulative[category],
            hovertemplate=(
                f"<b>{category}</b><br>"
                "Avg Holes: %{y:.2f}<br>"
                "Cumulative (this + better): %{customdata:.2f}"
                "<extra></extra>"
            ),
        ))

    for low in yearly_handicap_lows(rated_df):
        fig.add_vline(
            x=pd.Timestamp(low["date"]),
            line_width=1,
            line_dash="dot",
            line_color="#0ca30c",
            opacity=0.7,
            annotation_text=f"{low['year']} Low: {low['whs_handicap_index']:.1f}",
            annotation_position="top",
        )

    fig.update_layout(
        title=f"Rolling {window}-Round Average Score Distribution",
        xaxis_title="Date",
        yaxis_title="Avg Holes per Category",
        yaxis=dict(range=[0, 18]),
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5, traceorder="normal"),
        margin=dict(b=100),
    )
    st.plotly_chart(fig, width="stretch")

    current_handicap = rated_df.iloc[-1]["whs_handicap_index"] if not rated_df.empty else None
    _render_front_back_scatter(holes, round_meta, rated_df, current_handicap)

    _render_handicap_correlation(counts, round_meta, rated_df)


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


def _rolling_best_n_average(values: np.ndarray, differentials: np.ndarray, window: int, best_n: int) -> np.ndarray:
    """For each row with `window` rows of history ending at it (inclusive),
    average `values`' columns over just the `best_n` lowest-differential
    rows within that window -- replicating WHS Rule 5.1's own selection at
    every historical point (which rounds actually determined that window's
    handicap), rather than a plain average of the full window. Rows without
    enough history get NaN.
    """
    n_rows, n_cols = values.shape
    result = np.full((n_rows, n_cols), np.nan)
    for i in range(window - 1, n_rows):
        window_diffs = differentials[i - window + 1: i + 1]
        best_positions = np.argsort(window_diffs)[:best_n] + (i - window + 1)
        result[i] = values[best_positions].mean(axis=0)
    return result


def _render_handicap_correlation(counts: pd.DataFrame, round_meta: pd.DataFrame, rated_df: pd.DataFrame):
    """Scatter of WHS Handicap Index (x) against a chosen category's average
    holes-per-round (y) -- one point per round with enough history -- to
    explore how strongly each scoring category correlates with handicap.

    Two averaging modes for the y-value, both over a fixed _CORRELATION_WINDOW
    (not the adjustable slider used for the chart above, so every point is a
    consistent, comparable sample size):
    - Full window average (default): the plain average over all
      _CORRELATION_WINDOW rounds -- a "meta trend" of overall game shape.
    - "Only rounds that counted": averages just the 8 lowest-differential
      rounds within each window (Rule 5.1's own selection, replayed at every
      point in history) -- what actually needs to be shot to be near that
      handicap, with non-counting rounds' noise excluded.

    Two independent row filters narrow which points are plotted/regressed:
    "Current counting rounds" (only the rounds counting toward *today's*
    low Handicap Index) and "Only last 20 rounds" (your most recent form).

    Only one category's individual round markers are plotted at a time (all
    5 overlaid as points would be unreadable), selected via the Score Type
    pills. Toggling "trendline only" hides every category's points and
    instead draws all 5 trendlines together, so their slopes can be
    compared directly. The stats table always lists all 5 categories'
    regression confidence (r, R-squared, slope, p-value), regardless of
    which one is currently selected or how it's being displayed.
    """
    st.subheader("Score Type vs Handicap Correlation")
    st.caption(
        f"Each point's y-value is that category's average holes per round over the "
        f"{_CORRELATION_WINDOW} rounds up to and including that round."
    )

    category = st.pills(
        "Score Type", CATEGORY_ORDER, default="Par", required=True, key="scoring_trends_corr_category"
    )
    toggle_col1, toggle_col2, toggle_col3, toggle_col4 = st.columns(4)
    with toggle_col1:
        trend_only = st.checkbox(
            "Show trendline only (all score types)", key="scoring_trends_corr_trend_only"
        )
    with toggle_col2:
        window_counting_only = st.checkbox(
            "Only rounds that counted", key="scoring_trends_corr_window_counting_only",
            help=(
                "Average each window using only the 8 lowest-differential rounds within it -- "
                "the rounds that actually determined that window's handicap -- instead of all "
                f"{_CORRELATION_WINDOW}. Shows what you actually need to shoot to be near a "
                "handicap, rather than the broader meta-trend of your overall game."
            ),
        )
    with toggle_col3:
        current_counting_only = st.checkbox(
            "Current counting rounds", key="scoring_trends_corr_current_counting_only",
            help="Restrict to rounds that currently count toward your low Handicap Index.",
        )
    with toggle_col4:
        last_20_only = st.checkbox(
            "Only last 20 rounds", key="scoring_trends_corr_last_20_only",
            help="Restrict to your most recent 20 rounds.",
        )

    base = round_meta[["round_id"]].copy()
    rated_indexed = rated_df.set_index("round_id")
    base["handicap"] = base["round_id"].map(rated_indexed["whs_handicap_index"])
    base["differential"] = base["round_id"].map(rated_indexed["score_differential"])
    base["counts_toward_handicap"] = base["round_id"].map(rated_indexed["counts_toward_handicap"])

    if window_counting_only:
        y_values = _rolling_best_n_average(
            counts[CATEGORY_ORDER].to_numpy(dtype=float), base["differential"].to_numpy(),
            window=_CORRELATION_WINDOW, best_n=8,
        )
    else:
        y_values = counts[CATEGORY_ORDER].rolling(
            window=_CORRELATION_WINDOW, min_periods=_CORRELATION_WINDOW
        ).mean().to_numpy()

    for idx, cat in enumerate(CATEGORY_ORDER):
        base[cat] = y_values[:, idx]
    # The trendline/regression stats are always computed from the full
    # (unfiltered-by-row-toggle) dataset, so they stay fixed as "Current
    # counting rounds"/"Only last 20 rounds" are toggled -- those two only
    # change which scatter points are drawn, not the fitted line itself.
    full_merged = base.dropna(subset=["handicap", *CATEGORY_ORDER])

    if len(full_merged) < 2:
        st.info(f"Not enough rounds yet -- need at least {_CORRELATION_WINDOW} rated rounds for this chart.")
        return

    display_merged = full_merged
    if current_counting_only:
        display_merged = display_merged[display_merged["counts_toward_handicap"]]
    if last_20_only:
        display_merged = display_merged.tail(20)

    x_full = full_merged["handicap"].to_numpy()
    x_display = display_merged["handicap"].to_numpy()
    x_min_observed = float(x_full.min())
    x_max_observed = float(x_full.max())
    x_extrap_start = min(_EXTRAPOLATE_TO_HANDICAP, x_min_observed)
    has_extrapolation = x_extrap_start < x_min_observed

    fig = go.Figure()
    stats_rows = []
    extrapolated_maxima = []
    for cat in CATEGORY_ORDER:
        y_full = full_merged[cat].to_numpy()
        result = linregress(x_full, y_full)
        stats_rows.append({
            "Category": cat,
            "Rounds": len(full_merged),
            "Correlation (r)": round(result.rvalue, 3),
            "R²": round(result.rvalue ** 2, 3),
            "Slope": round(result.slope, 3),
            "p-value": round(result.pvalue, 4),
            "Significant (p<0.05)": "Yes" if result.pvalue < 0.05 else "No",
        })

        if not trend_only and cat == category:
            fig.add_trace(go.Scatter(
                x=x_display, y=display_merged[cat].to_numpy(), mode="markers",
                name=cat,
                marker=dict(size=7, color=_CATEGORY_COLORS[cat], opacity=0.6),
                hovertemplate=f"{cat} (actual): %{{y:.2f}}<extra></extra>",
            ))

        if trend_only or cat == category:
            # Finely sampled (not just the 2 endpoints) so "x unified" hover
            # in trendline-only mode can pick up every line's value at
            # whatever x position is being hovered, not just the endpoints.
            x_line = np.linspace(x_min_observed, x_max_observed, 100)
            y_line = result.intercept + result.slope * x_line
            fig.add_trace(go.Scatter(
                x=x_line, y=y_line, mode="lines",
                name=f"{cat} Trend",
                line=dict(width=2, dash="dash", color=_CATEGORY_COLORS[cat]),
                hovertemplate=f"{cat} (trend): %{{y:.2f}}<extra></extra>",
            ))

            if has_extrapolation:
                # Same fitted line, continued below the lowest handicap
                # actually observed -- drawn thinner/dotted so it reads as
                # projection rather than fitted-to-data.
                x_extrap = np.linspace(x_extrap_start, x_min_observed, 30)
                y_extrap = result.intercept + result.slope * x_extrap
                extrapolated_maxima.append(float(y_extrap.max()))
                fig.add_trace(go.Scatter(
                    x=x_extrap, y=y_extrap, mode="lines",
                    name=f"{cat} Trend (Extrapolated)",
                    line=dict(width=1.5, dash="dot", color=_CATEGORY_COLORS[cat]),
                    opacity=0.55,
                    hovertemplate=f"{cat} (extrapolated): %{{y:.2f}}<extra></extra>",
                    showlegend=False,
                ))

    if has_extrapolation:
        fig.add_vline(
            x=x_min_observed,
            line_width=1,
            line_dash="dot",
            line_color="#898781",
            opacity=0.7,
            annotation_text=f"Extrapolation begins ({x_min_observed:.1f})",
            annotation_position="top",
        )

    window_label = "Best 8 of 20" if window_counting_only else f"Full {_CORRELATION_WINDOW}"
    if trend_only:
        title = f"All Score Types: {window_label} Avg Trend vs Handicap Index"
        yaxis_title = f"Avg Holes ({window_label})"
    else:
        title = f"{category}: {window_label} Avg vs Handicap Index"
        yaxis_title = f"Avg {category} Holes ({window_label})"

    # Fixed at [0, max across all 5 series] (not just the displayed one) so
    # the axis doesn't jump around as the Score Type/toggles are changed --
    # a moving y-axis was undercutting the visual comparison this chart is for.
    # Also widened to fit the extrapolated projection(s), which can run
    # higher than any actually-observed value.
    y_max = max([float(full_merged[CATEGORY_ORDER].to_numpy().max())] + extrapolated_maxima)

    fig.update_layout(
        title=title,
        xaxis_title="WHS Handicap Index",
        yaxis_title=yaxis_title,
        # Rounds the shared "x unified" hover header to 1 decimal place --
        # otherwise it shows the raw interpolated x position (e.g. 17.15687).
        xaxis=dict(hoverformat=".1f"),
        yaxis=dict(range=[0, y_max]),
        margin=dict(b=40),
        height=900,
        # "x unified" always -- in trendline-only mode this surfaces every
        # category's value at once for a given x; in single-category mode it
        # ensures the trend's fitted value is always shown alongside the
        # actual point, with the x-axis (handicap) position as the shared
        # header, rather than only showing whichever trace is under the cursor.
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch")

    st.dataframe(pd.DataFrame(stats_rows), hide_index=True, width="stretch")
