# Setup

This guide gets you from a fresh clone to a started local Synapse lab, then through the manual Wiki.js token check needed for proof.

Synapse runs only on your machine. Services bind to localhost, secrets stay in `.env`, and lab commands leave existing Docker volumes untouched.

## Before you start

Install the required tools on a Debian-family or RHEL-family Linux system.

1. Install Python 3, `make`, `docker`, and `docker compose`.

   Debian, Ubuntu, or WSL with `apt`:

   ```bash
   sudo apt install -y python3 make docker.io docker-compose-plugin
   sudo systemctl enable --now docker
   ```

   Fedora, RHEL, or similar with `dnf`:

   ```bash
   sudo dnf install -y python3 make docker docker-compose-plugin
   sudo systemctl enable --now docker
   ```

2. Check that the commands work.

   ```bash
   python3 --version
   make --version
   docker --version
   docker compose version
   ```

3. Show the project commands.

   ```bash
   make help
   ```

## Live local lab flow

Use `make lab-up`, `make configure`, and `make proof` as separate steps. `make lab-up` starts services; `make configure` checks the manual Wiki.js API-token step; `make proof` runs the live evidence script only after that check passes.

Start from the repository root:

```bash
make lab-up
```

The lab-up command does five things:

1. checks that the required commands exist;
2. creates `.env` with generated local secrets if the file is missing;
3. starts the localhost-only Docker lab;
4. pulls the default local Ollama models: `nomic-embed-text` for embeddings and `tinyllama:latest` for format/answer prompts;
5. prepares Qdrant and starts the FastAPI Synapse service.

The command may take a while the first time because Docker images and models need to download. It is not the complete setup: Wiki.js still needs a one-time admin/token step before the live proof can pass.

## Check that services are up

After `make lab-up` finishes, print the service status and local URLs:

```bash
make lab-status
```

Open these in your browser:

- Synapse API: `http://localhost:15515`
- Wiki.js: `http://localhost:3000`
- Qdrant: `http://localhost:6333`

Ollama runs inside Compose at `http://ollama:11434` for the Synapse API container. Host-side scripts use `http://127.0.0.1:11434`. You usually do not open either endpoint in a browser.

### Optional Ollama Cloud relay

To exercise cloud generation without using the host Ollama daemon, set these values in the private `.env` before running `make lab-up`:

```dotenv
OLLAMA_CLOUD_MODE=true
OLLAMA_CLOUD_KEY_FILE=/usr/share/ollama/.ollama/id_ed25519
OLLAMA_CLOUD_PUBLIC_KEY_FILE=/usr/share/ollama/.ollama/id_ed25519.pub
OLLAMA_FORMAT_MODEL=gpt-oss:20b-cloud
OLLAMA_ANSWER_MODEL=gpt-oss:20b-cloud
OLLAMA_EMBED_MODEL=nomic-embed-text
```

The lab then applies `docker-compose.cloud-e2e.yml`, mounts the signed-in Ollama key read-only, and lets the isolated Ollama container relay cloud-capable generation models. The embedding model remains local because Ollama Cloud does not currently publish an embedding model. Never commit either key path's contents or an Ollama API key. Keep the key files readable only by the account that runs the lab.

## Configure Wiki.js API token

`make configure` is a local check for the manual Wiki.js API and token step. The lab services can start without a Wiki.js API token, but the live proof needs the Wiki.js API enabled and a usable token so Synapse can create, update, and read pages.

Steps:

1. open `http://localhost:3000`;
2. finish the Wiki.js first-run admin setup if it appears;
3. open the Wiki.js Administration Area and enable the API;
4. create an API token with page create/update/read permission;
5. open the `.env` file in this repo;
6. replace the placeholder value for `WIKIJS_API_TOKEN`;
7. check the token and live API:

```bash
make configure
```

8. restart the lab services if you changed `.env` while services were already running:

```bash
make lab-down
make lab-up
```

## Run the live proof

After `make configure` passes, run:

```bash
make proof
```

The proof sends a fresh note through the FastAPI Synapse webhook, checks that Wiki.js received it, checks that Qdrant indexed it, verifies the Wiki.js `synapse_content_hash` matches the Qdrant `current_content_hash`, asks the RAG webhook a question, and writes sanitized evidence under `.local-artifacts/evidence/`.

For a stronger manual proof with real Ollama embedding/answer models, real Wiki.js GraphQL create/update/readback, Qdrant using the probed embedding-model dimension, five realistic notes, and ten realistic questions, run:

```bash
make real-local-stack-proof
```

CI uses a cheaper mocked plumbing proof:

```bash
make mocked-fastapi-qdrant-e2e
```

