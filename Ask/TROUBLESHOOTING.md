# Synapse Ask Troubleshooting

> Common fixes for the Synapse Ask terminal client and its live Synapse RAG connection.

Use this file when the Ask TUI or one-shot commands do not reach the live stack, return an auth error, or refuse to answer because no usable source evidence was found.

## Quick checks

Run these first from the repository root:

```bash
make lab-status
curl -i http://localhost:15515/healthz
curl -i http://localhost:15515/readyz
```

Check the Ask environment:

```bash
grep -E '^(SYNAPSE_ASK_WEBHOOK_URL|SYNAPSE_WEBHOOK_AUTH_TOKEN)=' .env
```

Run a direct Ask request:

```bash
python3 "Ask/ask.py" --raw-json "What is in my indexed notes?"
```

## Missing webhook URL

Error:

```text
Missing SYNAPSE_ASK_WEBHOOK_URL
```

Cause: Ask has no live webhook URL and `--dry-run` was not used.

Fix:

```bash
export SYNAPSE_ASK_WEBHOOK_URL="http://localhost:15515/webhook/synapse/ask"
python3 "Ask/ask.py" --text "What is Synapse?"
```

If you only want a no-network preview:

```bash
python3 "Ask/ask.py" --dry-run --text "What is Synapse?"
```

## HTTP 401

Cause: the webhook token is missing, wrong, or not loaded from `.env`.

Fix:

```bash
export SYNAPSE_WEBHOOK_AUTH_TOKEN="<value-from-.env>"
python3 "Ask/ask.py" --text "What is Synapse?"
```

Verify the token exists locally:

```bash
grep '^SYNAPSE_WEBHOOK_AUTH_TOKEN=' .env
```

Do not paste real token values into issues, screenshots, or public docs.

## HTTP 502 or upstream error

Cause: the Synapse API is reachable, but one of its backend services failed.

Check the stack:

```bash
make lab-status
make lab-logs
```

Check service readiness:

```bash
curl -i http://localhost:15515/readyz
```

Common causes:

- Ollama is not reachable.
- Required Ollama model is not pulled.
- Qdrant collection is missing or stale.
- Wiki.js API token is missing or invalid.
- Synapse was started before `.env` was updated.

Fix the stack, then restart the lab:

```bash
make lab-down
make lab-up
make configure
```

## Dry run works, live mode fails

Cause: dry run does not use the live Synapse stack. It only checks local CLI behavior and metadata/chunk preview.

Verify the live path:

```bash
make lab-up
make configure
make proof
```

Then retry:

```bash
python3 "Ask/ask.py" --raw-json "What is in my indexed notes?"
```

## No sources returned

Cause: the live response did not include usable source evidence, or the question does not match indexed note content.

Check that notes were indexed:

```bash
make proof
```

Ask a question that is directly answerable from an indexed note:

```bash
python3 "Ask/ask.py" --raw-json "What algorithm does OSPF use?" \
  --source-path "Synapse-Demo/example-study-notes.md"
```

If this works, the issue is probably the original question or filter scope.

## Filter returns no answer

Cause: one of the live filters is too narrow or does not match indexed metadata.

Check the filter value:

| Filter | Check |
|---|---|
| `--source-path` | Must match the indexed Markdown source path |
| `--note-id` | Must match the deterministic Synapse note ID |
| `--wiki-path` | Must match the Wiki.js path, usually starting with `/` |
| `--exact-run-id` | Must match the proof/evidence run ID |

Retry without filters:

```bash
python3 "Ask/ask.py" --raw-json "What algorithm does OSPF use?"
```

Then add one filter at a time.

## TUI does not render correctly

Use script mode to verify Ask works without the full-screen TUI:

```bash
python3 "Ask/ask.py" --text "What is Synapse?"
```

Disable color:

```bash
python3 "Ask/ask.py" --no-color
```

Use raw JSON when debugging terminal rendering separately from backend behavior:

```bash
python3 "Ask/ask.py" --raw-json "What is Synapse?"
```

## `/notes` returns nothing or shows "No live Synapse webhook configured"

`/notes` queries **live Synapse indexed notes only**. It does not fall back to local files. It requires a configured `SYNAPSE_ASK_WEBHOOK_URL` or `--dry-run` mode.

**No webhook URL configured:**

If `SYNAPSE_ASK_WEBHOOK_URL` is not set and `--dry-run` is not active, `/notes` shows:

```text
No live Synapse webhook configured; use --dry-run for local note preview, or /local-notes to browse the vault.
```

Fix — configure the webhook:

```bash
export SYNAPSE_ASK_WEBHOOK_URL="http://localhost:15515/webhook/synapse/ask"
python3 "Ask/ask.py" --text "What is Synapse?"
```

Or use `--dry-run` to preview local note metadata without network:

```bash
python3 "Ask/ask.py" --dry-run
```

Or browse local vault files offline with `/local-notes`.

**Webhook returns an empty list:**

The Qdrant collection may be empty or the Synapse ingest pipeline has not run:

```bash
make proof
```

**Filter narrows results to zero:**

`/notes ospf` filters the list to entries matching the query. Try `/notes` with no filter to see all indexed sources.

## `/local-notes` shows the demo vault

`/local-notes` always browses the local Obsidian vault — it does not require a live Synapse connection. When no `OBSIDIAN_VAULT_PATH` is set, it uses the bundled demo vault (`examples/obsidian-vault/`) containing example files like `OSPF.md` and `BGP.md`.

To point `/local-notes` at your own vault:

```bash
export OBSIDIAN_VAULT_PATH="/path/to/your/vault"
```

Or add it to `.env`:

```bash
echo 'OBSIDIAN_VAULT_PATH=/path/to/your/vault' >> .env
```

## `/!nn` shows "Answer not found"

The `/!nn` command replays a previous answer by number. The number refers to the position in the session's answer history (1-based).

**Common causes:**

- The number is out of range — `/!1` works after the first answer, `/!2` after the second, etc.
- The session was cleared with `/clear`, which resets the answer history.
- The answer was from an error response — error results are not stored in history.

Check the current history size:

Answers are numbered in the order they appear in the session. `/!1` replays the first answer, `/!2` the second, and so on. If you see "Answer not found", the number exceeds the history length.

## `.env` changes are not picked up

Cause: services or shell variables may still be using old values.

Check exported shell values:

```bash
env | grep '^SYNAPSE_'
```

Restart the lab after changing `.env`:

```bash
make lab-down
make lab-up
```

If a shell variable overrides `.env`, unset it first:

```bash
unset SYNAPSE_ASK_WEBHOOK_URL
unset SYNAPSE_WEBHOOK_AUTH_TOKEN
```

## Useful debug commands

```bash
make lab-status
make lab-logs
curl -i http://localhost:15515/healthz
curl -i http://localhost:15515/readyz
curl -s http://localhost:6333/collections
curl -s http://localhost:11434/api/tags
python3 "Ask/ask.py" --raw-json "What is in my indexed notes?"
```

## Related documentation

- [Ask README](README.md)
- [Project setup](../docs/SETUP.md)
- [Architecture](../docs/ARCHITECTURE.MD)