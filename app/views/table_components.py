import json
import re

import pandas as pd
import streamlit as st

from app.calculations.round_ranking import compute_round_rankings
from app.calculations.streaks import STREAK_CATEGORIES, category_streaks


def _to_par_str(score, par) -> str:
    """Format a score-vs-par difference the way golf scores are
    conventionally shown: 'E' for even, otherwise a signed number."""
    diff = score - par
    if diff == 0:
        return "E"
    return f"{diff:+d}"


def _score_colors(diff: int) -> tuple[str, str] | tuple[None, None]:
    """Background/text color for a hole's score, by how it compares to par --
    blue for birdie or better, unhighlighted for par, and progressively
    darker reds for bogey / double bogey / triple-or-worse."""
    if diff <= -1:
        return "#2a78d6", "#ffffff"
    if diff == 0:
        return None, None
    if diff == 1:
        return "#f8d7da", "#5c1a1a"
    if diff == 2:
        return "#e57373", "#ffffff"
    return "#b71c1c", "#ffffff"


_LABEL_WIDTH = "108px"
_COL_WIDTH = "60px"


def scorecard_html(round_holes: pd.DataFrame, highlight_start: int | None = None, highlight_end: int | None = None) -> str:
    """Build a classic horizontal scorecard (Hole/Par/Handicap/Score rows,
    front 9 then back 9) as an HTML string, with the OUT/IN/TOT totals
    showing the score to par in brackets (e.g. "40 (+5)").

    Score cells are colored by how they compare to par -- blue for birdie or
    better, progressively darker reds for bogey/double/triple-or-worse, and
    plain for par. Holes in [highlight_start, highlight_end] (e.g. to call
    out a streak) get an added border rather than overriding that color, so
    the two concerns don't conflict.

    Both blocks use the same fixed column widths (rather than each table
    stretching to fill its container independently) so holes 1-9 in the
    front block line up directly above holes 10-18 in the back block.
    """
    ordered = round_holes.sort_values("hole_number")
    par_by_hole = dict(zip(ordered["hole_number"], ordered["par"]))
    si_by_hole = dict(zip(ordered["hole_number"], ordered["stroke_index"]))
    score_by_hole = dict(zip(ordered["hole_number"], ordered["score"]))
    estimated_holes = (
        set(ordered.loc[ordered["is_estimated"], "hole_number"])
        if "is_estimated" in ordered.columns
        else set()
    )

    def _plain_cell(value):
        return f"<td style='padding:4px 2px;text-align:center;width:{_COL_WIDTH};box-sizing:border-box;'>{value}</td>"

    def _score_cell(hole):
        diff = score_by_hole[hole] - par_by_hole[hole]
        bg, text_color = _score_colors(diff)
        style = f"padding:4px 2px;text-align:center;width:{_COL_WIDTH};box-sizing:border-box;"
        if bg is not None:
            style += f"background-color:{bg};color:{text_color};font-weight:600;"
        if highlight_start is not None and highlight_start <= hole <= highlight_end:
            style += "box-shadow:inset 0 0 0 3px #eda100;"
        if hole in estimated_holes:
            label = f"{score_by_hole[hole]}*"
            title = (
                " title='Not fully recorded -- estimated (e.g. net double bogey imputed "
                "for a missing hole, or a conceded/picked-up hole given a representative score)'"
            )
        else:
            label = str(score_by_hole[hole])
            title = ""
        return f"<td style='{style}'{title}>{label}</td>"

    def _label_cell(text):
        return (
            f"<td style='padding:4px 6px;text-align:left;font-weight:600;"
            f"width:{_LABEL_WIDTH};box-sizing:border-box;'>{text}</td>"
        )

    def _header_cell(value):
        return (
            f"<th style='padding:4px 2px;text-align:center;width:{_COL_WIDTH};box-sizing:border-box;"
            f"background-color:#31333f;color:#ffffff;'>{value}</th>"
        )

    def _label_header_cell(value):
        return (
            f"<th style='padding:4px 6px;text-align:left;width:{_LABEL_WIDTH};box-sizing:border-box;"
            f"background-color:#31333f;color:#ffffff;'>{value}</th>"
        )

    def _block(holes: list[int], totals: list[tuple[str, list[int]]], spacer_cols: int = 0) -> str:
        """spacer_cols pads out this block with blank total-width columns --
        used so the front-9 block (only an OUT total) matches the back-9
        block's width (IN + TOT totals), since each table centers itself
        independently and mismatched widths would misalign the two blocks.
        """
        if not holes:
            return ""
        spacer_headers = "".join(_header_cell("") for _ in range(spacer_cols))
        spacer_cells = "".join(_plain_cell("") for _ in range(spacer_cols))

        header = (
            "<tr>" + _label_header_cell("Hole") + "".join(_header_cell(h) for h in holes)
            + "".join(_header_cell(label) for label, _ in totals) + spacer_headers + "</tr>"
        )
        par_row = (
            "<tr>" + _label_cell("Par") + "".join(_plain_cell(par_by_hole[h]) for h in holes)
            + "".join(_plain_cell(sum(par_by_hole[h] for h in subset)) for _, subset in totals)
            + spacer_cells + "</tr>"
        )
        si_row = (
            "<tr>" + _label_cell("Handicap") + "".join(_plain_cell(si_by_hole[h]) for h in holes)
            + "".join(_plain_cell("") for _ in totals) + spacer_cells + "</tr>"
        )
        score_total_cells = "".join(
            _plain_cell(
                f"{sum(score_by_hole[h] for h in subset)} "
                f"({_to_par_str(sum(score_by_hole[h] for h in subset), sum(par_by_hole[h] for h in subset))})"
            )
            for _, subset in totals
        )
        score_row = (
            "<tr>" + _label_cell("Score") + "".join(_score_cell(h) for h in holes)
            + score_total_cells + spacer_cells + "</tr>"
        )
        return (
            "<table style='border-collapse:collapse;table-layout:fixed;margin:0 auto 8px auto;font-size:0.9rem;'>"
            f"{header}{par_row}{si_row}{score_row}</table>"
        )

    all_holes = sorted(par_by_hole.keys())
    front_holes = [h for h in range(1, 10) if h in par_by_hole]
    back_holes = [h for h in range(10, 19) if h in par_by_hole]

    blocks = []
    if front_holes:
        # Back-9 block has 2 total columns (IN, TOT); pad front-9's single
        # OUT total with 1 blank spacer column so both blocks are equal width.
        spacer = 1 if back_holes else 0
        blocks.append(_block(front_holes, [("OUT", front_holes)], spacer_cols=spacer))
    if back_holes:
        blocks.append(_block(back_holes, [("IN", back_holes), ("TOT", all_holes)]))
    return "".join(blocks)


