# Synapse Ask

> Terminal client for querying the Synapse local RAG workflow with cited, source-aware answers.

![Synapse Ask TUI knowledge-system demo](../docs/assets/synapse-ask-knowledge-system.gif)

Synapse Ask is the operator-facing query tool for the Synapse lab. It opens as an interactive terminal UI by default, supports one-shot script output, and includes an explicit dry-run mode for no-network previews.

## Features

- Full-screen terminal UI for querying indexed notes
- Live webhook mode for the Synapse FastAPI Ask endpoint
- One-shot `text`, `json`, and `raw-json` output
- Explicit `--dry-run` mode for local metadata and chunk previews
- Source-aware answer display using local-safe locators
- Optional filters for source paths, note IDs, Wiki.js paths, and proof runs

## Requirements

Live mode expects the local Synapse stack to be running:

```bash
make lab-up
make configure
```

Ask auto-loads these values from the project `.env` file when present. Shell environment variables override `.env`.

```env
SYNAPSE_ASK_WEBHOOK_URL=http://localhost:15515/webhook/synapse/ask
SYNAPSE_WEBHOOK_AUTH_TOKEN_FILE=secrets/synapse_webhook_auth_token
```

## Usage

Open the interactive TUI:

```bash
python3 "Ask/ask.py"
```

Start with a prefilled question:

```bash
python3 "Ask/ask.py" "What is Synapse?"
```

Print only the answer:

```bash
python3 "Ask/ask.py" --text "What is Synapse?"
```

Return raw response JSON for scripts:

```bash
python3 "Ask/ask.py" --raw-json "What is Synapse?"
```

Run without Docker, tokens, or live services:

```bash
python3 "Ask/ask.py" --dry-run --raw-json "What tools make up my knowledge system, and what are they used for?" \
  --note "examples/obsidian-vault/Synapse-Demo/knowledge-system-notes.md"
```

## Live filters

Use filters when a question should target a specific note, page, or proof run.

```bash
python3 "Ask/ask.py" --raw-json "What tools make up my knowledge system, and what are they used for?" \
  --source-path "Synapse-Demo/knowledge-system-notes.md"
```

| Flag | Purpose |
|---|---|
| `--source-path` | Restrict retrieval to one indexed Markdown source path |
| `--note-id` | Restrict retrieval to one deterministic Synapse note ID |
| `--wiki-path` | Restrict retrieval to one Wiki.js path |
| `--exact-run-id` | Restrict retrieval to a specific proof or evidence run |

## TUI commands

| Command / key | Action |
|---|---|
| `/help` | Show help |
| `/notes` | List indexed notes from live Synapse |
| `/local-notes` | Browse local vault Markdown files |
| `/!1` | Show answer 1 again |
| `/clear` or `Ctrl-L` | Clear transcript |
| `/quit`, `/q`, `Ctrl-Q`, `Esc` | Exit |
| `PgUp` / `PgDn` | Scroll |
| `Enter` | Submit question |

`/notes` queries the Synapse service and requires a live webhook URL or `--dry-run`. Without either, it shows a clear message directing you to `/local-notes` or `--dry-run`. `/local-notes` always works offline by reading the local vault.

## Source safety

Ask hides URL-shaped source fields in normal terminal output and prefers stable local locators such as `source_path`, `wiki_path`, `note_id`, or `chunk_id`.

If a live answer has no usable citation or source evidence, Ask returns the standard insufficient-context response instead of acting like a generic chatbot.

## More documentation

- [Project setup](../docs/SETUP.md)
- [Architecture](../docs/ARCHITECTURE.MD)
- [Ask troubleshooting](TROUBLESHOOTING.md)

## Rebuild the GIF

The tracked TUI GIF is generated from the real terminal client against a
deterministic local Ask webhook harness. It does not require Docker, Ollama,
Wiki.js, Qdrant, or credentials.

Install the capture tools on Fedora:

```bash
sudo dnf install -y xorg-x11-server-Xvfb kitty xdotool gifsicle ImageMagick
```

Regenerate and inspect the artifact:

```bash
python3 scripts/capture/capture_ask_gif.py
file docs/assets/synapse-ask-knowledge-system.gif
```

The harness defaults to the portable `mpeg4` ffmpeg encoder for its ignored
intermediate MP4. Set `SYNAPSE_CAPTURE_ENCODER=libx264` on a system that has
that encoder available.
