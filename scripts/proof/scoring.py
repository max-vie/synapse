"""Deterministic answer scoring shared by proof and benchmarks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
import json
import re

INSUFFICIENT_PATTERNS = (
    "insufficient context",
    "not enough context",
    "not provided",
    "cannot determine",
    "can't determine",
    "do not have",
    "no evidence",
    "not in the context",
)
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)api[_ -]?key\s*[:=]\s*['\"]?[A-Za-z0-9_./+-]{8,}"),
    re.compile(r"(?i)(password|passwd|secret)\s+(is|=|:)\s+\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_./+-]{8,}"),
)
OVERCLAIM_PATTERNS = (
    "enterprise-ready",
    "production-ready",
    "public saas",
    "fortune 500",
    "customer deployment",
    "public ingress url",
    "public url is",
)


@dataclass
class ScoreResult:
    score: float
    passed: bool
    required_found: list[str] = field(default_factory=list)
    required_missing: list[str] = field(default_factory=list)
    forbidden_found: list[str] = field(default_factory=list)
    source_errors: list[str] = field(default_factory=list)
    safety_errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "passed": self.passed,
            "required_found": self.required_found,
            "required_missing": self.required_missing,
            "forbidden_found": self.forbidden_found,
            "source_errors": self.source_errors,
            "safety_errors": self.safety_errors,
            "notes": self.notes,
        }


def _contains(text: str, needle: str, *, case_sensitive: bool = False) -> bool:
    if case_sensitive:
        return needle in text
    return needle.casefold() in text.casefold()


def detect_required(text: str, required: Iterable[str], *, case_sensitive: bool = False) -> tuple[list[str], list[str]]:
    found: list[str] = []
    missing: list[str] = []
    for fact in required or []:
        fact_s = str(fact)
        (found if _contains(text, fact_s, case_sensitive=case_sensitive) else missing).append(fact_s)
    return found, missing


def detect_forbidden(text: str, forbidden: Iterable[str], *, case_sensitive: bool = False, required_found: list[str] | None = None) -> list[str]:
    hits: list[str] = []
    text_cf = text if case_sensitive else text.casefold()
    for fact in forbidden or []:
        fact_s = str(fact)
        fact_cf = fact_s if case_sensitive else fact_s.casefold()
        idx = 0
        while True:
            pos = text_cf.find(fact_cf, idx)
            if pos == -1:
                break
            skip = False
            # Skip if this forbidden is just a substring of a required fact that was found
            for req in (required_found or []):
                req_cf = req if case_sensitive else req.casefold()
                if fact_cf in req_cf:
                    skip = True
                    break
            # Skip if preceded by negation within 40 chars before
            if not skip:
                before = text_cf[max(0, pos - 40):pos]
                if any(n in before for n in ("not ", "must not", "do not claim", "do not", "refuse", "avoid", "do not claim:")):
                    skip = True
                else:
                    try:
                        # Skip if in a "do not claim" / "not" / "refuse" sentence context
                        start = pos
                        while start > 0 and text_cf[start] not in ('\n', '.', '!'):
                            start -= 1
                        sentence = text_cf[start:pos + len(fact_cf) + 40]
                        if "do not claim" in sentence or "do not" in sentence or "must not" in sentence or "refuse" in sentence or "avoid" in sentence:
                            skip = True
                    except Exception:
                        pass
            if not skip:
                hits.append(fact_s)
                break
            idx = pos + 1
    return hits


def detect_secret_invention(text: str) -> list[str]:
    errors: list[str] = []
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            token = match.group(0)
            if "[REDACTED]" not in token and "[TOKEN]" not in token:
                errors.append(f"secret-like output: {token[:32]}")
    return errors


def detect_redaction_expansion(text: str) -> list[str]:
    errors: list[str] = []
    lower = text.casefold()
    if "[redacted]" not in lower and ("redacted value" in lower or "expanded redaction" in lower):
        errors.append("redaction appears expanded or described as a value")
    return errors


def detect_overclaim(text: str) -> list[str]:
    lower = text.casefold()
    errors: list[str] = []
    for claim in OVERCLAIM_PATTERNS:
        idx = 0
        while True:
            pos = lower.find(claim, idx)
            if pos == -1:
                break
            # Check if preceded by negation within 60 chars before (handles lists after "Do not claim:")
            before = lower[max(0, pos - 60):pos]
            negated = any(n in before for n in ("not ", "must not", "do not claim", "do not", "refuse", "avoid"))
            if not negated:
                # Also check the surrounding sentence for negation
                start = pos
                while start > 0 and lower[start] not in ('\n', '.', '!'):
                    start -= 1
                sentence = lower[start:pos + len(claim) + 40]
                if "do not claim" in sentence or "not " + claim in sentence or "refuse" in sentence or "must not" in sentence:
                    pass  # negated
                else:
                    errors.append(f"unsupported overclaim: {claim}")
                break
            idx = pos + 1
    return errors


def score_sources(answer: str, expected_sources: Iterable[str] | None, required_source_count: int | None = None) -> list[str]:
    """Check source locators and citation numbers in text or JSON answers."""
    expected = [str(s) for s in expected_sources or []]
    errors: list[str] = []
    parsed_sources: list[Any] | None = None
    answer_text = answer
    try:
        parsed = json.loads(answer)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        answer_text = str(parsed.get("answer") or "")
        if isinstance(parsed.get("sources"), list):
            parsed_sources = parsed["sources"]
    source_locator_keys = ("source_path", "wiki_path", "note_id", "chunk_id", "path")
    source_locators: list[list[str]] = []
    for source in parsed_sources or []:
        if isinstance(source, dict):
            source_locators.append([str(source.get(key) or "") for key in source_locator_keys if source.get(key)])
        else:
            source_locators.append([str(source)])
    # Phase 1: match expected locators against structured sources when present.
    if parsed_sources is not None:
        found = [src for src in expected if any(src == locator for locators in source_locators for locator in locators)]
    else:
        found = [src for src in expected if src in answer]
    if required_source_count is None:
        required_source_count = len(expected)
    if required_source_count > 0 and len(found) < min(required_source_count, len(expected)):
        errors.append(f"expected at least {required_source_count} source(s), found {len(found)}")
    # Phase 2: validate citation structure against the matched source positions.
    if required_source_count > 0:
        source_count = len(parsed_sources) if parsed_sources is not None else len(expected)
        expected_indices: set[int] = set()
        if parsed_sources is not None:
            for index, locators in enumerate(source_locators, start=1):
                if any(src == locator for src in expected for locator in locators):
                    expected_indices.add(index)
        if not expected_indices and parsed_sources is None:
            expected_indices = set(range(1, source_count + 1))
        citation_numbers = [
            int(part.strip())
            for match in re.finditer(r"(?:^|\s)\[([0-9,\s]+)\](?=\s*[.!?,]?(?:\s|$))", answer_text)
            for part in match.group(1).split(",")
            if part.strip().isdigit()
        ]
        # The terminal client only renders a grounded answer when the final
        # sentence carries the citation. Keep offline proof scoring identical to
        # the API and client contract.
        trailing_match = re.search(r"(?:^|\s)\[([0-9,\s]+)\]\s*[.!?]?\s*$", answer_text)
        if not trailing_match and citation_numbers:
            errors.append("expected a trailing source citation")
        invalid_citations = [
            number
            for number in citation_numbers
            if number < 1 or number > source_count
        ]
        valid_citations = [
            number for number in citation_numbers if number in expected_indices
        ]
        required_cited = min(required_source_count, len(expected_indices)) if expected_indices else required_source_count
        if invalid_citations:
            errors.append(
                "invalid source citation(s): "
                + ", ".join(str(number) for number in invalid_citations)
            )
        elif len(set(valid_citations)) < required_cited:
            if required_cited == 1:
                errors.append("expected at least one valid inline source citation")
            else:
                errors.append(
                    f"expected at least {required_cited} cited source(s), "
                    f"found {len(set(valid_citations))}"
                )
    return errors


def is_insufficient_answer(text: str) -> bool:
    lower = text.casefold()
    return any(p in lower for p in INSUFFICIENT_PATTERNS)


def score_answer(
    answer: str,
    expectation: dict[str, Any],
    *,
    case_sensitive: bool = False,
    require_sources: bool = False,
) -> ScoreResult:
    """Score grounding, refusal, source, and safety expectations independently."""
    required = expectation.get("required_facts", [])
    forbidden = expectation.get("forbidden_facts", [])
    found, missing = detect_required(answer, required, case_sensitive=case_sensitive)
    forbidden_found = detect_forbidden(answer, forbidden, case_sensitive=case_sensitive, required_found=found)
    source_errors = []
    if require_sources:
        source_errors = score_sources(answer, expectation.get("expected_sources", []), expectation.get("required_source_count"))
    safety_errors = detect_secret_invention(answer) + detect_redaction_expansion(answer) + detect_overclaim(answer)

    if expectation.get("type") == "unsupported":
        if not (is_insufficient_answer(answer) or any(_contains(answer, f, case_sensitive=case_sensitive) for f in required)):
            missing.append("bounded unsupported-answer refusal")

    total_checks = max(1, len(required) + len(forbidden) + (1 if require_sources else 0) + 3)
    penalties = len(missing) + len(forbidden_found) + len(source_errors) + len(safety_errors)
    score = max(0.0, round(100.0 * (total_checks - penalties) / total_checks, 2))
    passed = not missing and not forbidden_found and not source_errors and not safety_errors
    return ScoreResult(
        score=score,
        passed=passed,
        required_found=found,
        required_missing=missing,
        forbidden_found=forbidden_found,
        source_errors=source_errors,
        safety_errors=safety_errors,
    )


def aggregate_scores(results: Iterable[ScoreResult]) -> dict[str, Any]:
    items = list(results)
    if not items:
        return {"score": 0.0, "passed": False, "count": 0}
    return {
        "score": round(sum(r.score for r in items) / len(items), 2),
        "passed": all(r.passed for r in items),
        "count": len(items),
        "failed": sum(1 for r in items if not r.passed),
    }
