"""Tested Ask/RAG logic used by the internal Synapse service.

The FastAPI Synapse service authenticates webhooks and calls this module.
Retrieval, grounding, prompting, and source validation live here so they can be unit tested as normal Python code.
"""

from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from collections.abc import Callable, Mapping
from typing import Any

from .http_client import post_json
from .metadata import normalize_markdown_note_path

INSUFFICIENT_ANSWER = "I do not have enough indexed note context to answer that reliably."
STOPWORDS = {
    # English
    "what", "which", "when", "where", "why", "how",
    "the", "and", "for", "with", "that", "do", "not", "any", "old",
    "should", "be", "or", "explicitly", "phrases", "written", "recorded",
    "this", "used", "uses", "use", "from", "field", "fields",
    "note", "answer", "return", "quote", "state", "both", "current",
    "does", "did", "is", "are", "was", "were", "in", "on", "of", "to", "a", "an",
    "configure", "set", "run", "find", "get", "make", "show", "tell",
    # German (no overlap with English)
    "ist", "die", "der", "das", "den", "dem", "des", "ein", "eine", "einer",
    "und", "oder", "nicht", "auch", "sich", "auf", "aus", "bei",
    "welche", "welcher", "wann", "warum",
    # French (no overlap with English)
    "les", "une", "du", "et", "pas", "quoi", "comment", "pourquoi",
    # Spanish (no overlap with English)
    "las", "los", "una", "por", "donde",
}

DEFAULT_MAX_QUESTION_LENGTH = 1000

JsonRequester = Callable[[str, str, dict[str, Any], dict[str, str] | None], dict[str, Any]]


def _env_get(env: Mapping[str, str], key: str, default: str = "") -> str:
    value = env.get(key, default)
    return default if value is None else str(value)


def _strip_base_url(value: str, fallback: str) -> str:
    return (value or fallback).rstrip("/")


