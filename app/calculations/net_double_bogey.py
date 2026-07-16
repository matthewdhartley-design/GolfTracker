import math


def round_half_up(value: float) -> int:
    """Round to the nearest whole number, halves rounding up -- the WHS
    convention (Python's built-in round() uses round-half-to-even instead).
    """
    return math.floor(value + 0.5)


def course_handicap(handicap_index: float, slope_rating: float, course_rating: float, par: float) -> int:
    """WHS Course Handicap: Handicap Index * (Slope Rating / 113) + (Course
    Rating - Par), rounded to the nearest whole number.

    Clamped to a minimum of 0. A negative raw value would mean a "plus"
    handicap player who gives strokes back rather than receiving them --
    that reverse-allocation case isn't implemented here (out of scope for
    this project), so it's simplified to "receives no strokes" instead.
    """
    raw = handicap_index * (slope_rating / 113) + (course_rating - par)
    return max(0, round_half_up(raw))


def strokes_received(course_hcp: int, stroke_index: int) -> int:
    """Strokes received on a single hole under the standard WHS allocation:
    one stroke per hole for every full 18 in the course handicap, plus one
    additional stroke on the hardest holes (lowest stroke index) to use up
    the remainder.
    """
    base = course_hcp // 18
    extra = 1 if stroke_index <= (course_hcp % 18) else 0
    return base + extra


def max_hole_score(par: int, stroke_index: int, course_hcp: int) -> int:
    """Net double bogey: the most a hole can count for handicap purposes --
    par, plus two strokes, plus any handicap strokes received on that hole.
    """
    return par + 2 + strokes_received(course_hcp, stroke_index)


def capped_hole_score(actual_score: int, par: int, stroke_index: int, course_hcp: int) -> int:
    """The score to use for handicap purposes: the actual score, capped at
    net double bogey for that hole.
    """
    return min(actual_score, max_hole_score(par, stroke_index, course_hcp))