def round_detail_html(round_id: int, round_holes: pd.DataFrame, global_rated_df: pd.DataFrame) -> str:
    """Build the expanded detail shown under a clicked round (used by both
    the Macro Trends rounds table and the All Time Records rounds tables):
    a classic horizontal scorecard (gross scores, front 9 then back 9), a
    callout of the longest streak achieved in that round for each category,
    and where this round's score differential ranks among several
    comparison groups.

    Streaks qualify on net-double-bogey-capped scores (WHS Rule 3.1), same
    convention as the rest of this app, but the scorecard itself shows real,
    uncapped strokes. Rankings are always computed against the full
    (unfiltered) history, regardless of any filters applied on the calling
    page.
    """
    ordered = round_holes.sort_values("hole_number")
    scorecard = scorecard_html(ordered)

    capped_for_streaks = ordered.rename(columns={"score": "raw_score", "capped_score": "score"})
    streak_lines = []
    for label, max_to_par in STREAK_CATEGORIES:
        runs = category_streaks(capped_for_streaks, max_to_par)
        if not runs:
            streak_lines.append(f"<div><b>{label}:</b> none</div>")
            continue
        best = max(runs, key=lambda r: r["length"])
        streak_lines.append(
            f"<div><b>{label}:</b> {best['length']} hole(s) "
            f"(Holes {best['start_hole']}-{best['end_hole']})</div>"
        )

    rankings = compute_round_rankings(round_id, global_rated_df)
    ranking_lines = [f"<div><b>{label}:</b> {value}</div>" for label, value in rankings]

    sections = (
        "<div style='margin-top:4px;font-size:0.85rem;display:flex;gap:24px;flex-wrap:wrap;'>"
        "<div>" + "".join(streak_lines) + "</div>"
    )
    if ranking_lines:
        sections += "<div>" + "".join(ranking_lines) + "</div>"
    sections += "</div>"

    return f"<div style='padding:8px 4px;'>{scorecard}{sections}</div>"


