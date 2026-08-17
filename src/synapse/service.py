"""FastAPI Synapse API service.

This process owns the local webhook/auth boundary and delegates the tested work to
Python ingest and Ask modules.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import asyncio
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ._version import __version__
from .ask import ask, list_indexed_notes
from .ingest import ingest
from .runtime import SynapseRuntime
from .settings import Settings
from .upstream import UpstreamError

app = FastAPI(title="Synapse API", version=__version__)


def _max_parallel() -> int:
    try:
        return max(1, int(float(os.environ.get("SYNAPSE_MAX_PARALLEL_EXECUTIONS", "2"))))
    except ValueError:
        return 2


_WORK_SEMAPHORE = threading.BoundedSemaphore(_max_parallel())


class BusyError(ValueError):
    """Raised when the local lab work queue is full."""


def _run_limited(handler: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    if not _WORK_SEMAPHORE.acquire(blocking=False):
        raise BusyError("too many concurrent Synapse requests; retry later")
    try:
        return handler()
    finally:
        _WORK_SEMAPHORE.release()


async def _read_body_json(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw:
        return {}
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("request body must be a JSON object")
    return parsed


def _json_error(status: int, error_code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error_code": error_code, "error": message})


async def _run_endpoint(path: str, handler: Callable[[], dict[str, Any]]) -> JSONResponse:
    try:
        return JSONResponse(status_code=200, content=await asyncio.to_thread(_run_limited, handler))
    except BusyError as error:
        return _json_error(429, "rate_limited", str(error))
    except ValueError as error:
        return _json_error(400, "bad_request", str(error))
    except UpstreamError as error:
        print(f"synapse-api upstream error on {path}: code={error.error_code} detail={error.detail}", file=sys.stderr, flush=True)
        return _json_error(502, error.error_code, "upstream service unavailable")
    except Exception as error:  # noqa: BLE001 - callers need JSON instead of traceback text.
        print(f"synapse-api error on {path}: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return _json_error(502, "internal_error", "internal service error")


def _auth_disabled(env: Mapping[str, str] = os.environ) -> bool:
    return env.get("SYNAPSE_AUTH_DISABLED", "false").strip().casefold() == "true"


def _expected_token(env: Mapping[str, str] = os.environ) -> str:
    return env.get("SYNAPSE_WEBHOOK_AUTH_TOKEN", "")


def _supplied_token(request: Request) -> str:
    direct = request.headers.get("x-synapse-token", "").strip()
    if direct:
        return direct
    auth = request.headers.get("authorization", "").strip()
    prefix = "bearer "
    if auth.casefold().startswith(prefix):
        return auth[len(prefix) :].strip()
    return ""


def _auth_error(request: Request, env: Mapping[str, str] = os.environ) -> str | None:
    if _auth_disabled(env):
        return None
    expected = _expected_token(env)
    if not expected:
        return "SYNAPSE_WEBHOOK_AUTH_TOKEN is required unless SYNAPSE_AUTH_DISABLED=true"
    if _supplied_token(request) != expected:
        return "Unauthorized: missing or invalid Synapse webhook token"
    return None


def _with_index_only_flags(payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    updated["publish"] = False
    updated["format"] = False
    return updated


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _check_url(url: str, timeout: float = 3.0) -> tuple[bool, str]:
    """Return (ok, detail) for a single URL probe."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        return True, "ok"
    except Exception as exc:  # noqa: BLE001 - readiness probes must not crash.
        return False, str(exc)[:120]


def _check_qdrant(env: Mapping[str, str]) -> tuple[bool, str]:
    base = (env.get("QDRANT_BASE_URL") or "http://qdrant:6333").rstrip("/")
    collection = env.get("QDRANT_COLLECTION", "")
    if not collection:
        return False, "QDRANT_COLLECTION not set"
    ok, detail = _check_url(f"{base}/collections/{collection}")
    if not ok:
        return False, f"qdrant collection unreachable: {detail}"
    return True, "ok"


