"""One extractor for the fields the quality rules (and dedup) look at.

A job document may come straight from the model (any extra keys pass through
`_persist_jobs`) or from Mongo; either way the rules only ever see the
stripped strings produced here, so a `None` or a non-string value can never
reach a regex.
"""
from __future__ import annotations

SCORED_FIELDS: tuple[str, ...] = ("title", "description", "company", "salary_range")


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def extract_fields(job: dict) -> dict[str, str]:
    """Return `{field: stripped text}` for every scored field."""
    return {name: _as_text(job.get(name)) for name in SCORED_FIELDS}
