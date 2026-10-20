"""The Review JSON schema that the engine must return."""

import json
from importlib.resources import files

REVIEW_SCHEMA_TEXT: str = (
    files("review_agent").joinpath("review.schema.json").read_text(encoding="utf-8")
)
REVIEW_SCHEMA: dict = json.loads(REVIEW_SCHEMA_TEXT)