def _check_ollama(env: Mapping[str, str]) -> tuple[bool, str]:
    base = (env.get("OLLAMA_INTERNAL_BASE_URL") or "http://ollama:11434").rstrip("/")
    ok, detail = _check_url(f"{base}/api/version")
    if not ok:
        # /api/version may not exist on all builds; fall back to /api/tags
        ok2, detail2 = _check_url(f"{base}/api/tags")
        if not ok2:
            return False, f"ollama unreachable: {detail2}"
    return True, "ok"


def _check_wikijs(env: Mapping[str, str]) -> tuple[bool, str]:
    base = (env.get("WIKIJS_BASE_URL") or "http://wikijs:3000").rstrip("/")
    ok, detail = _check_url(base)
    if not ok:
        return False, f"wikijs unreachable: {detail}"
    return True, "ok"


def _check_readiness(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Probe all backend dependencies and return readiness status."""
    env = env if env is not None else os.environ
    checks: dict[str, Any] = {}
    all_ok = True

    qdrant_ok, qdrant_detail = _check_qdrant(env)
    checks["qdrant"] = {"ok": qdrant_ok, "detail": qdrant_detail}
    all_ok = all_ok and qdrant_ok

    ollama_ok, ollama_detail = _check_ollama(env)
    checks["ollama"] = {"ok": ollama_ok, "detail": ollama_detail}
    all_ok = all_ok and ollama_ok

    wikijs_ok, wikijs_detail = _check_wikijs(env)
    checks["wikijs"] = {"ok": wikijs_ok, "detail": wikijs_detail}

    # Wiki.js degradation: not-ready only when publishing is enabled
    # (token present and not a placeholder). Without publishing, wikijs
    # failure is informational but does not block readiness.
    token = env.get("WIKIJS_API_TOKEN", "")
    publishing_enabled = bool(token and not token.startswith("replace-"))
    if publishing_enabled and not wikijs_ok:
        all_ok = False

    checks["publishing"] = {"enabled": publishing_enabled, "blocking": publishing_enabled}

    return {"status": "ready" if all_ok else "not_ready", "checks": checks}


@app.get("/readyz")
def readyz() -> JSONResponse:
    result = _check_readiness()
    status_code = 200 if result["status"] == "ready" else 503
    return JSONResponse(status_code=status_code, content=result)


async def _handle_ask(request: Request) -> JSONResponse:
    """Internal ask handler: parse body, dispatch to ask module."""
    try:
        body = await _read_body_json(request)
    except json.JSONDecodeError as error:
        return _json_error(400, "bad_request", f"invalid JSON: {error.msg}")
    except ValueError as error:
        return _json_error(400, "bad_request", str(error))
    return await _run_endpoint("/ask", lambda: ask(body))


async def _handle_notes(request: Request) -> JSONResponse:
    """Internal notes handler: list Markdown notes present in the live index."""
    try:
        body = await _read_body_json(request)
    except json.JSONDecodeError as error:
        return _json_error(400, "bad_request", f"invalid JSON: {error.msg}")
    except ValueError as error:
        return _json_error(400, "bad_request", str(error))
    return await _run_endpoint("/notes", lambda: list_indexed_notes(body))


async def _handle_ingest(request: Request) -> JSONResponse:
    """Internal ingest handler: parse body, dispatch to ingest module."""
    try:
        body = await _read_body_json(request)
    except json.JSONDecodeError as error:
        return _json_error(400, "bad_request", f"invalid JSON: {error.msg}")
    except ValueError as error:
        return _json_error(400, "bad_request", str(error))
    return await _run_endpoint("/ingest", lambda: ingest(body))


async def _require_auth(request: Request) -> JSONResponse | None:
    """Check auth; return error response if failed, None if OK."""
    error = _auth_error(request)
    if error:
        return _json_error(401, "unauthorized", error)
    return None


@app.post("/webhook/synapse/ask")
@app.post("/ask")
async def ask_endpoint(request: Request) -> JSONResponse:
    auth_err = await _require_auth(request)
    if auth_err:
        return auth_err
    return await _handle_ask(request)


@app.post("/webhook/synapse/notes")
@app.post("/notes")
async def notes_endpoint(request: Request) -> JSONResponse:
    auth_err = await _require_auth(request)
    if auth_err:
        return auth_err
    return await _handle_notes(request)


@app.post("/webhook/synapse/note")
@app.post("/ingest")
async def ingest_endpoint(request: Request) -> JSONResponse:
    auth_err = await _require_auth(request)
    if auth_err:
        return auth_err
    return await _handle_ingest(request)

@app.post("/webhook/synapse/index-note")
async def webhook_index_note_endpoint(request: Request) -> JSONResponse:
    auth_err = await _require_auth(request)
    if auth_err:
        return auth_err
    try:
        body = await _read_body_json(request)
    except json.JSONDecodeError as error:
        return _json_error(400, "bad_request", f"invalid JSON: {error.msg}")
    except ValueError as error:
        return _json_error(400, "bad_request", str(error))
    return await _run_endpoint("/webhook/synapse/index-note", lambda: ingest(_with_index_only_flags(body)))


def create_app(runtime: SynapseRuntime | None = None) -> FastAPI:
    """Create an application using an injected runtime at the external seam."""
    if runtime is None:
        return app

    application = FastAPI(title="Synapse API", version=__version__)

    async def authenticated(request: Request, operation: str) -> JSONResponse:
        error = _auth_error(request)
        if error:
            return _json_error(401, "unauthorized", error)
        try:
            body = await _read_body_json(request)
        except json.JSONDecodeError as exc:
            return _json_error(400, "bad_request", f"invalid JSON: {exc.msg}")
        except ValueError as exc:
            return _json_error(400, "bad_request", str(exc))
        handlers = {
            "ask": runtime.answer_question,
            "notes": runtime.indexed_notes,
            "ingest": runtime.ingest_note,
            "index": lambda payload: runtime.ingest_note(_with_index_only_flags(dict(payload))),
        }
        return await _run_endpoint(request.url.path, lambda: handlers[operation](body))

    async def ask_route(request: Request) -> JSONResponse:
        return await authenticated(request, "ask")

    async def notes_route(request: Request) -> JSONResponse:
        return await authenticated(request, "notes")

    async def ingest_route(request: Request) -> JSONResponse:
        return await authenticated(request, "ingest")

    async def index_route(request: Request) -> JSONResponse:
        return await authenticated(request, "index")

    application.add_api_route("/healthz", healthz, methods=["GET"])
    application.add_api_route("/readyz", readyz, methods=["GET"])
    for path in ("/ask", "/webhook/synapse/ask"):
        application.add_api_route(path, ask_route, methods=["POST"])
    for path in ("/notes", "/webhook/synapse/notes"):
        application.add_api_route(path, notes_route, methods=["POST"])
    for path in ("/ingest", "/webhook/synapse/note"):
        application.add_api_route(path, ingest_route, methods=["POST"])
    application.add_api_route("/webhook/synapse/index-note", index_route, methods=["POST"])
    return application


def main() -> int:
    import uvicorn

    port = int(os.environ.get("SYNAPSE_SERVICE_PORT", "15515"))
    host = os.environ.get("SYNAPSE_SERVICE_HOST")
    if not host:
        host = ".".join(("0", "0", "0", "0")) if os.environ.get("SYNAPSE_CONTAINER_BIND") == "true" else "127.0.0.1"
    settings = Settings.from_env()
    settings.validate()
    uvicorn.run(create_app(SynapseRuntime.from_env(settings)), host=host, port=port, log_level=os.environ.get("SYNAPSE_UVICORN_LOG_LEVEL", "info"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
