"""The quality engine is pure: a dict in, a QualityResult out, no fixtures."""
from __future__ import annotations

import re

import pytest

from app.quality import (
    BANDS,
    FLAG_THRESHOLD,
    RULES,
    Band,
    Rule,
    band_for,
    describe,
    evaluate,
    extract_fields,
    validate_registry,
)

CLEAN_JOB = {
    "title": "Senior Backend Engineer",
    "company": "Acme AG",
    "location": "Bern",
    "description": "Build and operate the payments platform with a small team.",
    "salary_range": "CHF 120k–140k",
}


# ---------------------------------------------------------------------------
# Reference implementation: the heuristics as they shipped in the generated
# monitor route, kept verbatim so the registry refactor is proven equivalent.
# ---------------------------------------------------------------------------

_HTML_RE = re.compile(r"<[a-zA-Z][^>]*>|&[a-zA-Z]{2,6};", re.IGNORECASE)
_TEMPLATE_RE = re.compile(r"\{\{.*?\}\}|\[\[.*?\]\]|<%.*?%>", re.DOTALL)
_URL_RE = re.compile(r"https?://\S+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _legacy_analyze_quality(job: dict) -> tuple[int, list[str]]:
    score = 100
    issues: list[str] = []
    title = (job.get("title") or "").strip()
    desc = (job.get("description") or "").strip()
    company = (job.get("company") or "").strip()
    if len(title) < 3:
        issues.append("Title missing or too short")
        score -= 40
    elif len(title) > 200:
        issues.append("Title suspiciously long (>200 chars)")
        score -= 15
    if _URL_RE.search(title):
        issues.append("URL found inside job title")
        score -= 20
    words = title.lower().split()
    if len(words) > 4 and len(set(words)) / len(words) < 0.65:
        issues.append("Title contains heavily repeated words")
        score -= 10
    for field_name, field_val in [("title", title), ("description", desc), ("company", company)]:
        if _HTML_RE.search(field_val):
            issues.append(f"HTML artefacts in {field_name}")
            score -= 20
            break
    for field_val in [title, desc]:
        if _TEMPLATE_RE.search(field_val):
            issues.append("Template/placeholder tokens detected")
            score -= 30
            break
    if _CONTROL_RE.search(title + desc):
        issues.append("Control/binary characters detected")
        score -= 25
    if not company:
        issues.append("Company name absent")
        score -= 10
    if desc and len(desc) < 15:
        issues.append("Description too brief (<15 chars)")
        score -= 10
    salary = (job.get("salary_range") or "").strip()
    if salary and not re.search(r"\d", salary):
        issues.append("Salary range contains no numbers")
        score -= 5
    return max(0, score), issues


PARITY_JOBS = [
    CLEAN_JOB,
    {},
    {"title": "AI", "company": "", "description": "short", "salary_range": "competitive"},
    {"title": "Dev <b>urgent</b>", "company": "X &amp; Y", "description": "<p>Hi there friends</p>"},
    {"title": "Go go go go go go", "company": "Loop", "description": "{{ job.description }}"},
    {"title": "Apply at https://jobs.example.com now", "company": "Co", "description": "Long enough text here"},
    {"title": "x" * 250, "company": "Co", "description": "Fine description text"},
    {"title": "Data\x00Engineer", "company": "Co", "description": "ok\x07 description long"},
    {"title": None, "company": None, "description": None, "salary_range": None},
    {"title": 12345, "company": 7, "description": ["list"], "salary_range": "80k"},
]


@pytest.mark.parametrize("job", PARITY_JOBS, ids=range(len(PARITY_JOBS)))
def test_engine_matches_legacy_heuristics(job):
    legacy_score, legacy_issues = _legacy_analyze_quality(
        {k: (v if isinstance(v, str) or v is None else str(v)) for k, v in job.items()}
    )
    result = evaluate(job)
    assert result.score == legacy_score
    assert list(result.issues) == legacy_issues
    assert result.flagged == (legacy_score < 70)


def test_clean_job_scores_full_marks():
    result = evaluate(CLEAN_JOB)
    assert result.score == 100
    assert result.issues == ()
    assert result.fired == ()
    assert result.band == "clean"
    assert result.flagged is False


def test_issue_label_names_the_matching_field():
    result = evaluate({**CLEAN_JOB, "description": "<div>Great role</div> with a long enough text"})
    assert "HTML artefacts in description" in result.issues
    assert "html_artifacts" in result.fired
    assert result.score == 80
    assert result.band == "review"
    assert result.flagged is False


def test_score_floors_at_zero():
    job = {
        "title": "<b>go go go go https://x.y {{t}}</b>\x00",
        "company": "",
        "description": "{{ x }}",
        "salary_range": "lots",
    }
    result = evaluate(job)
    assert result.score == 0
    assert result.band == "flagged"
    assert result.flagged is True


def test_flag_threshold_boundary_is_exclusive():
    just_above = (Rule("p30", "p30", 100 - FLAG_THRESHOLD, "missing", ("company",)),)
    just_below = (Rule("p31", "p31", 100 - FLAG_THRESHOLD + 1, "missing", ("company",)),)
    job = {"title": "Role", "company": ""}
    assert evaluate(job, registry=just_above).flagged is False
    assert evaluate(job, registry=just_above).score == FLAG_THRESHOLD
    assert evaluate(job, registry=just_below).flagged is True


def test_bands_tile_the_whole_score_range():
    for score in range(0, 101):
        band_for(score)  # raises if any score were uncovered
    assert band_for(100).key == "clean"
    assert band_for(FLAG_THRESHOLD).key == "review"
    assert band_for(FLAG_THRESHOLD - 1).key == "flagged"


def test_describe_exposes_registry_as_data():
    payload = describe()
    assert payload["threshold"] == FLAG_THRESHOLD
    assert [b["key"] for b in payload["bands"]] == [b.key for b in BANDS]
    assert [r["key"] for r in payload["rules"]] == [r.key for r in RULES]
    html = next(r for r in payload["rules"] if r["key"] == "html_artifacts")
    assert html["fields"] == ["title", "description", "company"]
    assert html["penalty"] == 20
    assert "pattern" in html["params"]


def test_extract_fields_normalises_missing_and_non_string_values():
    fields = extract_fields({"title": None, "company": 42, "description": "  padded  "})
    assert fields == {"title": "", "description": "padded", "company": "42", "salary_range": ""}


def test_shipped_registry_is_valid():
    validate_registry(RULES, BANDS, FLAG_THRESHOLD)


@pytest.mark.parametrize(
    "bad_rules, message",
    [
        ((Rule("a", "A", 5, "missing", ("company",)), Rule("a", "B", 5, "missing", ("title",))), "duplicate"),
        ((Rule("a", "A", 5, "teleport", ("company",)),), "unknown kind"),
        ((Rule("a", "A", 0, "missing", ("company",)),), "positive"),
        ((Rule("a", "A", 5, "missing", ("salary",)),), "not extracted"),
        ((Rule("a", "A", 5, "matches", ("title",), {"pattern": "("}),), None),
        ((Rule("a", "A", 5, "matches", ("title",), {"pattern": "x", "flags": ["Z"]}),), "flag"),
        ((Rule("a", "A in {field}", 5, "missing", ("company",)),), "{field}"),
        ((Rule("a", "A", 5, "shorter_than", ("title",), {"n": "3"}),), "integer"),
        ((Rule("a", "Matches {placeholder}", 5, "matches", ("title",), {"pattern": "x"}),), "template"),
    ],
)
def test_validate_registry_rejects_malformed_rules(bad_rules, message):
    with pytest.raises((ValueError, re.error)) as excinfo:
        validate_registry(bad_rules, BANDS, FLAG_THRESHOLD)
    if message:
        assert message in str(excinfo.value)


def test_validate_registry_rejects_bands_that_do_not_tile():
    gap = (Band("a", "A", 0, 50, "bad"), Band("b", "B", 52, 100, "good"))
    with pytest.raises(ValueError, match="tile"):
        validate_registry(RULES, gap, 52)
    no_threshold_band = (Band("a", "A", 0, 59, "bad"), Band("b", "B", 60, 100, "good"))
    with pytest.raises(ValueError, match="threshold"):
        validate_registry(RULES, no_threshold_band, 70)


def test_validate_registry_rejects_unknown_band_tones():
    bad_tone = (Band("a", "A", 0, 69, "bad"), Band("b", "B", 70, 100, "warning"))
    with pytest.raises(ValueError, match="tone"):
        validate_registry(RULES, bad_tone, 70)
