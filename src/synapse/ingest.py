"""Tested ingest/index/publish logic used by the internal Synapse service."""

from __future__ import annotations

import datetime as dt
import os
import threading
from contextlib import contextmanager
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from .http_client import request_json as default_request_json
from .metadata import build_metadata, chunk_text, normalize_text, slugify, source_url
from .upstream import UpstreamError

JsonRequester = Callable[[str, str, dict[str, Any], dict[str, str] | None], dict[str, Any]]
DEFAULT_MAX_CONTENT_BYTES = 262_144
DEFAULT_MAX_CHUNKS_PER_NOTE = 32
DEFAULT_EMBED_BATCH_SIZE = 16
_NOTE_LOCKS_GUARD = threading.Lock()
_NOTE_LOCKS: dict[str, threading.Lock] = {}


def _int_env(env: Mapping[str, str], key: str, default: int) -> int:
    try:
        return int(float(_env_get(env, key, str(default))))
    except ValueError:
        return default


def _utf8_len(value: str) -> int:
    return len(value.encode("utf-8"))


def _env_get(env: Mapping[str, str], key: str, default: str = "") -> str:
    value = env.get(key, default)
    return default if value is None else str(value)


def _base_url(env: Mapping[str, str], key: str, fallback: str) -> str:
    return (_env_get(env, key) or fallback).rstrip("/")


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _revision_fields(item: Mapping[str, Any]) -> dict[str, Any]:
    content_hash = str(item["content_hash"])
    note_id = str(item["note_id"])
    updated_at = str(item.get("updated_at") or _utc_now())
    compact_time = updated_at.replace("-", "").replace(":", "").replace(".", "").replace("Z", "Z")
    return {
        "revision": str(item.get("revision") or content_hash),
        "current_content_hash": str(item.get("current_content_hash") or content_hash),
        "updated_at": updated_at,
        "ingest_job_id": str(item.get("ingest_job_id") or f"ingest-{note_id}-{compact_time}"),
    }


def with_revision(item: Mapping[str, Any]) -> dict[str, Any]:
    return {**dict(item), **_revision_fields(item)}


@contextmanager
def note_update_lock(note_id: str) -> Iterator[None]:
    with _NOTE_LOCKS_GUARD:
        lock = _NOTE_LOCKS.setdefault(note_id, threading.Lock())
    if not lock.acquire(blocking=False):
        raise ValueError(f"concurrent update refused for note_id={note_id}")
    try:
        yield
    finally:
        lock.release()
        with _NOTE_LOCKS_GUARD:
            # Only remove if no other thread grabbed it while we released.
            # .locked() is True if another thread called acquire() between
            # our release() and this guard acquisition — in that case the key
            # must remain so the other thread can finish.
            if not lock.locked():
                _NOTE_LOCKS.pop(note_id, None)


def enforce_content_limit(payload: Mapping[str, Any], env: Mapping[str, str]) -> None:
    max_bytes = _int_env(env, "SYNAPSE_MAX_CONTENT_BYTES", DEFAULT_MAX_CONTENT_BYTES)
    if max_bytes <= 0:
        return
    candidates = {
        "content": payload.get("content"),
        "markdown": payload.get("markdown"),
        "formatted_markdown": payload.get("formatted_markdown"),
    }
    for field, value in candidates.items():
        if value is None:
            continue
        size = _utf8_len(str(value))
        if size > max_bytes:
            raise ValueError(f"content too large: {field} is {size} bytes, exceeds max_content_bytes={max_bytes}")


def note_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    path = str(payload.get("path") or payload.get("vault_relative_path") or "").strip()
    if not path:
        raise ValueError("Missing required field: path or vault_relative_path")
    raw = str(payload.get("content") or payload.get("markdown") or "")
    content = normalize_text(raw)
    metadata = build_metadata(path, content).to_dict()
    if payload.get("title"):
        title = str(payload["title"]).strip()
        if title:
            # A title override changes display metadata only. Do not derive a
            # second Wiki.js path from it; the normalized vault path is stable.
            metadata["title"] = title
            metadata["slug"] = slugify(title)
    metadata["path_parts"] = [part for part in metadata["vault_relative_path"].split("/") if part]
    metadata["content"] = content
    return metadata


