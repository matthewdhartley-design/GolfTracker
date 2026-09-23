import pandas as pd

# Fixed naming convention for match stages, earliest to latest. "Quarter
# Final"/"Semi Final"/"Final" always sit exactly 2/1/0 stages before the
# final in club knockout golf, regardless of the draw size -- only how many
# "Round N" stages come before the Quarter Final varies by edition.
CANONICAL_STAGE_ORDER = [
    "Round 1", "Round 2", "Round 3", "Round 4", "Round 5", "Round 6", "Round 7", "Round 8",
    "Quarter Final", "Semi Final", "Final",
]
_STAGE_RANK = {stage: i for i, stage in enumerate(CANONICAL_STAGE_ORDER)}


def stage_rank(stage: str) -> int:
    """Canonical earliest-to-latest position of a stage name. Raises if the
    name isn't one of CANONICAL_STAGE_ORDER's exact strings -- data entry
    should stick to those so every edition sorts consistently.
    """
    return _STAGE_RANK[stage]


_FIXED_DISTANCE = {"Final": 0, "Semi Final": 1, "Quarter Final": 2}


def rounds_from_final(stages: pd.Series, rounds_before_quarterfinal: int) -> pd.Series:
    """How many stages before the *tournament's actual* Final each stage in
    `stages` is -- always 0 for Final, 1 for Semi Final, 2 for Quarter
    Final (fixed, universal: those names mean the same bracket depth in any
    size draw). "Round N" stages come before the Quarter Final, so their
    distance is 2 + (rounds_before_quarterfinal - N + 1).

    `rounds_before_quarterfinal` is that *competition's* total count of
    preliminary rounds (golf.knockout_competitions.rounds_before_quarterfinal)
    -- deliberately NOT inferred from which rounds this edition's rows
    happen to record, since being eliminated early means the later
    preliminary rounds (that other pairs played) never produce a row here
    at all. Using the edition's own max recorded "Round N" as a stand-in
    for the competition's true depth would silently miscount an early exit
    as if the bracket were shallower than it really is.
    """
    def _distance(stage: str) -> int:
        if stage in _FIXED_DISTANCE:
            return _FIXED_DISTANCE[stage]
        n = int(stage.split(" ")[1])
        return 2 + (rounds_before_quarterfinal - n + 1)

    return stages.map(_distance)


def build_knockout_grid(
    matches: pd.DataFrame, competitions: pd.DataFrame
) -> tuple[pd.DataFrame, dict[int, str]]:
    """Build the Final-anchored grid: one row per distance-from-final, one
    column per (competition_name, year) edition present in `matches`, cell
    values are a compact result string (or None if that edition didn't
    reach/need that stage).

    `competitions` is golf.knockout_competitions (via get_knockout_competitions),
    used to look up each match's competition's rounds_before_quarterfinal for
    rounds_from_final -- see that function for why this can't be inferred
    from `matches` alone.

    Returns (grid_df, row_labels) where row_labels maps each row's
    distance-from-final to a display label -- the stage name(s) actually
    seen at that distance, joined with " / " if editions disagree (e.g. one
    edition's "2 before final" stage is "Quarter Final" while a smaller
    draw's is "Round 1").
    """
    if matches.empty:
        return pd.DataFrame(), {}

    matches = matches.copy()
    # Group by the plain (competition, year) key -- season_label is only a
    # cosmetic override of the displayed label (e.g. "2025/26" for a winter
    # comp spanning two calendar years), not part of the grouping/sort key.
    matches["edition_key"] = matches["competition_name"] + " " + matches["year"].astype(str)
    display_year = matches["season_label"].where(matches["season_label"].notna(), matches["year"].astype(str))
    matches["edition"] = matches["competition_name"] + " " + display_year

    pre_qf_rounds = competitions.set_index("competition_name")["rounds_before_quarterfinal"]
    matches["distance"] = 0
    for edition_key, group in matches.groupby("edition_key"):
        depth = int(pre_qf_rounds[group["competition_name"].iloc[0]])
        matches.loc[group.index, "distance"] = rounds_from_final(group["stage"], depth)
    matches["result_text"] = matches.apply(_format_result, axis=1)

    edition_order = (
        matches[["edition_key", "edition"]].drop_duplicates().sort_values("edition_key")["edition"]
    )
    editions = edition_order.tolist()
    max_distance = int(matches["distance"].max())

    grid = pd.DataFrame(
        index=range(max_distance, -1, -1), columns=editions, dtype=object
    )
    row_labels: dict[int, list[str]] = {d: [] for d in grid.index}
    for row in matches.itertuples():
        grid.loc[row.distance, row.edition] = row.result_text
        if row.stage not in row_labels[row.distance]:
            row_labels[row.distance].append(row.stage)

    labels = {d: " / ".join(stages) for d, stages in row_labels.items()}
    return grid, labels


def _format_result(row) -> str:
    """A compact one-line result for a grid cell, e.g. 'W 1&0 (19th Hole) v
    Darlow/Rogers', 'L 3&2 v Smith', or 'Bye'.
    """
    if row.is_bye:
        return "Bye"

    opponents = row.opponent1_name or ""
    if pd.notna(row.opponent2_name) and row.opponent2_name:
        opponents += f" / {row.opponent2_name}"

    if row.won is None or pd.isna(row.won):
        return f"v {opponents}" if opponents else "-"

    outcome = "W" if row.won else "L"
    margin = f" {row.margin}" if pd.notna(row.margin) and row.margin else ""
    return f"{outcome}{margin} v {opponents}"