def expandable_rounds_table_html(
    columns: list[str],
    rows: list[dict],
    round_details: dict[int, str],
    table_id: str,
):
    """Render a rounds table where clicking a row splices that round's
    detail HTML directly into the gap between it and the next row --
    clicking the same row again collapses it, and clicking a different row
    closes whichever one was open first.

    Each dict in `rows` needs a "_round_id" key (used to look up
    `round_details` and passed to the click handler) plus one entry per
    label in `columns` (an already-formatted display value -- inline HTML,
    e.g. a colored dot span, is fine). An optional "_row_style" key adds
    extra inline CSS to that <tr> (e.g. a divider border).

    Uses st.iframe with height="content", so the iframe (and the page
    content below it) grows and shrinks in real time as rows expand and
    collapse -- Streamlit's own content-measuring script (auto-injected for
    height="content") re-measures on every DOM mutation, which includes our
    click handler splicing a detail row in and out.

    st.markdown doesn't reliably execute <script> tags, so this uses
    st.iframe, which runs in a real iframe (same technique as the other
    shared HTML table components in this module).
    """
    header = "<tr>" + "".join(
        f"<th style='text-align:left;padding:4px 8px;'>{col}</th>" for col in columns
    ) + "</tr>"

    row_html = []
    for row in rows:
        round_id = int(row["_round_id"])
        row_style = row.get("_row_style", "")
        cells = "".join(f"<td style='padding:4px 8px;'>{row[col]}</td>" for col in columns)
        row_html.append(
            f"<tr style='cursor:pointer;{row_style}' "
            f"onclick=\"toggleDetail_{table_id}(this, {round_id})\">{cells}</tr>"
        )

    no_data_message = "No hole-by-hole data recorded for this round."
    html = f"""
    <style>
        html, body {{
            margin: 0;
            background-color: #ffffff;
            color: #31333f;
            font-family: system-ui,-apple-system,'Segoe UI',sans-serif;
        }}
        @media (prefers-color-scheme: dark) {{
            html, body {{ background-color: #0e1117; color: #fafafa; }}
        }}
    </style>
    <table style='width:100%;border-collapse:collapse;font-size:0.9rem;'>
        <thead>{header}</thead>
        <tbody id="rounds-tbody-{table_id}">{''.join(row_html)}</tbody>
    </table>
    <script>
    const roundDetails_{table_id} = {json.dumps(round_details)};
    let openDetailRow_{table_id} = null;
    function toggleDetail_{table_id}(rowEl, roundId) {{
        const existing = rowEl.nextElementSibling;
        if (existing && existing.classList.contains('detail-row-{table_id}')) {{
            existing.remove();
            openDetailRow_{table_id} = null;
            return;
        }}
        if (openDetailRow_{table_id}) {{ openDetailRow_{table_id}.remove(); }}

        const tr = document.createElement('tr');
        tr.className = 'detail-row-{table_id}';
        const td = document.createElement('td');
        td.colSpan = {len(columns)};
        td.innerHTML = roundDetails_{table_id}[roundId] || "<div style='padding:8px;'>{no_data_message}</div>";
        tr.appendChild(td);
        rowEl.parentNode.insertBefore(tr, rowEl.nextSibling);
        openDetailRow_{table_id} = tr;
    }}
    </script>
    """
    st.iframe(html, height="content")


def sort_key(value) -> str:
    """Extract a sortable value from a table cell: numbers sort numerically,
    'N (P%)' cells sort by the count N, everything else sorts as text.
    """
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return text
    match = re.match(r"^(-?\d+(\.\d+)?)\s*\(", text)
    if match:
        return match.group(1)
    return text.lower()