def format_markdown(note: Mapping[str, Any], env: Mapping[str, str], request_json: JsonRequester) -> str:
    ollama = _base_url(env, "OLLAMA_CHAT_BASE_URL", "") or _base_url(env, "OLLAMA_INTERNAL_BASE_URL", "http://ollama:11434")
    model = _env_get(env, "OLLAMA_FORMAT_MODEL", "tinyllama:latest")
    try:
        num_predict = int(float(_env_get(env, "OLLAMA_FORMAT_NUM_PREDICT", "768")))
    except ValueError:
        num_predict = 768
    response = request_json(
        "POST",
        f"{ollama}/api/chat",
        {
            "model": model,
            "stream": False,
            "think": False,
            "options": {"num_predict": num_predict, "temperature": 0},
            "messages": [
                {
                    "role": "system",
                    "content": "Format the source note as compact clean Markdown. Preserve every fact exactly. Do not invent details. Do not add system names, products, services, publishers, dates, or verification claims that are not present in the source note. Preserve spelling, case, negative statements, identifiers, codenames, and source paths exactly. If the note is already Markdown, keep it concise and do not expand it. Return only Markdown.",
                },
                {"role": "user", "content": str(note.get("content") or "")},
            ],
        },
        {"Content-Type": "application/json"},
    )
    message = response.get("message") if isinstance(response.get("message"), Mapping) else {}
    return str(message.get("content") or response.get("response") or note.get("content") or "")


def prepare_publish_payload(note: Mapping[str, Any], formatted: str) -> dict[str, Any]:
    note = with_revision(note)
    # Wiki.js gets a readable formatted copy, but the original source is kept
    # in the same page so reviewers can compare presentation with truth.
    source_block = "\n\n## Original Source Note\n\n" + str(note.get("content") or "").strip() + "\n"
    frontmatter = "\n".join(
        [
            "---",
            f"synapse_note_id: {note['note_id']}",
            f"synapse_content_hash: {note['content_hash']}",
            f"synapse_revision: {note['revision']}",
            f"synapse_updated_at: {note['updated_at']}",
            f"synapse_ingest_job_id: {note['ingest_job_id']}",
            f"synapse_source_path: {note['vault_relative_path']}",
            f"synapse_schema_version: {note['schema_version']}",
            "---",
            "",
        ]
    )
    return {**dict(note), "formatted_markdown": frontmatter + (formatted.strip() + source_block).strip() + "\n"}


