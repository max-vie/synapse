# tests/

The Synapse test suite protects the local lab stack, Ask CLI/TUI, FastAPI service boundary, ingest/RAG behavior, public output hygiene, CI configuration, benchmark utilities, and capture workflow.

## How to run

```bash
make test                     # via Makefile
python -m pytest -q           # all tests
python -m pytest tests/test_ask_cli.py -q   # single file
```

## Test categories

| Category | Files | What they cover |
|---|---|---|
| Ask CLI/TUI | `test_ask_cli.py`, `test_ask_tui.py`, `test_ask_tui_state.py` | Command parsing, curses fallback, TUI state transitions |
| Ask formatting/source-safety | `test_ask_formatting.py`, `test_ask_http_sanitization.py` | Public-safe output, URL/path hiding, error redaction |
| Ask package/dotenv/notes | `test_ask_dotenv.py`, `test_ask_notes.py`, `test_ask_package_structure.py`, `test_ask_dry_run.py` | Config loading, vault resolution, package init, dry-run paths |
| Synapse metadata/ingest/RAG | `test_synapse_ask.py`, `test_rag_grounding_regressions.py`, `test_metadata.py`, `test_synapse_ingest.py` | Ask pipeline, grounding, coverage, metadata, ingest |
| FastAPI/auth/readiness | `test_synapse_service_fastapi.py`, `test_webhook_auth.py`, `test_synapse_http_client.py` | Endpoints, auth, readiness, upstream errors |
| e2e/CI configuration | `test_ci_e2e_config.py`, `test_version_policy.py`, `test_local_limits_config.py` | Compose files, scripts, version single-source, limits |
| Public hygiene/security | `test_public_hygiene.py`, `test_dependency_hygiene.py`, `test_validate.py` | No secrets in output, dependency policy, config validation |
| Benchmark/report | `test_benchmark_*.py`, `test_workflow_benchmark_config.py` | Model matrix, scoring, report generation, fixtures |
| Capture/GIF | `test_capture_ask_gif.py` | GIF capture workflow |
| Example data | `test_example_study_note.py` | Demo vault note content |

## Normal pytest should stay local

Normal tests must **not** require Docker, live Ollama, Wiki.js, Qdrant, real API tokens, or network access. Use fake requesters and mocks for HTTP. Tests that need a live stack belong in `scripts/e2e/`, not in `pytest`.

## When adding tests

- Prefer focused regression tests — one bug, one test.
- Never hardcode real secrets; use dummy values.
- Mock HTTP calls with fake requesters or `unittest.mock`.
- Live-stack proof goes in `scripts/e2e/` via `make proof`, `make mocked-fastapi-qdrant-e2e`, or `make real-local-stack-proof`.
- Add a regression test when fixing a bug.