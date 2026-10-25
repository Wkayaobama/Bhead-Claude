"""Quality rules, bands and threshold as data.

A `Rule` is interpreted by `engine.evaluate`; it never holds code. Adding a
check means adding a row here (and, for a new predicate kind, one branch in
the engine). The payload of `/api/monitor/quality-config` is generated from
this module, so the UI copy follows the registry instead of restating it.

Scores start at 100 and lose each fired rule's `penalty`, floored at 0. A
job is flagged when its score is below `FLAG_THRESHOLD`; `BANDS` give the
operator-facing reading of a score and must tile 0..100.

Predicate kinds (see engine.py):
  shorter_than             len(field) <  n
  longer_than              len(field) >  n
  matches                  regex found in any listed field (fires once; the
                           label may name the first matching `{field}`)
  repeated_words           > min_words words and unique/total < max_unique_ratio
  missing                  field is empty
  shorter_than_if_present  field non-empty and len(field) < n
  lacks_if_present         field non-empty and regex NOT found
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Rule:
    key: str
    label: str
    penalty: int
    kind: str
    fields: tuple[str, ...]
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Band:
    key: str
    label: str
    min_score: int
    max_score: int
    tone: str  # good | warn | bad — a hint for the UI, not a style


FLAG_THRESHOLD = 70

BANDS: tuple[Band, ...] = (
    Band("clean", "Clean", 90, 100, "good"),
    Band("review", "Needs review", FLAG_THRESHOLD, 89, "warn"),
    Band("flagged", "Flagged", 0, FLAG_THRESHOLD - 1, "bad"),
)

_HTML = r"<[a-zA-Z][^>]*>|&[a-zA-Z]{2,6};"
_TEMPLATE = r"\{\{.*?\}\}|\[\[.*?\]\]|<%.*?%>"
_URL = r"https?://\S+"
_CONTROL = r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"

RULES: tuple[Rule, ...] = (
    Rule("title_too_short", "Title missing or too short", 40,
         "shorter_than", ("title",), {"n": 3}),
    Rule("title_too_long", "Title suspiciously long (>200 chars)", 15,
         "longer_than", ("title",), {"n": 200}),
    Rule("url_in_title", "URL found inside job title", 20,
         "matches", ("title",), {"pattern": _URL}),
    Rule("title_repeated_words", "Title contains heavily repeated words", 10,
         "repeated_words", ("title",), {"min_words": 4, "max_unique_ratio": 0.65}),
    Rule("html_artifacts", "HTML artefacts in {field}", 20,
         "matches", ("title", "description", "company"),
         {"pattern": _HTML, "flags": ["I"]}),
    Rule("template_tokens", "Template/placeholder tokens detected", 30,
         "matches", ("title", "description"), {"pattern": _TEMPLATE, "flags": ["S"]}),
    Rule("control_chars", "Control/binary characters detected", 25,
         "matches", ("title", "description"), {"pattern": _CONTROL}),
    Rule("company_missing", "Company name absent", 10,
         "missing", ("company",)),
    Rule("description_too_brief", "Description too brief (<15 chars)", 10,
         "shorter_than_if_present", ("description",), {"n": 15}),
    Rule("salary_no_digits", "Salary range contains no numbers", 5,
         "lacks_if_present", ("salary_range",), {"pattern": r"\d"}),
)
