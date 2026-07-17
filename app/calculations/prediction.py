import pandas as pd
import statsmodels.formula.api as smf

# Tiered formulas, tried in order until one fits without error: the full model
# gives par (categorical) its own yardage slope (a long par 3 plays
# differently to a long par 5), falling back to a single shared yardage
# slope, then to a model without par at all, for training windows too small
# or too collinear (e.g. one par type with no yardage variation) to support
# the richer formula.
_FULL_FORMULA = "to_par ~ C(par) + yardage + yardage:C(par) + stroke_index"
_NO_INTERACTION_FORMULA = "to_par ~ C(par) + yardage + stroke_index"
_MINIMAL_FORMULA = "to_par ~ yardage + stroke_index"

_TERM_LABELS = {
    "Intercept": "Intercept (Par 3 baseline)",
    "C(par)[T.4]": "Par 4 effect (vs Par 3)",
    "C(par)[T.5]": "Par 5 effect (vs Par 3)",
    "yardage": "Yardage slope",
    "yardage:C(par)[T.4]": "Yardage slope, extra for Par 4",
    "yardage:C(par)[T.5]": "Yardage slope, extra for Par 5",
    "stroke_index": "Stroke Index slope",
}


class HoleScoreModel:
    """A fitted OLS regression of score-to-par on par/yardage/stroke index,
    plus the diagnostics needed to judge how much to trust it.
    """

    def __init__(self, result, formula: str, n_obs: int):
        self.result = result
        self.formula = formula
        self.n_obs = n_obs

    @property
    def r_squared(self) -> float:
        return self.result.rsquared

    @property
    def adj_r_squared(self) -> float:
        return self.result.rsquared_adj

    def coefficient_rows(self) -> list[dict]:
        """One row per fitted term: label, coefficient, and p-value."""
        return [
            {
                "Term": _TERM_LABELS.get(term, term),
                "Coefficient": round(coef, 3),
                "P-Value": round(self.result.pvalues[term], 3),
            }
            for term, coef in self.result.params.items()
        ]


def fit_hole_score_model(train_holes: pd.DataFrame, target_par_values=None) -> HoleScoreModel:
    """Fit an OLS regression of net-double-bogey-capped score-to-par on par
    (categorical), yardage (with its own slope per par type), and stroke
    index (a single continuous slope).

    `target_par_values`, if given, are the par values the model will need to
    predict for -- if training data doesn't include one of them (e.g. a
    "Last 20 Rounds" window that happened to have no par 5s), the categorical
    par formula is skipped entirely up front, since a fitted model can't
    predict a category it never saw. Separately, if a formula still fails to
    fit (e.g. a singular design matrix from a par type with zero yardage
    variation), the next simpler formula in the tier is tried instead.
    """
    train = train_holes.copy()
    train["to_par"] = train["capped_score"] - train["par"]
    train["par"] = train["par"].astype(int)

    formulas = [_FULL_FORMULA, _NO_INTERACTION_FORMULA, _MINIMAL_FORMULA]
    if target_par_values is not None and not set(target_par_values).issubset(set(train["par"].unique())):
        formulas = [_MINIMAL_FORMULA]

    for formula in formulas:
        try:
            result = smf.ols(formula, data=train).fit()
            return HoleScoreModel(result, formula, len(train))
        except Exception:
            continue

    raise ValueError("Not enough training data to fit a regression model.")


def predict_hole_scores(model: HoleScoreModel, target_holes: pd.DataFrame) -> pd.DataFrame:
    """Predict a score for each hole in `target_holes` (needs par, yardage,
    stroke_index columns) from a model already fit by fit_hole_score_model().

    Returns target_holes with an added 'predicted_score' column (rounded to
    1 decimal place).
    """
    target = target_holes.copy()
    target["par"] = target["par"].astype(int)

    predicted_to_par = model.result.predict(target)

    result = target_holes.copy()
    result["predicted_score"] = (target["par"] + predicted_to_par).round(1)
    return result