That CI proof uses a Compose-internal mock Ollama and no Wiki.js. It proves FastAPI webhook execution, Synapse API routing, and Qdrant canary retrieval only; it does not prove real model quality, real embedding dimensions, real Wiki.js behavior, or realistic notes. The optional `real-local-stack-proof` GitHub workflow is manual and self-hosted only; the runner must have a private `.env` at the path configured in the `SYNAPSE_ENV_FILE` repository variable (kept outside the Git checkout so stale files from prior runs are removed).

## Ask questions from the terminal

`Ask/ask.py` talks to the live FastAPI Ask webhook by default. It auto-loads `SYNAPSE_ASK_WEBHOOK_URL` and `SYNAPSE_WEBHOOK_AUTH_TOKEN` from the project `.env` file; if those vars are already exported in your shell, the shell values take priority.

Open the full terminal UI:

```bash
python3 "Ask/ask.py"
```

Ask one question without opening the full UI:

```bash
python3 "Ask/ask.py" --text "What is in my indexed notes?"
```

Get structured JSON output:

```bash
python3 "Ask/ask.py" --json "What is in my indexed notes?"
```

Get the raw response object for scripting:

```bash
python3 "Ask/ask.py" --raw-json "What is in my indexed notes?"
```

Use dry-run only when you intentionally want a no-network preview:

```bash
python3 "Ask/ask.py" --dry-run --raw-json "What algorithm does OSPF use?" --note "examples/obsidian-vault/Synapse-Demo/example-study-notes.md"
```

### TUI commands

| Command | Action |
|---|---|
| `/notes` | List indexed notes from live Synapse (requires webhook or `--dry-run`) |
| `/local-notes` | Browse local vault Markdown files (always works offline) |
| `/!1` | Show answer 1 again |
| `/help` | Show all commands |
| `/clear` | Clear transcript |
| `/quit` | Exit |

If `/notes` shows "No live Synapse webhook configured", set `SYNAPSE_ASK_WEBHOOK_URL` or use `--dry-run`. Type `/local-notes` to browse vault files without a live connection.

For Ask-specific errors and troubleshooting, see [Ask/TROUBLESHOOTING.md](../Ask/TROUBLESHOOTING.md).

## Daily commands

Show available commands:

```bash
make help
```

Create or refresh `.env` and start services:

```bash
make lab-up
```

Check the manual Wiki.js token setup:

```bash
make configure
```

Show service status:

```bash
make lab-status
```

Show service logs:

```bash
make lab-logs
```

Stop the lab without deleting data:

```bash
make lab-down
```

Run local release checks:

```bash
make check
```

## Environment files

`.env.example` is the safe template committed to git.

`.env` is your private local config. `make lab-up` creates it automatically if it does not exist. It contains generated values for:

- `SYNAPSE_WEBHOOK_AUTH_TOKEN`
- `SYNAPSE_AUTH_DISABLED=false`
- `WIKIJS_DB_PASSWORD`

You usually edit only these values:

