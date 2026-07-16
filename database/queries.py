import pandas as pd
from sqlalchemy import text

from database.connection import get_db_connection


def seed_course_tees_from_rounds() -> int:
    """Insert one placeholder row per distinct (course_name, tee_color) combo
    found in golf.golf_rounds that isn't already in golf.golf_course_tees.

    golf.golf_course_tees stores course/tee-level data (par, yardage,
    course_rating, slope_rating), none of which exists in golf.golf_rounds.
    Each new combo is seeded with 0 for these required numeric columns as
    placeholders — real values must be filled in later from actual
    scorecards. Per-hole data (hole_number, stroke_index, etc.) lives in a
    separate table.

    Returns the number of rows inserted.
    """
    query = text("""
        INSERT INTO golf.golf_course_tees
            (course_name, tee_color, par, yardage, course_rating, slope_rating)
        SELECT DISTINCT course_name, tee_color_played, 0, 0, 0, 0
        FROM golf.golf_rounds
        ON CONFLICT (course_name, tee_color) DO NOTHING
    """)
    with get_db_connection() as conn:
        result = conn.execute(query)
        conn.commit()
        return result.rowcount


def get_rounds_with_hole_counts() -> pd.DataFrame:
    """Fetch all golf.golf_rounds with a count of how many golf.golf_hole_details
    rows exist for each round, sorted chronologically by date.
    """
    query = """
        SELECT r.round_id, r.date, r.course_name, r.tee_color_played,
               r.total_score,
               COUNT(h.detail_id) AS hole_scores_recorded
        FROM golf.golf_rounds r
        LEFT JOIN golf.golf_hole_details h ON r.round_id = h.round_id
        GROUP BY r.round_id, r.date, r.course_name, r.tee_color_played, r.total_score
        ORDER BY r.date ASC
    """
    with get_db_connection() as conn:
        return pd.read_sql(query, conn)


def get_hole_info() -> pd.DataFrame:
    """Fetch all golf.golf_hole_info rows (hole-by-hole par/yardage/stroke
    index), sorted by course, tee, and hole number.
    """
    query = """
        SELECT course_name, tee_color, hole_number, par, yardage, stroke_index
        FROM golf.golf_hole_info
        ORDER BY course_name, tee_color, hole_number
    """
    with get_db_connection() as conn:
        return pd.read_sql(query, conn)


def get_incomplete_hole_data() -> pd.DataFrame:
    """List every golf.golf_course_tees row that doesn't have a complete
    18-hole golf.golf_hole_info set yet -- 0 holes recorded means no
    hole-by-hole data exists at all; 1-17 means a partial/incomplete set.
    Used to flag exactly which course/tee combos still need hole data supplied.
    """
    query = """
        SELECT t.course_name, t.tee_color,
               COALESCE(h.hole_count, 0) AS hole_count
        FROM golf.golf_course_tees t
        LEFT JOIN (
            SELECT course_name, tee_color, COUNT(*) AS hole_count
            FROM golf.golf_hole_info
            GROUP BY course_name, tee_color
        ) h ON t.course_name = h.course_name AND t.tee_color = h.tee_color
        WHERE COALESCE(h.hole_count, 0) < 18
        ORDER BY t.course_name, t.tee_color
    """
    with get_db_connection() as conn:
        return pd.read_sql(query, conn)


def upsert_hole_info(course_name: str, tee_color: str, holes: list[dict]) -> None:
    """Insert or update golf.golf_hole_info rows for a course/tee, then sync
    golf.golf_course_tees.yardage to the new hole-level total.

    `holes` is a list of dicts with keys hole_number, par, yardage, stroke_index.
    """
    insert_query = text("""
        INSERT INTO golf.golf_hole_info
            (course_name, tee_color, hole_number, par, yardage, stroke_index)
        VALUES (:course_name, :tee_color, :hole_number, :par, :yardage, :stroke_index)
        ON CONFLICT (course_name, tee_color, hole_number) DO UPDATE
        SET par = EXCLUDED.par, yardage = EXCLUDED.yardage, stroke_index = EXCLUDED.stroke_index
    """)
    sync_yardage_query = text("""
        UPDATE golf.golf_course_tees
        SET yardage = (
            SELECT SUM(yardage) FROM golf.golf_hole_info
            WHERE course_name = :course_name AND tee_color = :tee_color
        )
        WHERE course_name = :course_name AND tee_color = :tee_color
    """)
    with get_db_connection() as conn:
        for hole in holes:
            conn.execute(insert_query, {
                "course_name": course_name,
                "tee_color": tee_color,
                "hole_number": hole["hole_number"],
                "par": hole["par"],
                "yardage": hole["yardage"],
                "stroke_index": hole["stroke_index"],
            })
        conn.execute(sync_yardage_query, {"course_name": course_name, "tee_color": tee_color})
        conn.commit()


def get_known_course_tees() -> pd.DataFrame:
    """List all (course_name, tee_color) combos from golf.golf_course_tees,
    for populating course/tee selection dropdowns.
    """
    query = "SELECT course_name, tee_color FROM golf.golf_course_tees ORDER BY course_name, tee_color"
    with get_db_connection() as conn:
        return pd.read_sql(query, conn)


