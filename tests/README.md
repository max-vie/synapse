# Tests

The normal suite protects public interfaces without Docker, network access, real tokens, Ollama, Wiki.js, or Qdrant.

```bash
make test
python -m pytest -q
python -m pytest tests/app/test_rag.py -q
make evaluate
```

## Structure

| Directory | Interface under test |
|---|---|
| `ask/` | Ask CLI, HTTP client, output safety, TUI state, rendering, and fallback behavior |
| `app/` | Metadata, ingest, RAG, runtime, FastAPI routes, auth, readiness, and sanitized errors |
| `tooling/` | Lab lifecycle, proof scenarios, benchmarks, repository checks, and capture harness |
| `contracts/` | Package version, Compose safety defaults, image pins, CI gates, and reviewer example data |

`conftest.py` isolates Synapse environment variables so a sourced local `.env` cannot change test results.

`make evaluate` runs the deterministic source-grounded evaluation. Its in-memory
adapters prove policy behavior and report grounding, refusal, citation, and
prompt-injection metrics; they do not measure a live model's answer quality.

## Rules

- Test through the module interface whenever possible; avoid private dictionaries, globals, coordinates, and source-text assertions.
- Use parameterized tables for equivalent input classes instead of one test per literal.
- Keep secrets fake and assert that public errors and evidence remain sanitized.
- Add focused regression coverage for a reproduced bug, then prefer observable outcomes over implementation order.
- Run live behavior through `make proof`, `make mocked-fastapi-qdrant-e2e`, or `make real-local-stack-proof`; pytest success is not live-stack proof.
