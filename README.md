# Synapse

> Self-hosted AI notes automation lab that turns Markdown notes into a private searchable knowledge base.

[![CI](https://github.com/max-vie/synapse/actions/workflows/ci.yml/badge.svg)](https://github.com/max-vie/synapse/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=fff)](docs/SETUP.md#live-local-lab-flow)
[![Ollama](https://img.shields.io/badge/Ollama-fff?logo=ollama&logoColor=000)](docs/SETUP.md#environment-files)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](docs/ARCHITECTURE.MD#service-roles)
[![Qdrant](https://img.shields.io/badge/Qdrant-DC244C?logo=qdrant&logoColor=white)](docs/ARCHITECTURE.MD#service-roles)

![Synapse Ask TUI answering an OSPF question from indexed notes](docs/assets/synapse-ask-real-tui-ospf.gif)

## Project overview

Synapse is a small local infrastructure lab for testing an AI-assisted notes workflow. It focuses on three things:

- running the stack locally with Docker Compose;
- connecting Markdown notes to a RAG workflow;
- proving the result with scripts, logs, and evidence.

## Quick lab flow

The local lab is a three-step flow because Wiki.js requires manual first-run admin setup and API-token creation:

```bash
make lab-up
make configure
make proof
```

`make lab-up` starts the FastAPI Synapse service, Qdrant, Ollama, and Wiki.js. It does not mean the proof-ready lab is fully configured. After it starts, open Wiki.js, enable the Wiki.js API in the Administration Area, create a page-capable API token, save it in private `.env`, then run `make configure` to check the token and live API before `make proof`.

The reviewer demo is separate and only runs when explicitly called:

```bash
make demo
```

More detail: [Setup guide](docs/SETUP.md). For the short command list, run:

```bash
make help
```

## Workflow

```mermaid
flowchart LR
    note[Markdown note] --> api[Synapse API :15515]
    api -->|format| ollama[Ollama :11434]
    ollama -->|formatted note| api
    api -->|GraphQL| wiki[Wiki.js :3000]
    api -->|upsert vectors| qdrant[Qdrant :6333]
    ask[Ask / RAG] --> api
    api -->|embed question| ollama
    api -->|query vector| qdrant
    qdrant -->|matching chunks| api
    api -->|answer prompt| ollama
    ollama -->|embedding + generated answer| api
    api -->|source quotes| answer[Answer]
```

## Docs

- [Setup](docs/SETUP.md)
- [Architecture](docs/ARCHITECTURE.MD)
- [Version policy](docs/VERSION_POLICY.md)
- [Ask](Ask/README.md)
