import pandas as pd

CATEGORY_ORDER = ["Birdie or Better", "Par", "Bogey", "Double Bogey", "Triple+ Bogey"]


def categorize_score(score: int, par: int) -> str:
    """Bucket a hole score relative to par into one of the 5 CATEGORY_ORDER labels."""
    diff = score - par
    if diff <= -1:
        return "Birdie or Better"
    if diff == 0:
        return "Par"
    if diff == 1:
        return "Bogey"
    if diff == 2:
        return "Double Bogey"
    return "Triple+ Bogey"


def round_score_distribution(scores_df: pd.DataFrame) -> pd.DataFrame:
    """Given a DataFrame with round_id/score/par columns (one row per hole),
    return a table indexed by round_id with one column per CATEGORY_ORDER
    label, counting how many holes in that round fell into each category.
    """
    df = scores_df.copy()
    df["category"] = [categorize_score(s, p) for s, p in zip(df["score"], df["par"])]
    counts = df.groupby(["round_id", "category"]).size().unstack(fill_value=0)
    counts = counts.reindex(columns=CATEGORY_ORDER, fill_value=0)
    return counts


def hole_score_distribution(scores_df: pd.DataFrame) -> pd.DataFrame:
    """Given a DataFrame with hole_number/score/par columns, return a table
    indexed by hole (1-18) with one column per CATEGORY_ORDER label, counting
    how many recorded rounds fell into each category on that hole. Holes or
    categories with no data are filled with 0 rather than omitted.
    """
    df = scores_df.copy()
    df["category"] = [categorize_score(s, p) for s, p in zip(df["score"], df["par"])]

    counts = df.groupby(["hole_number", "category"]).size().unstack(fill_value=0)
    counts = counts.reindex(columns=CATEGORY_ORDER, fill_value=0)
    counts = counts.reindex(index=range(1, 19), fill_value=0)
    return counts