def publish_wikijs(item: Mapping[str, Any], env: Mapping[str, str], request_json: JsonRequester) -> dict[str, Any]:
    base = _base_url(env, "WIKIJS_BASE_URL", "http://wikijs:3000")
    token = _env_get(env, "WIKIJS_API_TOKEN")
    locale = _env_get(env, "WIKIJS_LOCALE", "en")
    if not token:
        raise ValueError("Missing WIKIJS_API_TOKEN")

    def gql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        response = request_json(
            "POST",
            f"{base}/graphql",
            {"query": query, "variables": variables},
            {"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        errors = response.get("errors")
        not_found_lookup = (
            "singleByPath" in query
            and isinstance(errors, list)
            and errors
            and all(
                isinstance(error, Mapping)
                and str(error.get("message") or "").casefold() == "this page does not exist."
                for error in errors
            )
        )
        if isinstance(errors, list) and errors and not not_found_lookup:
            messages = "; ".join(str(error.get("message") if isinstance(error, Mapping) else error) for error in errors)
            raise UpstreamError("upstream_wikijs_error", f"Wiki.js GraphQL error: {messages}")
        data = response.get("data")
        return data if isinstance(data, dict) else {}

    path = str(item["wiki_path"]).lstrip("/")
    lookup_query = "query ($path: String!, $locale: String!) { pages { singleByPath(path: $path, locale: $locale) { id path title } } }"
    # Wiki.js deployments differ on whether lookup accepts a leading slash.
    # Probe both forms before deciding that a stable page needs creation.
    list_data = gql(lookup_query, {"path": "/" + path, "locale": locale})
    page_data = list_data.get("pages", {}).get("singleByPath") if isinstance(list_data.get("pages"), Mapping) else None
    if not page_data:
        # Wiki.js 2.5 accepts the slash-prefixed form in some deployments but
        # resolves existing pages only when the path has no leading slash in
        # others. Retry the lookup in the canonical stored form before trying
        # to create a page, otherwise an update is misclassified as a duplicate.
        list_data = gql(lookup_query, {"path": path, "locale": locale})
        page_data = list_data.get("pages", {}).get("singleByPath") if isinstance(list_data.get("pages"), Mapping) else None
    existing = page_data if isinstance(page_data, Mapping) and page_data.get("id") else None
    variables = {"path": path, "title": item["title"], "content": item["formatted_markdown"], "locale": locale}
    if existing:
        result = gql(
            'mutation Update($id:Int!,$path:String!,$title:String!,$content:String!,$locale:String!){ pages { update(id:$id,path:$path,title:$title,content:$content,description:"Synapse note",locale:$locale,isPublished:true,isPrivate:false,editor:"markdown",tags:[]){ responseResult { succeeded errorCode message } page { id path title } } } }',
            {**variables, "id": int(existing["id"])},
        )
        response_result = result.get("pages", {}).get("update", {}).get("responseResult", {})
        if not response_result.get("succeeded"):
            raise UpstreamError("upstream_wikijs_error", f"Wiki.js update failed: {response_result.get('message') or 'unknown error'}")
    else:
        result = gql(
            'mutation Create($path:String!,$title:String!,$content:String!,$locale:String!){ pages { create(path:$path,title:$title,content:$content,description:"Synapse note",locale:$locale,isPublished:true,isPrivate:false,editor:"markdown",tags:[]){ responseResult { succeeded errorCode message } page { id path title } } } }',
            variables,
        )
        response_result = result.get("pages", {}).get("create", {}).get("responseResult", {})
        if not response_result.get("succeeded"):
            raise UpstreamError("upstream_wikijs_error", f"Wiki.js create failed: {response_result.get('message') or 'unknown error'}")
    return result


def delete_qdrant_chunks(item: Mapping[str, Any], env: Mapping[str, str], request_json: JsonRequester) -> None:
    """Remove every indexed chunk for a stable note identity."""
    qdrant = _base_url(env, "QDRANT_BASE_URL", "http://qdrant:6333")
    collection = _env_get(env, "QDRANT_COLLECTION", "synapse_notes")
    request_json(
        "POST",
        f"{qdrant}/collections/{collection}/points/delete?wait=true",
        {"filter": {"must": [{"key": "note_id", "match": {"value": item["note_id"]}}]}},
        {"Content-Type": "application/json"},
    )


def delete_wikijs(item: Mapping[str, Any], env: Mapping[str, str], request_json: JsonRequester) -> dict[str, Any]:
    """Delete the page at the note's stable publication path, if present."""
    base = _base_url(env, "WIKIJS_BASE_URL", "http://wikijs:3000")
    token = _env_get(env, "WIKIJS_API_TOKEN")
    locale = _env_get(env, "WIKIJS_LOCALE", "en")
    if not token:
        raise ValueError("Missing WIKIJS_API_TOKEN")

    def gql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        response = request_json(
            "POST",
            f"{base}/graphql",
            {"query": query, "variables": variables},
            {"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        errors = response.get("errors")
        not_found_lookup = (
            "singleByPath" in query
            and isinstance(errors, list)
            and errors
            and all(
                isinstance(error, Mapping)
                and str(error.get("message") or "").casefold() == "this page does not exist."
                for error in errors
            )
        )
        if isinstance(errors, list) and errors and not not_found_lookup:
            messages = "; ".join(str(error.get("message") if isinstance(error, Mapping) else error) for error in errors)
            raise UpstreamError("upstream_wikijs_error", f"Wiki.js GraphQL error: {messages}")
        data = response.get("data")
        return data if isinstance(data, dict) else {}

    path = str(item["wiki_path"]).lstrip("/")
    lookup_query = "query ($path: String!, $locale: String!) { pages { singleByPath(path: $path, locale: $locale) { id path title } } }"
    # Deletion uses the same path lookup rules as publishing so a title change
    # cannot strand the page under a different display slug.
    list_data = gql(lookup_query, {"path": "/" + path, "locale": locale})
    page_data = list_data.get("pages", {}).get("singleByPath") if isinstance(list_data.get("pages"), Mapping) else None
    if not page_data:
        list_data = gql(lookup_query, {"path": path, "locale": locale})
        page_data = list_data.get("pages", {}).get("singleByPath") if isinstance(list_data.get("pages"), Mapping) else None
    if not isinstance(page_data, Mapping) or not page_data.get("id"):
        return {"status": "not_found"}

    result = gql(
        "mutation Delete($id:Int!){ pages { remove(id:$id){ responseResult { succeeded errorCode message } } } }",
        {"id": int(page_data["id"])},
    )
    response_result = result.get("pages", {}).get("remove", {}).get("responseResult", {})
    if not response_result.get("succeeded"):
        raise UpstreamError("upstream_wikijs_error", f"Wiki.js delete failed: {response_result.get('message') or 'unknown error'}")
    return {"status": "deleted", "page_id": int(page_data["id"]), "wiki_path": str(item["wiki_path"])}


def _batched(values: list[Any], size: int) -> list[list[Any]]:
    safe_size = max(1, size)
    return [values[index : index + safe_size] for index in range(0, len(values), safe_size)]


def _vectors_from_embed_response(response: Mapping[str, Any], expected: int) -> list[list[Any]]:
    embeddings = response.get("embeddings")
    if isinstance(embeddings, list) and len(embeddings) == expected and all(isinstance(vector, list) and vector for vector in embeddings):
        return embeddings
    if expected == 1:
        vector = response.get("embedding")
        if isinstance(vector, list) and vector:
            return [vector]
    raise ValueError(f"Embedding response missing {expected} vectors")


def delete_stale_qdrant_chunks(item: Mapping[str, Any], env: Mapping[str, str], request_json: JsonRequester) -> None:
    item = with_revision(item)
    qdrant = _base_url(env, "QDRANT_BASE_URL", "http://qdrant:6333")
    collection = _env_get(env, "QDRANT_COLLECTION", "synapse_notes")
    request_json(
        "POST",
        f"{qdrant}/collections/{collection}/points/delete?wait=true",
        {
            "filter": {
                "must": [{"key": "note_id", "match": {"value": item["note_id"]}}],
                "must_not": [{"key": "content_hash", "match": {"value": item["content_hash"]}}],
            }
        },
        {"Content-Type": "application/json"},
    )


def rollback_new_qdrant_chunks(item: Mapping[str, Any], env: Mapping[str, str], request_json: JsonRequester) -> None:
    """Delete newly inserted Qdrant chunks when Wiki.js publishing fails.

    Removes all points matching both the note_id and the new content_hash,
    undoing the upsert that happened before the publish attempt.
    """
    item = with_revision(item)
    qdrant = _base_url(env, "QDRANT_BASE_URL", "http://qdrant:6333")
    collection = _env_get(env, "QDRANT_COLLECTION", "synapse_notes")
    request_json(
        "POST",
        f"{qdrant}/collections/{collection}/points/delete?wait=true",
        {
            "filter": {
                "must": [
                    {"key": "note_id", "match": {"value": item["note_id"]}},
                    {"key": "content_hash", "match": {"value": item["content_hash"]}},
                ],
            }
        },
        {"Content-Type": "application/json"},
    )


def index_qdrant(item: Mapping[str, Any], env: Mapping[str, str], request_json: JsonRequester, *, delete_stale: bool = True) -> int:
    item = with_revision(item)
    qdrant = _base_url(env, "QDRANT_BASE_URL", "http://qdrant:6333")
    collection = _env_get(env, "QDRANT_COLLECTION", "synapse_notes")
    ollama = _base_url(env, "OLLAMA_INTERNAL_BASE_URL", "http://ollama:11434")
    embed_model = _env_get(env, "OLLAMA_EMBED_MODEL", "nomic-embed-text")
    chunks = chunk_text(str(item.get("index_markdown") or item.get("formatted_markdown") or item.get("content") or ""), str(item["note_id"]))
    max_chunks = _int_env(env, "SYNAPSE_MAX_CHUNKS_PER_NOTE", DEFAULT_MAX_CHUNKS_PER_NOTE)
    if max_chunks > 0 and len(chunks) > max_chunks:
        raise ValueError(f"too many chunks: {len(chunks)} exceeds max_chunks_per_note={max_chunks}")
    if not chunks:
        raise ValueError("No Qdrant points generated; preserving existing chunks")

    batch_size = _int_env(env, "SYNAPSE_EMBED_BATCH_SIZE", DEFAULT_EMBED_BATCH_SIZE)
    vectors: list[list[Any]] = []
    for batch in _batched(chunks, batch_size):
        embed = request_json(
            "POST",
            f"{ollama}/api/embed",
            {"model": embed_model, "input": [chunk.text for chunk in batch]},
            {"Content-Type": "application/json"},
        )
        vectors.extend(_vectors_from_embed_response(embed, len(batch)))

    points = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        points.append(
            {
                "id": chunk.chunk_id,
                "vector": vector,
                "payload": {
                    "schema_version": item["schema_version"],
                    "source": item["source"],
                    "note_id": item["note_id"],
                    "content_hash": item["content_hash"],
                    "current_content_hash": item["current_content_hash"],
                    "revision": item["revision"],
                    "updated_at": item["updated_at"],
                    "ingest_job_id": item["ingest_job_id"],
                    "chunk_hash": chunk.content_hash,
                    "chunk_index": chunk.chunk_index,
                    "title": item["title"],
                    "source_path": item["vault_relative_path"],
                    "vault_relative_path": item["vault_relative_path"],
                    "wiki_path": item["wiki_path"],
                    "path_parts": item.get("path_parts") or [],
                    "source_url": source_url(_env_get(env, "WIKIJS_PUBLIC_BASE_URL", ""), str(item["wiki_path"])),
                    "text": chunk.text,
                },
            }
        )
    request_json(
        "PUT",
        f"{qdrant}/collections/{collection}/points?wait=true",
        {"points": points},
        {"Content-Type": "application/json"},
    )
    new_filter = {
        "must": [
            {"key": "note_id", "match": {"value": item["note_id"]}},
            {"key": "content_hash", "match": {"value": item["content_hash"]}},
        ]
    }
    count_response = request_json(
        "POST",
        f"{qdrant}/collections/{collection}/points/count",
        {"exact": True, "filter": new_filter},
        {"Content-Type": "application/json"},
    )
    result = count_response.get("result") if isinstance(count_response.get("result"), Mapping) else {}
    indexed_count = result.get("count", count_response.get("count"))
    # Never remove the previous revision until Qdrant confirms every new point
    # exists. This is the local replacement transaction's verification step.
    if indexed_count != len(points):
        raise UpstreamError("upstream_qdrant_error", f"Qdrant replacement verification failed: expected {len(points)} points for new content_hash, found {indexed_count}")
    if delete_stale:
        delete_stale_qdrant_chunks(item, env, request_json)
    return len(points)


def ingest(
    payload: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    request_json: JsonRequester | None = None,
) -> dict[str, Any]:
    env = env or os.environ
    requester = request_json or default_request_json
    enforce_content_limit(payload, env)
    note = with_revision(note_from_payload(payload))
    publish = bool(payload.get("publish", True))
    should_format = bool(payload.get("format", publish))
    delete_requested = bool(payload.get("delete", False))
    with note_update_lock(str(note["note_id"])):
        if delete_requested:
            # Remove searchable state first. If publishing deletion fails, the
            # page remains visible but cannot be returned as grounded evidence.
            delete_qdrant_chunks(note, env, requester)
            if publish:
                wiki_result = delete_wikijs(note, env, requester)
                publisher_status = "deleted"
            else:
                wiki_result = {"status": "skipped"}
                publisher_status = "skipped"
            return {
                **note,
                "status": "deleted",
                "publisher": "wikijs" if publish else None,
                "publisher_status": publisher_status,
                "wikijs_result": wiki_result,
                "indexed_chunks": 0,
                "chunks": 0,
                "qdrant_collection": _env_get(env, "QDRANT_COLLECTION", "synapse_notes"),
            }
        if should_format:
            formatted = format_markdown(note, env, requester)
        else:
            formatted = str(payload.get("formatted_markdown") or note["content"])
        item = (
            prepare_publish_payload(note, formatted)
            if publish
            else with_revision({**note, "formatted_markdown": formatted})
        )
        # Publish order is deliberate: index the original source, publish the
        # readable page, then remove stale vectors after both sides succeeded.
        # Index-only requests use their provided formatted content instead.
        index_item = (
            {**item, "index_markdown": note["content"]} if publish else item
        )
        indexed_chunks = index_qdrant(index_item, env, requester, delete_stale=not publish)
        if publish:
            try:
                wiki_result = publish_wikijs(item, env, requester)
            except Exception:  # noqa: BLE001 - rollback must happen regardless of error type.
                # Wiki.js publish failed: roll back newly inserted Qdrant chunks
                # so no searchable chunks exist without a corresponding Wiki.js page.
                rollback_new_qdrant_chunks(item, env, requester)
                raise
            delete_stale_qdrant_chunks(item, env, requester)
        else:
            wiki_result = None
        return {
            **item,
            "status": "ok" if publish else "indexed",
            "publisher": "wikijs" if publish else None,
            "publisher_status": "ok" if publish else "skipped",
            "wikijs_result": wiki_result,
            "indexed_chunks": indexed_chunks,
            "chunks": indexed_chunks,
            "qdrant_collection": _env_get(env, "QDRANT_COLLECTION", "synapse_notes"),
        }
