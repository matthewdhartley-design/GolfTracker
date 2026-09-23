import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.calculations.handicap_data import get_full_handicap_history
from app.calculations.net_double_bogey import course_handicap, strokes_received
from app.calculations.prediction import fit_hole_score_model, predict_hole_scores
from app.views.table_components import render_table_with_fixed_total
from database.queries import get_course_tees, get_hole_info


def _is_placeholder(value) -> bool:
    """True if a rating-type value is missing or this project's '0' placeholder
    sentinel for "not yet supplied" (see golf_schema memory notes)."""
    return pd.isna(value) or value == 0


def _to_par_str(score: float, par: float) -> str:
    """Format a score-vs-par difference the way golf scores are conventionally
    shown: 'E' for even, otherwise a signed number (e.g. '+2.3', '-1')."""
    diff = round(score - par, 1)
    if diff == 0:
        return "E"
    return f"{diff:+.1f}"

_WINDOW_OPTIONS = [
    ("All Time", "all"),
    ("Last 20 Rounds", "r20"),
    ("Last 40 Rounds", "r40"),
    ("Last 3 Months", "m3"),
    ("Last 6 Months", "m6"),
    ("Last 12 Months", "m12"),
]
_WINDOW_MONTHS = {"m3": 3, "m6": 6, "m12": 12}


def _filter_by_window(holes_df: pd.DataFrame, window: str) -> pd.DataFrame:
    """Filter capped-hole rows down to whole rounds within the given window,
    mirroring the "Zoom to" presets on the Handicap Over Time chart (Last
    20/40 Rounds, Last 3/6/12 Months) but as a genuine data filter rather
    than a chart range -- "all" returns every row unfiltered.
    """
    if window == "all" or holes_df.empty:
        return holes_df

    rounds = holes_df[["round_id", "date"]].drop_duplicates().sort_values("date")

    if window in ("r20", "r40"):
        n = min(20 if window == "r20" else 40, len(rounds))
        keep_ids = rounds.tail(n)["round_id"]
    else:
        max_date = pd.to_datetime(rounds["date"]).max()
        cutoff = max_date - pd.DateOffset(months=_WINDOW_MONTHS[window])
        keep_ids = rounds[pd.to_datetime(rounds["date"]) >= cutoff]["round_id"]

    return holes_df[holes_df["round_id"].isin(keep_ids)]


