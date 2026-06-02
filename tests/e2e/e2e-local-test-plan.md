# Local E2E test plan

Goal: prove the localhost Synapse stack can move a fresh note through FastAPI, Wiki.js, Qdrant, and RAG retrieval.

## Preconditions

- `.env` exists and is ignored.
- `WIKIJS_API_TOKEN` is a real Wiki.js API token.
- `SYNAPSE_WEBHOOK_AUTH_TOKEN` is set for authenticated webhook calls.
- Docker volumes are preserved; do not remove volumes for this test.

## Command

```bash
scripts/e2e/local-e2e-proof.sh
```

## Gates

The script fails unless all of these pass:

- FastAPI, Wiki.js, Qdrant, and Ollama HTTP checks return 200.
- A fresh note webhook response returns `status: ok` and `publisher: wikijs`.
- The created Wiki.js page contains the unique proof phrase.
- Qdrant contains points for the returned `note_id`.
- The RAG answer includes the unique proof phrase and sources.

## Evidence

Sanitized outputs are written to:

- `.local-artifacts/evidence/local-e2e-report.md`
- `.local-artifacts/evidence/local-e2e-latest.json`

A reviewer-friendly summary lives in [docs/SETUP.md](../../docs/SETUP.md).

Evidence must not contain real tokens or localhost IP addresses.