- `WIKIJS_API_TOKEN`: add this after Wiki.js admin setup.
- `OLLAMA_FORMAT_MODEL` and `OLLAMA_ANSWER_MODEL`: `make lab-up` defaults both to `tinyllama:latest` so a low-resource reviewer can pull and run the lab. Larger benchmarked models such as `gemma3:12b` or `gemma3:27b` are optional overrides; expect much larger downloads and roughly 16 GB+ RAM for 12B-class models or 32 GB+ RAM/VRAM for 27B-class models.
- `OLLAMA_EMBED_MODEL`: embedding model for Qdrant indexing. `make lab-up` probes this model once through Ollama, measures the returned vector length, and manages `QDRANT_COLLECTION` as `synapse_notes__<embedding_model>__<dimension>`.
- `QDRANT_COLLECTION_BASE`: prefix for managed collection names. Default `synapse_notes`.
- `SYNAPSE_MANAGE_QDRANT_COLLECTION`: keep `true` for the normal lab so setup can update `QDRANT_COLLECTION` when the embedding model or dimension changes.
- `OLLAMA_INTERNAL_BASE_URL`: container URL for Ollama. Keep the default `http://ollama:11434` unless the Synapse API should call a different container-reachable Ollama endpoint.
- `OLLAMA_HOST_BASE_URL`: host-side proof URL for Ollama. Keep the default `http://127.0.0.1:11434` for the local Compose lab.
- `OLLAMA_CHAT_BASE_URL`: optional container-reachable chat override. Leave unset for the normal local lab.
- `OLLAMA_CLOUD_MODE`: set `true` to apply the signed-in cloud relay overlay; leave `false` for the normal local lab.
- `OLLAMA_CLOUD_KEY_FILE` and `OLLAMA_CLOUD_PUBLIC_KEY_FILE`: host paths to the signed-in Ollama key pair used by the cloud overlay. They are mounted read-only and are never copied into the checkout.
- `SYNAPSE_MAX_CONTENT_BYTES`: maximum note body accepted before formatting/indexing. Default `262144`.
- `SYNAPSE_MAX_CHUNKS_PER_NOTE`: maximum chunks indexed for one note. Default `32`.
- `SYNAPSE_MAX_QUESTION_LENGTH`: maximum Ask question length. Default `1000`.
- `SYNAPSE_MAX_PARALLEL_EXECUTIONS`: concurrent Synapse API work items. Default `2`.
- `SYNAPSE_EMBED_BATCH_SIZE`: chunk embeddings per Ollama `/api/embed` request. Default `16`.
- `SYNAPSE_HTTP_TIMEOUT_SECONDS`: timeout for Ollama, Qdrant, and Wiki.js requests. Default `180` seconds so larger local models can respond without failing the workflow early.
- `RAG_TOP_K`: number of top Qdrant results to keep after score filtering. Default `5`.
- `RAG_CANDIDATE_K`: initial Qdrant query limit before score and grounding filters. Default `25`. Must be `>=` `RAG_TOP_K`.
- `RAG_SCORE_THRESHOLD`: minimum Qdrant similarity score for a result to be accepted. Default `0.35`. Set `0` to accept all.
- `RAG_QUERY_TERM_MIN_COVERAGE`: fraction of query term groups that must match a chunk for it to pass grounding. Default `0.6`.
- `RAG_QUERY_TERM_MIN_MATCHES`: minimum number of query term groups that must match a chunk regardless of coverage. Default `2`.
- `RAG_DOMAIN_GLOSSARY_JSON`: JSON object mapping canonical terms to alias lists for query expansion. Default `{}`.
- `SYNAPSE_ANSWER_VALIDATION`: how strictly to validate LLM answers against source quotes. `structural` (default) checks citation format only. `quote_overlap` checks trigram overlap between the answer and `quoted_support` (refuses below threshold). `extractive` requires the answer text to appear verbatim in the quoted support.
- `RAG_QUOTE_OVERLAP_THRESHOLD`: minimum trigram overlap ratio for `quote_overlap` validation. Default `0.3`. Set lower to allow looser paraphrases; higher to demand closer matches.

Ask responses include cited sources plus a `quoted_support` snippet from the retrieved chunk. With `SYNAPSE_ANSWER_VALIDATION=structural` (default), the citation gate checks valid citation numbers and source locators only; it does not prove the answer is factually correct. Use `quote_overlap` or `extractive` validation modes to refuse answers that lack support from the quoted source text.

Note: `.env` is private. Do not commit it, share it, or paste real token values into docs, issues, benchmark output, screenshots, or chat. Keep `SYNAPSE_AUTH_DISABLED=false` for the live lab; `SYNAPSE_AUTH_DISABLED=true` is only for no-network demo runs.

## Reviewer demo

The reviewer demo is the safe preview path. It uses no Docker, no `.env`, no tokens, and no network calls.

```bash
make demo
```

Use this for a quick repository check. Use the explicit local lab flow when you want to prove the actual lab:

```bash
make lab-up
make configure
make proof
```

## Troubleshooting

Docker daemon is not reachable:
- Start the Docker service with `sudo systemctl start docker`.
- Make sure your current shell has Docker group access, or run `make lab-up` from a shell that can use Docker.
- Retry `make lab-up`.

Synapse API or Wiki.js does not open:
- Run `make lab-status`.
- Check that the listed localhost ports are running.
- Run `make lab-logs` if a service exited.

Ask returns unauthorized:
- Export the same `SYNAPSE_WEBHOOK_AUTH_TOKEN` that is in `.env`.
- Make sure the Synapse API service was restarted after env changes with `make lab-up`.

Wiki.js proof fails:
- Check that `WIKIJS_API_TOKEN` is set in `.env`.
- Make sure the token can create and update pages.
- Run `make lab-up`, then retry `make proof`.

Qdrant proof fails:
- Run `make lab-up`, then retry `make proof`.

Tests fail because `pytest` is missing:
- Use `make demo` for the no-dependency preview.
- Install test dependencies before running `make check`.

## Safety notes

- Services bind to localhost, not a public interface.
- `.env` stays private. Do not commit or share it.
- `.local-artifacts/` stays out of git unless you intentionally sanitize a file first.
- `make lab-down` stops containers but keeps named Docker volumes.
- Do not run `docker compose down -v` unless you intentionally want to delete lab data.
- Treat `make proof` as local lab evidence, not production readiness.