def render_course_preview():
    """Render the Course Preview sub-tab: pick any known course/tee and see a
    per-hole predicted score, based on par/yardage/stroke index tendencies
    learned from a selectable window of your scoring history.
    """
    hole_info = get_hole_info()
    if hole_info.empty:
        st.info("No course hole-by-hole data (par/yardage/stroke index) recorded yet.")
        return

    course_options = sorted(hole_info["course_name"].dropna().unique().tolist())
    selected_course = st.selectbox("Course", course_options, key="course_preview_course")

    tee_options = sorted(
        hole_info.loc[hole_info["course_name"] == selected_course, "tee_color"].dropna().unique().tolist()
    )
    selected_tee = st.selectbox(
        "Tee", tee_options, key=f"course_preview_tee_{selected_course}"
    )

    window_labels = [label for label, _ in _WINDOW_OPTIONS]
    window_map = dict(_WINDOW_OPTIONS)
    selected_window_label = st.selectbox(
        "Calculate average using",
        window_labels,
        index=window_labels.index("Last 20 Rounds"),
        key="course_preview_window",
    )
    selected_window = window_map[selected_window_label]

    target_holes = hole_info[
        (hole_info["course_name"] == selected_course) & (hole_info["tee_color"] == selected_tee)
    ].sort_values("hole_number")

    rated_df, capped_holes_df = get_full_handicap_history()
    if capped_holes_df.empty:
        st.info("No rounds yet have both hole-by-hole scores and course hole-by-hole par data recorded.")
        return

    train_holes = _filter_by_window(capped_holes_df, selected_window)
    if train_holes.empty:
        st.warning("No rounds fall within the selected window to base a prediction on.")
        return

    st.caption(
        f"Predictions are based on {train_holes['round_id'].nunique()} round(s) of scoring history "
        f"({selected_window_label.lower()}), using net-double-bogey-capped scores (WHS Rule 3.1)."
    )

    try:
        model = fit_hole_score_model(train_holes, target_par_values=target_holes["par"].unique())
    except ValueError as e:
        st.warning(str(e))
        return
    predicted = predict_hole_scores(model, target_holes)

    with st.expander("Regression model diagnostics"):
        st.caption(f"Formula: `{model.formula}`")
        st.write(
            f"R² = {model.r_squared:.3f}, Adjusted R² = {model.adj_r_squared:.3f}, "
            f"fit on {model.n_obs} holes."
        )
        st.dataframe(pd.DataFrame(model.coefficient_rows()), hide_index=True, width="stretch")

    current_handicap = rated_df.iloc[-1]["whs_handicap_index"] if not rated_df.empty else None

    tee_rows = get_course_tees()
    tee_row = tee_rows[
        (tee_rows["course_name"] == selected_course) & (tee_rows["tee_color"] == selected_tee)
    ]
    has_rating = (
        not tee_row.empty
        and not _is_placeholder(tee_row.iloc[0]["course_rating"])
        and not _is_placeholder(tee_row.iloc[0]["slope_rating"])
        and not _is_placeholder(tee_row.iloc[0]["par"])
    )

    predicted_total = round(predicted["predicted_score"].sum(), 1)
    predicted_par = int(predicted["par"].sum())

    metric_col1, metric_col2 = st.columns(2)
    metric_col1.metric(
        "Predicted Score (from history)",
        f"{predicted_total} ({_to_par_str(predicted_total, predicted_par)})",
    )

    tee_hcp = None
    if current_handicap is not None and has_rating:
        row = tee_row.iloc[0]
        tee_hcp = course_handicap(current_handicap, row["slope_rating"], row["course_rating"], row["par"])
        on_handicap_score = tee_hcp + int(row["par"])
        metric_col2.metric(
            "On-Handicap Expected Score",
            f"{on_handicap_score} ({_to_par_str(on_handicap_score, int(row['par']))})",
            help=(
                f"Course Handicap {tee_hcp} (Handicap Index {current_handicap:.1f}, "
                f"Slope {row['slope_rating']:.0f}, Rating {row['course_rating']:.1f}) + Par {int(row['par'])}"
            ),
        )
    else:
        metric_col2.metric("On-Handicap Expected Score", "N/A")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=predicted["hole_number"],
        y=predicted["par"],
        mode="lines+markers",
        name="Par",
        line=dict(width=1, dash="dash", color="#898781"),
        marker=dict(size=6),
    ))
    fig.add_trace(go.Scatter(
        x=predicted["hole_number"],
        y=predicted["predicted_score"],
        mode="lines+markers",
        name="Predicted Score",
        line=dict(width=2, color="#2a78d6"),
        marker=dict(size=7),
    ))
    fig.update_layout(
        title=f"Predicted Score by Hole -- {selected_course} ({selected_tee})",
        xaxis_title="Hole",
        yaxis_title="Score",
        xaxis=dict(tickmode="linear", tick0=1, dtick=1),
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
        margin=dict(b=100),
    )
    st.plotly_chart(fig, width="stretch")

    rows = [
        {
            "Hole": str(int(row.hole_number)),
            "Par": int(row.par),
            "Yardage": int(row.yardage),
            "Stroke Index": int(row.stroke_index),
            "Predicted Score": round(row.predicted_score, 1),
        }
        for row in predicted.itertuples()
    ]
    total_row = {
        "Hole": "Total",
        "Par": predicted_par,
        "Yardage": int(predicted["yardage"].sum()),
        "Stroke Index": "",
        "Predicted Score": f"{predicted_total} ({_to_par_str(predicted_total, predicted_par)})",
    }

    if tee_hcp is not None:
        st.caption(
            f"'Strokes Received' and 'Expected Score' below are on-handicap figures, based on a "
            f"Course Handicap of {tee_hcp} (Handicap Index {current_handicap:.1f}), allocated to the "
            "lowest stroke index holes first."
        )
        for row_dict, row in zip(rows, predicted.itertuples()):
            received = strokes_received(tee_hcp, int(row.stroke_index))
            row_dict["Strokes Received"] = received
            row_dict["Expected Score"] = int(row.par) + received
        total_row["Strokes Received"] = tee_hcp
        total_row["Expected Score"] = f"{on_handicap_score} ({_to_par_str(on_handicap_score, predicted_par)})"

    def _subtotal_row(label: str, subset_rows: list[dict]) -> dict:
        row = {"Hole": label}
        for col in subset_rows[0]:
            if col == "Hole":
                continue
            elif col == "Stroke Index":
                row[col] = ""
            elif col == "Predicted Score":
                subtotal = round(sum(r[col] for r in subset_rows), 1)
                row[col] = f"{subtotal} ({_to_par_str(subtotal, row['Par'])})"
            else:
                row[col] = int(sum(r[col] for r in subset_rows))
        return row

    front9_rows = [r for r in rows if int(r["Hole"]) <= 9]
    back9_rows = [r for r in rows if int(r["Hole"]) > 9]
    summary_rows = [
        _subtotal_row("Front 9", front9_rows),
        _subtotal_row("Back 9", back9_rows),
        total_row,
    ]

    render_table_with_fixed_total(rows, summary_rows, table_id="course_preview")