def render_table_with_fixed_total(rows: list[dict], summary_rows: list[dict] | dict, table_id: str):
    """Render `rows` as a click-to-sort table with `summary_rows` permanently
    pinned as the last row(s) (e.g. Front 9 / Back 9 / Total), no header of
    its own, and no gap from the row above it.

    `summary_rows` can be a single dict (e.g. just a Total row) or a list of
    dicts rendered in the given order.

    st.dataframe can't pin a row (sorting could move a Total row out of
    place) or hide its header, and two separate st.dataframe widgets can't
    be guaranteed to line up column-for-column since each auto-sizes
    independently. This renders one HTML table with real click-to-sort via
    embedded JS instead -- st.markdown doesn't reliably execute <script>
    tags, so this uses st.iframe, which runs in a real iframe. The summary
    rows live in their own <tbody> that the sort script never touches, so
    they always stay last regardless of how the data is sorted.
    """
    if isinstance(summary_rows, dict):
        summary_rows = [summary_rows]

    columns = list(rows[0].keys())

    def _cells(row: dict, *, bold: bool = False) -> str:
        style = "font-weight:600;" if bold else ""
        return "".join(
            f"<td data-value=\"{sort_key(row[col])}\" style='padding:4px 8px;{style}"
            f"{'' if col == 'Hole' else 'text-align:right;'}'>{row[col]}</td>"
            for col in columns
        )

    header_cells = "".join(
        f"<th style='text-align:{'left' if col == 'Hole' else 'right'};padding:4px 8px;"
        f"cursor:pointer;user-select:none;' onclick=\"sortTable_{table_id}({i})\">{col}</th>"
        for i, col in enumerate(columns)
    )
    data_rows = "".join(f"<tr>{_cells(row)}</tr>" for row in rows)
    summary_rows_html = "".join(f"<tr>{_cells(row, bold=True)}</tr>" for row in summary_rows)

    html = f"""
    <style>
        /* Explicit light/dark backgrounds so the browser doesn't fall back to
        its own color-scheme default (which renders as solid black when the
        surrounding Streamlit app is in dark mode and this iframe's document
        otherwise has no declared background). */
        html, body {{
            margin: 0;
            background-color: #ffffff;
            color: #31333f;
        }}
        @media (prefers-color-scheme: dark) {{
            html, body {{
                background-color: #0e1117;
                color: #fafafa;
            }}
        }}
    </style>
    <div style="font-family:system-ui,-apple-system,'Segoe UI',sans-serif;">
    <table style='width:100%;border-collapse:collapse;font-size:0.9rem;'>
        <thead id="header-{table_id}"><tr>{header_cells}</tr></thead>
        <tbody id="data-body-{table_id}">{data_rows}</tbody>
        <tbody>{summary_rows_html}</tbody>
    </table>
    </div>
    <script>
    function sortTable_{table_id}(colIndex) {{
        const tbody = document.getElementById('data-body-{table_id}');
        const ths = document.getElementById('header-{table_id}').querySelectorAll('th');
        const ascending = !(tbody.getAttribute('data-sort-col') == colIndex
                             && tbody.getAttribute('data-sort-dir') === 'asc');

        const rows = Array.from(tbody.querySelectorAll('tr'));
        rows.sort((a, b) => {{
            const x = a.children[colIndex].getAttribute('data-value');
            const y = b.children[colIndex].getAttribute('data-value');
            const nx = parseFloat(x), ny = parseFloat(y);
            const result = (!isNaN(nx) && !isNaN(ny)) ? (nx - ny) : x.localeCompare(y);
            return ascending ? result : -result;
        }});
        rows.forEach(r => tbody.appendChild(r));
        tbody.setAttribute('data-sort-col', colIndex);
        tbody.setAttribute('data-sort-dir', ascending ? 'asc' : 'desc');

        ths.forEach((th, i) => {{
            th.innerText = th.innerText.replace(/ [\\u25b2\\u25bc]$/, '');
            if (i === colIndex) {{ th.innerText += ascending ? ' \\u25b2' : ' \\u25bc'; }}
        }});
    }}
    </script>
    """
    st.iframe(html, height="content")
