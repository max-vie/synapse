# Local E2E lab

This lab runs the Synapse services in Docker Compose with persisted volumes.

Services:

- Synapse API: `http://localhost:15515`
- Wiki.js: `http://localhost:3000`
- Qdrant: `http://localhost:6333`
- Ollama: `http://localhost:11434`

## Setup

```bash
scripts/e2e/setup.sh
scripts/e2e/start.sh
scripts/e2e/pull-models.sh
scripts/e2e/create-qdrant-collection.sh
```

Then create a Wiki.js API key in the admin UI and store it in ignored `.env` as `WIKIJS_API_TOKEN`.

## Import workflows

```bash
```

The import is safe to rerun: old Synapse workflows are deactivated and only the latest generated workflow for each stable name is active.

## Localhost access

The compose file binds FastAPI, Wiki.js, Qdrant, and Ollama to localhost only. Run `make lab-status` on the lab host to print the local URLs.

## Live proof

```bash
scripts/e2e/local-e2e-proof.sh
```

The proof creates a fresh Markdown note, posts it to FastAPI with required webhook auth, verifies Wiki.js page content, verifies Qdrant payloads, asks the RAG webhook, and writes sanitized evidence under `.local-artifacts/evidence/`.

## Stop without deleting data

```bash
scripts/e2e/stop.sh
```

This stops containers but preserves Docker volumes.