def normalize_path(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/").lstrip("/")


def normalize_filter(key: str, value: Any) -> str:
    if key == "source_path":
        raw_path = str(value or "").strip()
        return normalize_markdown_note_path(raw_path) if raw_path else ""
    if key == "wiki_path":
        path = normalize_path(value)
        return f"/{path}" if path else ""
    return str(value or "").strip()


def parse_question(body: Mapping[str, Any], env: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = env or {}
    question = str(body.get("question") or body.get("q") or "").strip()
    if len(question) < 3:
        raise ValueError("Send JSON with a question field.")
    max_question_length = _int_env(env, "SYNAPSE_MAX_QUESTION_LENGTH", DEFAULT_MAX_QUESTION_LENGTH)
    if max_question_length > 0 and len(question) > max_question_length:
        raise ValueError(f"question too long: {len(question)} characters exceeds max_question_length={max_question_length}")

    filters = {}
    for key in ("note_id", "source_path", "wiki_path"):
        value = normalize_filter(key, body.get(key))
        if value:
            filters[key] = value

    explicit_run = str(body.get("exact_run_id") or "").strip()
    match = re.search(r"\be2e(?:-[a-z0-9]+)*-[0-9]{8}T[0-9]{6}Z\b", question, flags=re.I)
    exact_run_id = explicit_run or (match.group(0) if match else "")
    return {"question": question, "filters": filters, "exact_run_id": exact_run_id}


def build_qdrant_filter(filters: Mapping[str, str]) -> dict[str, Any]:
    return {"must": [{"key": key, "match": {"value": value}} for key, value in filters.items()]}


def extract_vector(embed_response: Mapping[str, Any]) -> list[float]:
    embeddings = embed_response.get("embeddings")
    vector = embeddings[0] if isinstance(embeddings, list) and embeddings else embed_response.get("embedding")
    if not isinstance(vector, list) or not vector:
        raise ValueError("Embedding response missing vector")
    return vector


_ANGOLO_NORMALIZE_MAP = str.maketrans({"ß": "ss", "æ": "ae", "œ": "oe", "ð": "d", "þ": "th"})


def _normalize(value: Any) -> str:
    text = str(value or "")
    text = text.translate(_ANGOLO_NORMALIZE_MAP)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    lowered = text.lower()
    preserved = re.sub(r"[^a-z0-9._/@#:-]+", " ", lowered)
    stripped = re.sub(r"\s+", " ", preserved).strip()
    tokens = stripped.split()
    cleaned = []
    for token in tokens:
        token = token.rstrip(".,;:!?")
        token = token.lstrip(".,;:!?")
        if token:
            cleaned.append(token)
    return " ".join(cleaned)


def _simple_token_variants(term: str) -> set[str]:
    variants = {term}
    if not term or " " in term:
        return variants
    has_tech_char = any(ch in term for ch in "./@#:")
    if has_tech_char:
        return variants
    if len(term) >= 3:
        variants.update({f"{term}s", f"{term}es", f"{term}ed", f"{term}ing"})
        if term.endswith("s") and len(term) > 3:
            variants.add(term[:-1])
        if term.endswith("es") and len(term) > 4:
            variants.add(term[:-2])
    if "ss" in term:
        variants.add(term.replace("ss", "ß"))
    if "ß" in term:
        variants.add(term.replace("ß", "ss"))
    return variants


def _contains_term(text: str, term: str) -> bool:
    normalized_term = _normalize(term)
    if not normalized_term:
        return False
    normalized_text = _normalize(text)
    if " " in normalized_term:
        return f" {normalized_term} " in f" {normalized_text} "
    text_tokens = set(normalized_text.split())
    if text_tokens.intersection(_simple_token_variants(normalized_term)):
        return True
    has_tech_char = any(ch in normalized_term for ch in "./@#:")
    if has_tech_char:
        return normalized_term in normalized_text
    return False


def _parse_glossary(env: Mapping[str, str]) -> dict[str, Any]:
    try:
        parsed = json.loads(_env_get(env, "RAG_DOMAIN_GLOSSARY_JSON", "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _term_groups(question: str, env: Mapping[str, str]) -> list[dict[str, Any]]:
    question_normalized = _normalize(question)
    question_lower = question.lower()
    question_tokens = re.findall(r"[a-z0-9._/@#:-]{2,}", question_normalized)
    covered_indexes: set[int] = set()
    groups: list[dict[str, Any]] = []

    def add_term_group(label: str, variants: list[str]) -> None:
        clean_label = _normalize(label)
        base_variants = list(dict.fromkeys(v for v in [clean_label, *(_normalize(v) for v in variants)] if v))
        cross_variants = []
        for v in base_variants:
            if "ss" in v:
                cross_variants.append(v.replace("ss", "ß"))
        extra = list(dict.fromkeys(cv for cv in cross_variants if cv and cv not in base_variants))
        clean_variants = base_variants + extra
        if not clean_label or any(group["label"] == clean_label for group in groups):
            return
        groups.append({"label": clean_label, "variants": clean_variants})

    for canonical, aliases in _parse_glossary(env).items():
        alias_values = aliases if isinstance(aliases, list) else [aliases]
        variants = [_normalize(v) for v in [canonical, *alias_values] if _normalize(v)]
        matched_alias = next((variant for variant in variants if _contains_term(question_lower, variant)), "")
        if not matched_alias:
            continue
        add_term_group(matched_alias, variants)
        alias_tokens = set(matched_alias.split())
        for index, token in enumerate(question_tokens):
            if _normalize(token) in alias_tokens:
                covered_indexes.add(index)

    for index, term in enumerate(question_tokens):
        normalized = _normalize(term)
        if not normalized or normalized in STOPWORDS or index in covered_indexes:
            continue
        add_term_group(normalized, [normalized])
    return groups


def _point_payload(point: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = point.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _metadata_haystack(point: Mapping[str, Any]) -> str:
    payload = _point_payload(point)
    return " ".join(str(payload.get(key) or "") for key in ("source_path", "wiki_path", "title", "text")).lower()


def _content_haystack(point: Mapping[str, Any]) -> str:
    payload = _point_payload(point)
    return f"{payload.get('title') or ''} {payload.get('text') or ''}".lower()


def _exact_query_markers(question: str) -> list[str]:
    """Return exact incident/run-style markers that should scope retrieval.

    Vector search can rank stale near-duplicate notes above the current companion
    source. Exact markers from the user's question keep multi-source grounding tied
    to the same fresh proof run instead of mixing unrelated old evidence.
    """
    markers = []
    for match in re.finditer(r"\b[A-Za-z]{2,}-[A-Za-z0-9]*[0-9][A-Za-z0-9]*-[0-9]+\b", question):
        normalized = match.group(0).casefold()
        if normalized not in markers:
            markers.append(normalized)
    return markers


def _point_matches_marker_scope(point: Mapping[str, Any], markers: list[str]) -> bool:
    if not markers:
        return True
    haystack = _metadata_haystack(point).casefold()
    return all(marker in haystack for marker in markers)


def _quoted_support(text: Any, question: str, env: Mapping[str, str]) -> str:
    raw_text = str(text or "")
    if re.search(r"\b(command|replay|exact)\b", question, flags=re.I):
        for line in raw_text.splitlines():
            cleaned_line = re.sub(r"\s+", " ", line).strip()
            if "`" in cleaned_line and re.search(r"`[^`]+`", cleaned_line):
                return cleaned_line[:357].rstrip() + "..." if len(cleaned_line) > 360 else cleaned_line
    source_text = re.sub(r"\s+", " ", raw_text).strip()
    if not source_text:
        return ""
    sentences = [match.group(0).strip() for match in re.finditer(r"[^.!?]+[.!?]?", source_text) if match.group(0).strip()]
    if not sentences:
        return source_text[:360]
    groups = _term_groups(question, env)
    anchor_labels = {group["label"] for group in groups if re.match(r"^[a-z0-9._/@#:-]{2,}$", group["label"]) and group["label"] not in STOPWORDS}

    def score(sentence: str) -> tuple[int, int, int]:
        matched_groups = [group for group in groups if any(_contains_term(sentence, variant) for variant in group["variants"])]
        anchor_matches = sum(1 for group in matched_groups if group["label"] in anchor_labels)
        return (len(matched_groups), anchor_matches, len(sentence))

    best = max(sentences, key=score)
    if len(best) > 360:
        return best[:357].rstrip() + "..."
    return best


def _float_env(env: Mapping[str, str], key: str, default: float) -> float:
    try:
        return float(_env_get(env, key, str(default)))
    except ValueError:
        return default


def _int_env(env: Mapping[str, str], key: str, default: int) -> int:
    try:
        return int(float(_env_get(env, key, str(default))))
    except ValueError:
        return default


def build_context(parsed: Mapping[str, Any], points: list[dict[str, Any]], env: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = env or {}
    threshold = _float_env(env, "RAG_SCORE_THRESHOLD", 0.35)
    accepted = [point for point in points if float(point.get("score") or 0) >= threshold]
    filters = parsed.get("filters") if isinstance(parsed.get("filters"), Mapping) else {}

    for key, value in filters.items():
        accepted = [point for point in accepted if str(_point_payload(point).get(key) or "") == str(value)]

    grounding_stats: dict[str, Any] = {"query_terms": [], "anchor_terms": [], "matched_terms": [], "term_coverage": 1}

    def insufficient(reason: str, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return {
            "question": parsed.get("question"),
            "filters": dict(filters),
            "exact_run_id": parsed.get("exact_run_id") or "",
            "insufficient_context": True,
            "context": "",
            "sources": [],
            "retrieval": {
                "accepted": len(accepted),
                "threshold": threshold,
                "filtered_for_grounding": True,
                "reason": reason,
                **grounding_stats,
                **dict(extra or {}),
            },
        }

    exact_run_id = str(parsed.get("exact_run_id") or "").lower()
    if exact_run_id:
        accepted = [point for point in accepted if exact_run_id in _metadata_haystack(point)]

    exact_markers = _exact_query_markers(str(parsed.get("question") or ""))
    if exact_markers:
        marker_scoped = [point for point in accepted if _point_matches_marker_scope(point, exact_markers)]
        if marker_scoped:
            accepted = marker_scoped

    groups = _term_groups(str(parsed.get("question") or ""), env)
    anchor_terms = [group["label"] for group in groups if re.match(r"^[a-z0-9._/@#:-]{2,}$", group["label"]) and group["label"] not in STOPWORDS]
    grounding_stats = {**grounding_stats, "query_terms": [group["label"] for group in groups], "anchor_terms": anchor_terms}
    min_coverage = _float_env(env, "RAG_QUERY_TERM_MIN_COVERAGE", 0.6)
    min_matches = _int_env(env, "RAG_QUERY_TERM_MIN_MATCHES", 2)

    def grounding_for_point(point: Mapping[str, Any]) -> dict[str, Any]:
        text = _content_haystack(point)
        matched_terms = [group["label"] for group in groups if any(_contains_term(text, variant) for variant in group["variants"])]
        coverage = len(matched_terms) / len(groups) if groups else 1
        required = min(len(groups), max(1, min_matches, math.ceil(len(groups) * min_coverage))) if groups else 0
        return {
            "matched_terms": matched_terms,
            "term_coverage": coverage,
            "required_matches": required,
            "anchors_satisfied": all(term in matched_terms for term in anchor_terms),
        }

    if groups:
        grounded = [
            {"point": point, "grounding": grounding_for_point(point)}
            for point in accepted
        ]
        grounded = [item for item in grounded if item["grounding"]["anchors_satisfied"] and len(item["grounding"]["matched_terms"]) >= item["grounding"]["required_matches"]]
        if not grounded:
            combined = []
            combined_terms: set[str] = set()
            candidate_items = [item for item in [
                {"point": point, "grounding": grounding_for_point(point)}
                for point in accepted
            ] if item["grounding"]["matched_terms"]]
            for item in candidate_items:
                combined.append(item)
                combined_terms.update(str(term) for term in item["grounding"]["matched_terms"])
            combined_required = min(len(groups), max(1, min_matches, math.ceil(len(groups) * min_coverage))) if groups else 0
            if combined and all(term in combined_terms for term in anchor_terms) and len(combined_terms) >= combined_required:
                grounding_stats = {
                    **grounding_stats,
                    "matched_terms": sorted(combined_terms),
                    "term_coverage": len(combined_terms) / len(groups) if groups else 1,
                    "required_matches": combined_required,
                    "anchors_satisfied": True,
                    "combined_source_grounding": True,
                }
                accepted = [item["point"] for item in combined]
            else:
                best = sorted(
                    (grounding_for_point(point) for point in accepted),
                    key=lambda item: (len(item["matched_terms"]), item["term_coverage"]),
                    reverse=True,
                )
                return insufficient("no_query_term_coverage", best[0] if best else {})
        else:
            grounding_stats = {**grounding_stats, **grounded[0]["grounding"]}
            accepted = [item["point"] for item in grounded]

    if not accepted:
        return insufficient("no_grounded_note_context")

    accepted = sorted(accepted, key=lambda point: float(point.get("score") or 0), reverse=True)
    seen: set[str] = set()
    unique = []
    for point in accepted:
        payload = _point_payload(point)
        key = f"{payload.get('note_id') or payload.get('source_path') or payload.get('wiki_path') or ''}:{payload.get('chunk_index', '')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(point)
    accepted = unique

    if not accepted:
        return insufficient("no_unique_note_context")

    sources = []
    for point in accepted:
        payload = _point_payload(point)
        sources.append(
            {
                "title": payload.get("title") or "Untitled",
                "note_id": payload.get("note_id"),
                "source_path": payload.get("source_path"),
                "wiki_path": payload.get("wiki_path"),
                "source_url": payload.get("source_url"),
                "score": point.get("score"),
                "chunk_index": payload.get("chunk_index"),
                "quoted_support": _quoted_support(payload.get("text"), str(parsed.get("question") or ""), env),
            }
        )
    context = "\n\n".join(
        f"[{index + 1}] {sources[index]['title']} score={float(point.get('score') or 0):.3f} source_path={sources[index].get('source_path') or ''}\n{_point_payload(point).get('text') or ''}"
        for index, point in enumerate(accepted)
    )
    return {
        "question": parsed.get("question"),
        "filters": dict(filters),
        "exact_run_id": parsed.get("exact_run_id") or "",
        "insufficient_context": False,
        "context": context,
        "sources": sources,
        "retrieval": {"accepted": len(accepted), "threshold": threshold, "filtered_for_grounding": True, **grounding_stats},
    }


def build_answer_payload(question: str, context: str, env: Mapping[str, str]) -> dict[str, Any]:
    model = _env_get(env, "OLLAMA_ANSWER_MODEL", "tinyllama:latest")
    num_predict = _int_env(env, "OLLAMA_ANSWER_NUM_PREDICT", 256)
    system = " ".join(
        [
            "Answer only from the provided note context.",
            "Do not use outside knowledge or invent details.",
            f"If the context does not contain the answer, say exactly: {INSUFFICIENT_ANSWER}",
            "If the context explicitly says a value is unavailable, redacted, or not provided, state that boundary exactly and cite the supporting source instead of inventing a value.",
            "Quote identifiers, codenames, commands, paths, and source labels exactly as written.",
            "Cite supporting source numbers like [1].",
            "End the answer with the supporting source number, for example [1].",
            "Answer in one concise sentence.",
            "Do not use Markdown formatting, bold, italics, headings, or code fences in the answer.",
            "Return only the plain-text answer.",
        ]
    )
    user = f"Question:\n{question}\n\nNote context:\n{context}\n\nAnswer from the note context only."
    return {
        "model": model,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": num_predict},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }


def _normalize_refusal(text: str) -> str:
    without_citation = re.sub(r"\s*\[[0-9,\s]+\]\s*[.!?]?\s*$", "", text)
    without_period = re.sub(r"[.\s]+$", "", without_citation)
    return re.sub(r"\s+", " ", without_period).strip().lower()


def _source_has_locator(source: Mapping[str, Any]) -> bool:
    return any(str(source.get(key) or "").strip() for key in ("source_path", "wiki_path", "source_url", "note_id"))


def extractive_answer(ctx: Mapping[str, Any]) -> str:
    """Build a cited answer directly from retrieved source snippets.

    This mode is useful for local CPU-only labs where larger recommended models are
    too slow for every Ask request, and it keeps answers auditable because every
    sentence is copied from `quoted_support` rather than generated from model memory.
    """
    raw_sources = ctx.get("sources")
    sources = raw_sources if isinstance(raw_sources, list) else []
    parts = []
    for index, source in enumerate(sources, start=1):
        if not isinstance(source, Mapping):
            continue
        quote = re.sub(r"\s+", " ", str(source.get("quoted_support") or "")).strip()
        if not quote:
            continue
        quote = quote.rstrip()
        citation = f"[{index}]"
        if quote.endswith(citation):
            parts.append(quote if quote.endswith(f"{citation}.") else f"{quote}.")
        else:
            parts.append(f"{quote} {citation}.")
    return " ".join(parts).strip()


def _ngrams(text: str, n: int = 3) -> set[str]:
    tokens = _normalize(text).split()
    if len(tokens) < n:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _quote_overlap(answer: str, sources: list[Mapping[str, Any]]) -> float:
    quoted_union = " ".join(
        str(source.get("quoted_support") or "").strip() for source in sources if isinstance(source, Mapping)
    )
    if not quoted_union.strip():
        return 0.0
    answer_ngrams = _ngrams(answer)
    quote_ngrams = _ngrams(quoted_union)
    if not answer_ngrams:
        return 0.0
    overlap = answer_ngrams & quote_ngrams
    return len(overlap) / len(answer_ngrams)


def _extractive_answer_valid(answer: str, sources: list[Mapping[str, Any]]) -> bool:
    answer_clean = re.sub(r"\s*\[[0-9,\s]+\]\s*[.!?]?\s*$", "", answer).strip()
    answer_clean = re.sub(r"\s*\[[0-9,\s]+\]", "", answer_clean).strip()
    if not answer_clean:
        return False
    quoted_texts = [
        re.sub(r"\s+", " ", str(source.get("quoted_support") or "")).strip()
        for source in sources
        if isinstance(source, Mapping)
    ]
    union_normalized = _normalize(" ".join(quoted_texts))
    answer_normalized = _normalize(answer_clean)
    return answer_normalized in union_normalized or any(
        answer_normalized in _normalize(qt) for qt in quoted_texts if qt
    )


def answer_or_refuse(
    ctx: Mapping[str, Any],
    llm_response: Mapping[str, Any],
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = env or {}
    sources = ctx.get("sources") if isinstance(ctx.get("sources"), list) else []
    validation_mode = _env_get(env, "SYNAPSE_ANSWER_VALIDATION", "structural").strip().lower()

    def refuse(reason: str, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        retrieval = ctx.get("retrieval") if isinstance(ctx.get("retrieval"), Mapping) else {}
        return {
            "question": ctx.get("question"),
            "answer": INSUFFICIENT_ANSWER,
            "insufficient_context": True,
            "sources": [],
            "retrieval": {**dict(retrieval), "refusal_reason": reason, **dict(extra or {})},
        }

    if ctx.get("insufficient_context"):
        retrieval = ctx.get("retrieval") if isinstance(ctx.get("retrieval"), Mapping) else {}
        return refuse(str(retrieval.get("reason") or "insufficient_context"))
    if not sources:
        return refuse("missing_sources")

    message = llm_response.get("message") if isinstance(llm_response.get("message"), Mapping) else {}
    answer = str(message.get("content") or llm_response.get("response") or "").strip()
    if not answer or _normalize_refusal(answer) == _normalize_refusal(INSUFFICIENT_ANSWER):
        return refuse("empty_or_refused_answer")

    citation_numbers: list[int | float] = []
    for match in re.finditer(r"(?:^|\s)\[([0-9,\s]+)\](?=\s*[.!?,]?(?:\s|$))", answer):
        before = answer[: match.start()].rstrip()
        previous = re.search(r"([A-Za-z][A-Za-z0-9_-]*)$", before)
        if previous and previous.group(1).lower() == "rfc":
            continue
        for part in match.group(1).split(","):
            try:
                citation_numbers.append(int(part.strip()))
            except ValueError:
                citation_numbers.append(float("nan"))

    invalid = [number for number in citation_numbers if not isinstance(number, int) or number < 1 or number > len(sources)]
    if invalid:
        return refuse("invalid_citation")
    valid = [number for number in citation_numbers if isinstance(number, int) and 1 <= number <= len(sources)]
    if not valid:
        return refuse("missing_valid_citation")
    if any(not _source_has_locator(sources[number - 1]) for number in sorted(set(valid))):
        return refuse("invalid_source_locator")

    cited_sources = [sources[number - 1] for number in sorted(set(valid))]

    validation_label = "structural_citations_only"

    if validation_mode == "quote_overlap":
        threshold = _float_env(env, "RAG_QUOTE_OVERLAP_THRESHOLD", 0.3)
        overlap = _quote_overlap(answer, cited_sources)
        if overlap < threshold:
            return refuse(
                "answer_grounding_failed",
                {"quote_overlap": round(overlap, 3), "quote_overlap_threshold": threshold},
            )
        validation_label = "quote_overlap"

    elif validation_mode == "extractive":
        if not _extractive_answer_valid(answer, cited_sources):
            return refuse("answer_grounding_failed", {"validation": "extractive_content_mismatch"})
        validation_label = "extractive_content"

    raw_retrieval = ctx.get("retrieval")
    retrieval = raw_retrieval if isinstance(raw_retrieval, Mapping) else {}
    retrieval_payload = {key: value for key, value in retrieval.items()}
    return {
        "question": ctx.get("question"),
        "answer": answer,
        "insufficient_context": False,
        "sources": sources,
        "retrieval": {**retrieval_payload, "answer_validation": validation_label},
    }


def _extract_points(qdrant_response: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = qdrant_response.get("result")
    if isinstance(result, Mapping):
        points = result.get("points") or result.get("result") or []
    else:
        points = result or qdrant_response.get("points") or []
    return points if isinstance(points, list) else []


def _extract_scroll_page(qdrant_response: Mapping[str, Any]) -> tuple[list[dict[str, Any]], Any]:
    result = qdrant_response.get("result")
    if not isinstance(result, Mapping):
        return [], None
    points = result.get("points") or []
    return (points if isinstance(points, list) else []), result.get("next_page_offset")


def _indexed_note_from_payload(payload: Mapping[str, Any]) -> dict[str, str] | None:
    source_path = str(payload.get("source_path") or "").strip().replace("\\", "/")
    if not source_path or not source_path.lower().endswith(".md"):
        return None
    note: dict[str, str] = {"source_path": source_path}
    for key in ("title", "note_id", "wiki_path"):
        value = str(payload.get(key) or "").strip()
        if value:
            note[key] = value
    return note


def list_indexed_notes(
    payload: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    request_json: JsonRequester | None = None,
) -> dict[str, Any]:
    """List distinct Markdown note sources present in the live Qdrant index."""
    env = env or os.environ
    requester = request_json or (lambda method, url, body, headers=None: post_json(url, body, headers=headers))
    qdrant = _strip_base_url(_env_get(env, "QDRANT_BASE_URL"), "http://qdrant:6333")
    collection = _env_get(env, "QDRANT_COLLECTION", "synapse_notes")
    query = _normalize(str(payload.get("query") or ""))
    try:
        limit = max(1, min(50, int(float(str(payload.get("limit") or env.get("SYNAPSE_INDEXED_NOTES_LIMIT") or 12)))))
    except ValueError:
        limit = 12

    notes_by_path: dict[str, dict[str, str]] = {}
    offset = None
    pages = 0
    while pages < 20 and len(notes_by_path) < limit:
        body: dict[str, Any] = {"limit": 128, "with_payload": True}
        if offset is not None:
            body["offset"] = offset
        response = requester("POST", f"{qdrant}/collections/{collection}/points/scroll", body, {"Content-Type": "application/json"})
        points, offset = _extract_scroll_page(response)
        pages += 1
        for point in points:
            note = _indexed_note_from_payload(_point_payload(point))
            if note is None:
                continue
            haystack = _normalize(" ".join(str(note.get(key, "")) for key in ("source_path", "title", "note_id", "wiki_path")))
            if query and query not in haystack:
                continue
            notes_by_path.setdefault(note["source_path"], note)
            if len(notes_by_path) >= limit:
                break
        if not offset:
            break

    notes = sorted(notes_by_path.values(), key=lambda note: note["source_path"].lower())[:limit]
    return {"notes": notes, "count": len(notes)}


def ask(
    payload: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    request_json: JsonRequester | None = None,
) -> dict[str, Any]:
    env = env or os.environ
    requester = request_json or (lambda method, url, body, headers=None: post_json(url, body, headers=headers))
    parsed = parse_question(payload, env=env)

    ollama_embed = _strip_base_url(_env_get(env, "OLLAMA_INTERNAL_BASE_URL"), "http://ollama:11434")
    embed_model = _env_get(env, "OLLAMA_EMBED_MODEL", "nomic-embed-text")
    embed = requester("POST", f"{ollama_embed}/api/embed", {"model": embed_model, "input": parsed["question"]}, {"Content-Type": "application/json"})
    vector = extract_vector(embed)

    qdrant = _strip_base_url(_env_get(env, "QDRANT_BASE_URL"), "http://qdrant:6333")
    collection = _env_get(env, "QDRANT_COLLECTION", "synapse_notes")
    top_k = _int_env(env, "RAG_TOP_K", 5)
    candidate_k = max(top_k, _int_env(env, "RAG_CANDIDATE_K", max(top_k, 25)))
    qdrant_body = {
        "query": vector,
        "limit": candidate_k,
        "with_payload": True,
        "filter": build_qdrant_filter(parsed["filters"]),
    }
    qdrant_response = requester("POST", f"{qdrant}/collections/{collection}/points/query", qdrant_body, {"Content-Type": "application/json"})
    ctx = build_context(parsed, _extract_points(qdrant_response), env)

    if ctx.get("insufficient_context"):
        return answer_or_refuse(ctx, {"response": INSUFFICIENT_ANSWER}, env=env)

    chat_base = _strip_base_url(_env_get(env, "OLLAMA_CHAT_BASE_URL") or _env_get(env, "OLLAMA_INTERNAL_BASE_URL"), "http://ollama:11434")
    answer_mode = _env_get(env, "SYNAPSE_ANSWER_MODE", "llm").strip().lower()
    if answer_mode == "extractive":
        return answer_or_refuse(ctx, {"response": extractive_answer(ctx)}, env=env)
    llm_response = requester("POST", f"{chat_base}/api/chat", build_answer_payload(str(ctx["question"]), str(ctx["context"]), env), {"Content-Type": "application/json"})
    if isinstance(llm_response.get("message"), Mapping):
        normalized_llm = llm_response
    else:
        normalized_llm = {"response": str(llm_response.get("response") or "").strip() or INSUFFICIENT_ANSWER}
    return answer_or_refuse(ctx, normalized_llm, env=env)
