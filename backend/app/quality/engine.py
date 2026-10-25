"""Pure interpreter over the quality registry.

`evaluate` takes a job document and returns a `QualityResult`; it reads no
settings, touches no database and has no clock, so the same input always
yields the same score and the tests need no fixtures beyond a dict.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from app.quality.extractor import SCORED_FIELDS, extract_fields
from app.quality.registry import BANDS, FLAG_THRESHOLD, RULES, Band, Rule

KINDS: frozenset[str] = frozenset({
    "shorter_than",
    "longer_than",
    "matches",
    "repeated_words",
    "missing",
    "shorter_than_if_present",
    "lacks_if_present",
})

_FLAG_NAMES = {"I": re.IGNORECASE, "S": re.DOTALL, "M": re.MULTILINE}

# The UI keys its styling on these; a typo here would otherwise surface as a
# crashed Monitor page for every viewer.
TONES: frozenset[str] = frozenset({"good", "warn", "bad"})


@dataclass(frozen=True)
class QualityResult:
    score: int
    issues: tuple[str, ...]
    fired: tuple[str, ...]
    flagged: bool
    band: str


@lru_cache(maxsize=None)
def _compile(pattern: str, flags: tuple[str, ...]) -> re.Pattern:
    value = 0
    for name in flags:
        value |= _FLAG_NAMES[name]
    return re.compile(pattern, value)


def _regex(rule: Rule) -> re.Pattern:
    return _compile(rule.params["pattern"], tuple(rule.params.get("flags", ())))


def _fire(rule: Rule, fields: dict[str, str]) -> str | None:
    """Return the issue label when `rule` fires for `fields`, else None."""
    kind = rule.kind
    if kind == "matches":
        rx = _regex(rule)
        for name in rule.fields:
            if rx.search(fields[name]):
                return rule.label.format(field=name)
        return None

    value = fields[rule.fields[0]]
    if kind == "shorter_than":
        hit = len(value) < rule.params["n"]
    elif kind == "longer_than":
        hit = len(value) > rule.params["n"]
    elif kind == "repeated_words":
        words = value.lower().split()
        hit = (
            len(words) > rule.params["min_words"]
            and len(set(words)) / len(words) < rule.params["max_unique_ratio"]
        )
    elif kind == "missing":
        hit = not value
    elif kind == "shorter_than_if_present":
        hit = bool(value) and len(value) < rule.params["n"]
    elif kind == "lacks_if_present":
        hit = bool(value) and not _regex(rule).search(value)
    else:  # pragma: no cover — validate_registry rejects unknown kinds
        raise ValueError(f"unknown predicate kind {kind!r}")
    return rule.label if hit else None


def band_for(score: int, bands: Iterable[Band] = BANDS) -> Band:
    for band in bands:
        if band.min_score <= score <= band.max_score:
            return band
    raise ValueError(f"no band covers score {score}")


def evaluate(
    job: dict,
    *,
    registry: Iterable[Rule] = RULES,
    bands: Iterable[Band] = BANDS,
    threshold: int = FLAG_THRESHOLD,
) -> QualityResult:
    fields = extract_fields(job)
    score = 100
    issues: list[str] = []
    fired: list[str] = []
    for rule in registry:
        label = _fire(rule, fields)
        if label is not None:
            issues.append(label)
            fired.append(rule.key)
            score -= rule.penalty
    score = max(0, score)
    return QualityResult(
        score=score,
        issues=tuple(issues),
        fired=tuple(fired),
        flagged=score < threshold,
        band=band_for(score, bands).key,
    )


def describe(
    registry: Iterable[Rule] = RULES,
    bands: Iterable[Band] = BANDS,
    threshold: int = FLAG_THRESHOLD,
) -> dict:
    """Registry metadata for API payloads so UI copy is rendered, not restated."""
    return {
        "threshold": threshold,
        "max_score": 100,
        "bands": [
            {
                "key": b.key,
                "label": b.label,
                "min_score": b.min_score,
                "max_score": b.max_score,
                "tone": b.tone,
            }
            for b in bands
        ],
        "rules": [
            {
                "key": r.key,
                "label": r.label,
                "penalty": r.penalty,
                "kind": r.kind,
                "fields": list(r.fields),
                "params": {k: v for k, v in r.params.items()},
            }
            for r in registry
        ],
    }


def validate_registry(
    registry: Iterable[Rule] = RULES,
    bands: Iterable[Band] = BANDS,
    threshold: int = FLAG_THRESHOLD,
) -> None:
    """Fail fast on a registry that could not be interpreted or explained."""
    rules = tuple(registry)
    keys = [r.key for r in rules]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate rule keys: {sorted(k for k in keys if keys.count(k) > 1)}")
    for rule in rules:
        if rule.kind not in KINDS:
            raise ValueError(f"rule {rule.key}: unknown kind {rule.kind!r}")
        if rule.penalty <= 0:
            raise ValueError(f"rule {rule.key}: penalty must be positive")
        if not rule.fields:
            raise ValueError(f"rule {rule.key}: needs at least one field")
        unknown = set(rule.fields) - set(SCORED_FIELDS)
        if unknown:
            raise ValueError(f"rule {rule.key}: fields {sorted(unknown)} are not extracted")
        if rule.kind in ("matches", "lacks_if_present"):
            if "pattern" not in rule.params:
                raise ValueError(f"rule {rule.key}: {rule.kind} needs params.pattern")
            for flag in rule.params.get("flags", ()):
                if flag not in _FLAG_NAMES:
                    raise ValueError(f"rule {rule.key}: unknown regex flag {flag!r}")
            re.compile(rule.params["pattern"])
        if rule.kind in ("shorter_than", "longer_than", "shorter_than_if_present"):
            if not isinstance(rule.params.get("n"), int):
                raise ValueError(f"rule {rule.key}: {rule.kind} needs an integer params.n")
        if rule.kind == "repeated_words":
            for p in ("min_words", "max_unique_ratio"):
                if p not in rule.params:
                    raise ValueError(f"rule {rule.key}: repeated_words needs params.{p}")
        if "{field}" in rule.label and rule.kind != "matches":
            raise ValueError(f"rule {rule.key}: only 'matches' labels may use {{field}}")
        try:
            rule.label.format(field="x")
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError(
                f"rule {rule.key}: label {rule.label!r} is not a valid template ({exc})"
            ) from None

    ordered = sorted(bands, key=lambda b: b.min_score)
    for band in ordered:
        if band.tone not in TONES:
            raise ValueError(f"band {band.key}: tone must be one of {sorted(TONES)}")
    if not ordered or ordered[0].min_score != 0 or ordered[-1].max_score != 100:
        raise ValueError("bands must start at 0 and end at 100")
    for lower, upper in zip(ordered, ordered[1:]):
        if lower.max_score + 1 != upper.min_score:
            raise ValueError(f"bands {lower.key} and {upper.key} do not tile")
    if not any(b.min_score == threshold for b in ordered):
        raise ValueError(f"no band starts at the flag threshold {threshold}")
