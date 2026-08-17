# Operator tooling

Production code lives in `src/synapse/`. This directory contains explicit operator, proof, maintenance, and media tools.

Use Make for the normal reviewer workflow:

```bash
make lab-up
make configure
make proof
```

## Interfaces

| Interface | Purpose |
|---|---|
| `python -m scripts.lab` | Local Compose lifecycle, configuration, status, cleanup, and proof dispatch |
| `python -m scripts.checks` | Repository hygiene, documentation links, and image-version checks |
| `python -m scripts.benchmark` | Optional curated Ollama model evaluation and reporting |
| `python -m scripts.capture` | Reproduce the tracked Ask TUI GIF |
| `python scripts/demo.py` | No-network reviewer preview |

`scripts/proof/` holds internal proof scenarios, scoring, redaction, and the CI mock. Call it through `scripts.lab` or the corresponding Make targets.

`scripts/ci/` contains CI-only shell adapters for verified tool installation and container-image scanning.

## Safety

- `.env` contains local configuration paths; managed credentials are created below the ignored `SYNAPSE_SECRET_DIR` with private permissions.
- `.local-artifacts/` contains generated evidence and benchmark output.
- `python -m scripts.lab remove` deletes containers, named volumes, `.env`, and local artifacts. It requires confirmation, or `--yes` in noninteractive use.
- Local proof demonstrates the configured lab workflow; it does not establish production readiness.
