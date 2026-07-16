import numpy as np
import pandas as pd


def yardage_moving_average(df: pd.DataFrame, window: int = 50, step: int = 1) -> pd.DataFrame:
    """Given hole-instance rows with 'yardage' and 'to_par' columns, compute a
    centered moving average of to_par over yardage: for every query yardage
    across the observed range (stepping by `step` yards), average the to_par
    of every recorded hole within +/- window/2 yards of it.

    This is a distance-based moving average (not a fixed-row-count rolling
    window), which is the correct approach since holes aren't evenly spaced
    by yardage. Query points with no data nearby get avg_to_par = NaN rather
    than a fabricated average or being dropped -- NaN makes a plotted line
    break/gap at that point instead of misleadingly connecting straight
    across a yardage range with no recorded holes in it.

    Returns a DataFrame with columns: yardage, avg_to_par, count (every
    yardage in the observed range is present, count 0 where avg_to_par is NaN).
    """
    yardages = df["yardage"].to_numpy()
    to_pars = df["to_par"].to_numpy()
    half_window = window / 2

    min_y, max_y = int(df["yardage"].min()), int(df["yardage"].max())
    query_points = np.arange(min_y, max_y + 1, step)

    rows = []
    for y in query_points:
        mask = (yardages >= y - half_window) & (yardages <= y + half_window)
        if mask.any():
            rows.append({"yardage": int(y), "avg_to_par": to_pars[mask].mean(), "count": int(mask.sum())})
        else:
            rows.append({"yardage": int(y), "avg_to_par": np.nan, "count": 0})

    return pd.DataFrame(rows)
