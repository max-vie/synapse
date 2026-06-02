# scripts/

Automation, service code, and tooling for the Synapse project.

## Use Makefile first

Most tasks have a Makefile target. Prefer these over calling scripts directly:

| Target | What it does |
|---|---|
| `make lab-up` | Start the full local lab stack |
| `make configure` | Generate `.env` and set up Qdrant collection |
| `make proof` | Run local e2e proof against a live lab |
| `make demo` | Run the Ask demo script |
| `make check` | Run tests, validation, hygiene, and link checks |
| `make lab-down` | Stop the local lab stack |
| `make update-check` | Check for base image updates |

## Directory map

| Path | Purpose |
|---|---|
| `scripts/e2e/` | Lab lifecycle and proof helpers |
| `scripts/synapse/` | FastAPI service modules (tested, not throwaway) |
| `scripts/ci/` | CI security and release hygiene |
| `scripts/benchmark/` | Optional local model benchmark tools |
| `scripts/capture/` | GIF/capture tooling — see [capture/README.md](capture/README.md) |

## Top-level scripts

| Script | What it does |
|---|---|
| `demo.py` | Run the Ask demo |
| `validate.py` | Validate `.env` and config |
| `public_hygiene.py` | Check repo for leaked secrets |
| `check_docs_links.py` | Find broken doc links |
| `check_image_versions.py` | Check Docker base image freshness |
| `check_removed_publisher.py` | Detect removed n8n publisher traces |

## Details by directory

**`scripts/e2e/`** — Lab lifecycle helpers (`start.sh`, `stop.sh`, `setup.sh`, `remove.sh`, `status.sh`, `start-synapse.sh`) and proof runners (`local-e2e-proof.sh`, `real-local-stack-proof.sh`). Normally called through Makefile targets like `make lab-up` and `make proof`.

**`scripts/synapse/`** — The actual FastAPI service: `service.py` (app/entrypoint), `http_client.py`, `ingest.py`, `metadata.py`, `upstream.py`, `ask.py`. These are tested modules imported by the service container, not one-off helpers.

**`scripts/ci/`** — Security scanning and release hygiene used in CI pipelines. Not intended for local dev.

**`scripts/benchmark/`** — Optional tools for benchmarking local Ollama models against quality criteria.

**`scripts/capture/`** — GIF and screenshot capture tooling for demos. See [capture/README.md](capture/README.md) for usage.

## Safety notes

- **`.env`** is private — never committed; contains local secrets.
- **`.local-artifacts/`** is local-only output; gitignored.
- **`scripts/e2e/remove.sh`** is destructive — stops containers, removes volumes, deletes `.env` and `.local-artifacts/`.
- Proof scripts verify a **local lab**, not production readiness.