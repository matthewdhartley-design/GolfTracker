import os

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

load_dotenv()

_MODEL = "gemini-2.5-flash"

_PROMPT = (
    "This is a photo of a golf scorecard for a single round that was played. "
    "Read the course name, the tee color/marker played (if shown), the date "
    "the round was played (if handwritten or printed anywhere on the card, in "
    "ISO yyyy-mm-dd format), and the player's gross score for every hole, 1 "
    "through 18. If a value isn't visible or legible, omit it rather than "
    "guessing."
)


class HoleScore(BaseModel):
    hole_number: int
    score: int


class ScorecardExtraction(BaseModel):
    course_name: str
    tee_color: str | None = None
    date: str | None = None
    holes: list[HoleScore]


def analyze_scorecard_image(image_bytes: bytes, mime_type: str = "image/png") -> ScorecardExtraction:
    """Send a scorecard photo to Gemini and return structured hole-by-hole
    scores plus whatever course/tee/date info is visible on the card.

    Raises RuntimeError if GEMINI_API_KEY isn't configured.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not found in .env file. Add one to use Scorecard AI.")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=_MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            _PROMPT,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ScorecardExtraction,
        ),
    )
    return ScorecardExtraction.model_validate_json(response.text)