def find_round_by_course_and_date(course_name: str, round_date) -> dict | None:
    """Look for an existing golf.golf_rounds row for this course on this date.
    Returns {"round_id", "total_score"} if found, else None.
    """
    query = text("""
        SELECT round_id, total_score FROM golf.golf_rounds
        WHERE course_name = :course_name AND date = :round_date
    """)
    with get_db_connection() as conn:
        row = conn.execute(query, {"course_name": course_name, "round_date": round_date}).fetchone()
        return {"round_id": row[0], "total_score": row[1]} if row else None


def create_round(round_date, course_name: str, tee_color: str, total_score: int) -> int:
    """Insert a new golf.golf_rounds row and return its round_id."""
    query = text("""
        INSERT INTO golf.golf_rounds (date, course_name, tee_color_played, total_score)
        VALUES (:round_date, :course_name, :tee_color, :total_score)
        RETURNING round_id
    """)
    with get_db_connection() as conn:
        round_id = conn.execute(query, {
            "round_date": round_date, "course_name": course_name,
            "tee_color": tee_color, "total_score": total_score,
        }).scalar()
        conn.commit()
        return round_id


def upsert_hole_details(round_id: int, holes: list[dict]) -> None:
    """Insert or update golf.golf_hole_details rows for a round.
    `holes` is a list of dicts with keys hole_number, score.
    """
    query = text("""
        INSERT INTO golf.golf_hole_details (round_id, hole_number, score)
        VALUES (:round_id, :hole_number, :score)
        ON CONFLICT (round_id, hole_number) DO UPDATE SET score = EXCLUDED.score
    """)
    with get_db_connection() as conn:
        for hole in holes:
            conn.execute(query, {
                "round_id": round_id, "hole_number": hole["hole_number"], "score": hole["score"],
            })
        conn.commit()


def get_courses_with_hole_score_data() -> list[str]:
    """List courses that have at least one round with both hole-by-hole
    scores (golf_hole_details) and matching hole-by-hole par (golf_hole_info).
    """
    query = """
        SELECT DISTINCT r.course_name
        FROM golf.golf_hole_details d
        JOIN golf.golf_rounds r ON d.round_id = r.round_id
        JOIN golf.golf_hole_info hi
          ON hi.course_name = r.course_name AND hi.tee_color = r.tee_color_played
         AND hi.hole_number = d.hole_number
        ORDER BY r.course_name
    """
    with get_db_connection() as conn:
        return pd.read_sql(query, conn)["course_name"].tolist()


def get_hole_scores_with_par(course_name: str) -> pd.DataFrame:
    """For a given course, return every recorded hole_number/score/par row
    (plus which tee that round was played on) across all rounds with
    hole-level detail, using each round's own tee to look up the correct par
    per hole.
    """
    query = text("""
        SELECT d.hole_number, d.score, hi.par, r.tee_color_played
        FROM golf.golf_hole_details d
        JOIN golf.golf_rounds r ON d.round_id = r.round_id
        JOIN golf.golf_hole_info hi
          ON hi.course_name = r.course_name AND hi.tee_color = r.tee_color_played
         AND hi.hole_number = d.hole_number
        WHERE r.course_name = :course_name
    """)
    with get_db_connection() as conn:
        return pd.read_sql(query, conn, params={"course_name": course_name})


def get_all_hole_scores_with_par() -> pd.DataFrame:
    """Return every recorded hole_number/score/par/yardage/stroke_index row,
    across every round that has both hole-level scores (golf_hole_details)
    and matching hole-level info (golf_hole_info) for the course/tee it was
    played on, tagged with round_id/date/course_name/tee_color_played/
    total_score so callers can group by round.
    """
    query = """
        SELECT r.round_id, r.date, r.course_name, r.tee_color_played, r.total_score,
               d.hole_number, d.score, hi.par, hi.yardage, hi.stroke_index
        FROM golf.golf_hole_details d
        JOIN golf.golf_rounds r ON d.round_id = r.round_id
        JOIN golf.golf_hole_info hi
          ON hi.course_name = r.course_name AND hi.tee_color = r.tee_color_played
         AND hi.hole_number = d.hole_number
        ORDER BY r.date, d.hole_number
    """
    with get_db_connection() as conn:
        return pd.read_sql(query, conn)


def get_macro_rounds() -> pd.DataFrame:
    """Fetch all golf.golf_rounds joined with their course/tee rating,
    slope, and par, sorted chronologically by date.

    Uses a LEFT JOIN so rounds without a matching golf_course_tees row still
    appear (with null course_rating/slope_rating/course_par) rather than
    disappearing from totals and best-score stats.
    """
    query = """
        SELECT r.round_id, r.date, r.course_name, r.tee_color_played,
               r.total_score, r.handicap_after_round,
               t.course_rating, t.slope_rating, t.par AS course_par
        FROM golf.golf_rounds r
        LEFT JOIN golf.golf_course_tees t
          ON r.course_name = t.course_name AND r.tee_color_played = t.tee_color
        ORDER BY r.date ASC
    """
    with get_db_connection() as conn:
        return pd.read_sql(query, conn)
