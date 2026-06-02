#!/usr/bin/env python3
"""Create the Qdrant collection that matches the active Ollama embedding model."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

PROBE_TEXT = "synapse vector dimension probe"
DEFAULT_COLLECTION_BASE = "synapse_notes"
DEFAULT_EMBED_MODEL = "nomic-embed-text"
DEFAULT_DISTANCE = "Cosine"

RequestJson = Callable[[str, dict[str, Any] | None, str | None], dict[str, Any]]


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise SystemExit(f"missing {path}; run make lab-up first")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    replacement = f"{key}={value}"
    for index, line in enumerate(lines):
        if line.startswith(f"{key}="):
            if line == replacement:
                return
            lines[index] = replacement
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    lines.append(replacement)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def strip_base_url(value: str | None, fallback: str) -> str:
    return (value or fallback).strip().rstrip("/")


def model_slug(model: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", model.strip().lower()).strip("_")
    return slug or "embedding_model"


def derived_collection_name(base: str, embedding_model: str, dimension: int) -> str:
    return f"{model_slug(base)}__{model_slug(embedding_model)}__{dimension}"


def extract_vector(response: dict[str, Any]) -> list[Any]:
    embeddings = response.get("embeddings")
    if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
        return embeddings[0]
    embedding = response.get("embedding")
    if isinstance(embedding, list):
        return embedding
    raise SystemExit(f"Ollama embed probe returned no embedding vector: {response}")


def default_request_json(url: str, payload: dict[str, Any] | None = None, method: str | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method or ("POST" if payload is not None else "GET"),
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def request_json_with_retries(
    request_json: RequestJson,
    url: str,
    payload: dict[str, Any] | None = None,
    method: str | None = None,
    *,
    attempts: int = 30,
    delay_seconds: float = 2.0,
) -> dict[str, Any]:
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return request_json(url, payload, method)
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                raise
            last_error = exc
        except urllib.error.URLError as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(delay_seconds)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}") from last_error


def ollama_host_url(env: dict[str, str]) -> str:
    if env.get("OLLAMA_HOST_BASE_URL"):
        return strip_base_url(env["OLLAMA_HOST_BASE_URL"], "")
    if env.get("OLLAMA_INTERNAL_BASE_URL") and env.get("QDRANT_VECTOR_SIZE"):
        # Mocked CI keeps Ollama Compose-internal and supplies an explicit fixture size.
        return strip_base_url(env["OLLAMA_INTERNAL_BASE_URL"], "")
    return f"http://127.0.0.1:{env.get('OLLAMA_PORT', '11434')}"


def qdrant_host_url(env: dict[str, str]) -> str:
    if env.get("QDRANT_HOST_BASE_URL"):
        return strip_base_url(env["QDRANT_HOST_BASE_URL"], "")
    return f"http://127.0.0.1:{env.get('QDRANT_PORT', '6333')}"


def embedding_dimension(env: dict[str, str], request_json: RequestJson = default_request_json) -> int:
    if env.get("QDRANT_VECTOR_SIZE") and not env.get("OLLAMA_HOST_BASE_URL"):
        try:
            return int(env["QDRANT_VECTOR_SIZE"])
        except ValueError as exc:
            raise SystemExit(f"invalid QDRANT_VECTOR_SIZE={env['QDRANT_VECTOR_SIZE']!r}") from exc
    model = env.get("OLLAMA_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    response = request_json_with_retries(request_json, f"{ollama_host_url(env)}/api/embed", {"model": model, "input": PROBE_TEXT}, None)
    vector = extract_vector(response)
    if not vector:
        raise SystemExit("Ollama embed probe returned an empty vector")
    return len(vector)


def collection_metadata(collection_info: dict[str, Any]) -> dict[str, Any]:
    result = collection_info.get("result", {}) if isinstance(collection_info, dict) else {}
    metadata = result.get("metadata") or result.get("config", {}).get("params", {}).get("metadata") or {}
    return metadata if isinstance(metadata, dict) else {}


def vector_config(collection_info: dict[str, Any]) -> tuple[Any, Any]:
    vectors = collection_info.get("result", {}).get("config", {}).get("params", {}).get("vectors", {})
    if isinstance(vectors, dict) and ("size" in vectors or "distance" in vectors):
        return vectors.get("size"), vectors.get("distance")
    return None, None


def collection_base(env: dict[str, str]) -> str:
    return env.get("QDRANT_COLLECTION_BASE") or DEFAULT_COLLECTION_BASE


def should_manage_collection(env: dict[str, str]) -> bool:
    raw = env.get("SYNAPSE_MANAGE_QDRANT_COLLECTION", "true").strip().lower()
    return raw not in {"0", "false", "no"}


def expected_collection(env: dict[str, str], model: str, dimension: int) -> str:
    if should_manage_collection(env):
        return derived_collection_name(collection_base(env), model, dimension)
    return env.get("QDRANT_COLLECTION") or derived_collection_name(collection_base(env), model, dimension)


def apply_collection_metadata(request_json: RequestJson, qdrant: str, collection: str, metadata: dict[str, Any]) -> None:
    request_json_with_retries(request_json, f"{qdrant}/collections/{collection}", {"metadata": metadata}, "PATCH")


def ensure_collection(
    env: dict[str, str],
    *,
    env_file: Path | None = None,
    request_json: RequestJson = default_request_json,
) -> dict[str, Any]:
    model = env.get("OLLAMA_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    dimension = embedding_dimension(env, request_json)
    collection = expected_collection(env, model, dimension)
    metadata = {"embedding_model": model, "embedding_dimension": dimension}
    qdrant = qdrant_host_url(env)

    if env_file is not None and should_manage_collection(env):
        write_env_value(env_file, "QDRANT_COLLECTION", collection)
        env["QDRANT_COLLECTION"] = collection

    try:
        info = request_json_with_retries(request_json, f"{qdrant}/collections/{collection}", None, None)
    except RuntimeError as exc:
        if "404" not in str(exc):
            raise
    else:
        actual_size, actual_distance = vector_config(info)
        actual_metadata = collection_metadata(info)
        if actual_size == dimension and actual_distance == DEFAULT_DISTANCE and actual_metadata.get("embedding_model") == model:
            return {"collection": collection, "embedding_model": model, "embedding_dimension": dimension}
        if actual_size == dimension and actual_distance == DEFAULT_DISTANCE and not actual_metadata.get("embedding_model"):
            apply_collection_metadata(request_json, qdrant, collection, metadata)
            return {"collection": collection, "embedding_model": model, "embedding_dimension": dimension}
        raise SystemExit(
            "Qdrant collection schema mismatch for "
            f"{collection}: expected size={dimension} distance={DEFAULT_DISTANCE} embedding_model={model}; "
            f"actual size={actual_size} distance={actual_distance} "
            f"actual embedding_model={actual_metadata.get('embedding_model', 'unknown')}. "
            "Use a new QDRANT_COLLECTION name or recreate the collection."
        )

    request_json_with_retries(
        request_json,
        f"{qdrant}/collections/{collection}",
        {"vectors": {"size": dimension, "distance": DEFAULT_DISTANCE}, "metadata": metadata},
        "PUT",
    )
    apply_collection_metadata(request_json, qdrant, collection, metadata)
    return {"collection": collection, "embedding_model": model, "embedding_dimension": dimension}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=os.environ.get("SYNAPSE_ENV_FILE", str(Path(__file__).resolve().parents[2] / ".env")))
    args = parser.parse_args(argv)
    env_file = Path(args.env_file)
    env = load_dotenv(env_file)
    result = ensure_collection(env, env_file=env_file)
    print(
        "Qdrant collection ready: "
        f"{result['collection']} (embedding_model={result['embedding_model']}, dimension={result['embedding_dimension']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
