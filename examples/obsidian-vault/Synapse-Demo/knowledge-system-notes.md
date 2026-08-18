# My Knowledge System

## Question

What tools make up my knowledge system, and what are they used for?

## Direct answer

My knowledge system is a local Markdown-to-RAG workflow. Markdown notes are the
source of truth. The Synapse FastAPI service coordinates note intake and
questions. Ollama provides local formatting, embedding, and answer generation.
Qdrant stores searchable vector chunks. Wiki.js stores a readable published
copy. The Ask CLI/TUI is the terminal interface for questions. Docker Compose
runs the local services, while the demo, evaluation, and proof scripts verify
that the workflow behaves as expected.

## Tools and responsibilities

### Markdown vault and Obsidian-style notes

The Markdown vault is where the source notes live. Markdown is portable, easy to
diff, and independent of the publishing or search tools. Synapse receives a
note path and note content from an automation caller; it is not a filesystem
watcher and does not own the note editor.

The source note remains authoritative when Synapse creates a formatted copy or
searchable chunks. A note receives a deterministic note identity from its source
and normalized vault path, so a title edit does not create a new identity.

### Synapse FastAPI service

The Synapse API is the coordinator and policy owner. It exposes authenticated
note and Ask webhooks as well as direct endpoints used by tests and local
clients.

For note intake, the service validates the request, applies content limits,
builds deterministic metadata, optionally asks Ollama to format the Markdown,
indexes the source text in Qdrant, and publishes the readable copy to Wiki.js.
It verifies the new Qdrant points before stale points are removed. If publishing
fails after indexing, the new Qdrant points are rolled back.

For questions, the service embeds the question, retrieves candidate chunks,
filters them by note scope and metadata, checks query-term grounding, builds a
small context, asks Ollama for an answer, and validates citations against
quoted support. If the retrieved note text is not sufficient, the service
returns the standard insufficient-context response instead of inventing an
answer.

### Ollama

Ollama is the local model runtime. Synapse uses it for three separate jobs:

- Formatting: turn incoming Markdown into a compact readable copy without adding facts.
- Embedding: turn note chunks and questions into vectors for similarity search.
- Answer generation: produce a concise answer from the retrieved note context.

The default lightweight setup uses `nomic-embed-text` for embeddings and
`tinyllama:latest` for formatting and answers. These defaults are for a local
reviewer setup, not a claim that they are the best available models.

### Qdrant

Qdrant is the vector store. Synapse stores one or more chunks for each note,
along with the note identity, content hash, revision, source path, Wiki.js path,
chunk index, and chunk text.

Qdrant performs the initial similarity search. A similarity score alone is not
enough to support an answer, so Synapse applies score, filter, marker, lexical
grounding, duplicate, and top-k policy before sending context to Ollama.

### Wiki.js

Wiki.js is the human-readable publishing target. It stores the formatted note,
the original source note, and Synapse frontmatter such as the note identity,
content hash, revision, source path, and ingest job ID.

Wiki.js is not the source of truth and is not the vector search store. It gives a
reviewer a readable page that can be compared with the original Markdown and
the Qdrant index.

### Ask CLI/TUI

Ask is the operator-facing terminal client. It can open a full-screen TUI, send a
one-shot question, return JSON, or run a dry-run preview without Docker or
network access.

In live mode, Ask sends questions to the authenticated Synapse Ask webhook. It
renders the answer with source-safe locators such as the relative source path,
Wiki.js path, note identity, and chunk identity. It refuses to display a live
answer that lacks usable source evidence or a valid trailing citation.

### Docker Compose

Docker Compose runs the local infrastructure stack: Synapse, Qdrant, Ollama,
Wiki.js, and the Wiki.js PostgreSQL database. Services bind to localhost by
default. Named volumes preserve Qdrant data, Ollama model data, and Wiki.js
database data when containers are stopped.

### Verification tooling

The repository has separate verification paths for separate claims:

- `make demo` checks deterministic metadata and Ask dry-run behavior without external services.
- `make evaluate` checks grounding, refusal, citation, prompt-injection, latency, and context-size behavior with in-memory adapters.
- `make mocked-fastapi-qdrant-e2e` checks service and Qdrant plumbing with a synthetic Ollama endpoint.
- `make proof` checks the configured local workflow with Wiki.js, Qdrant, and Ollama.
- `make real-local-stack-proof` runs the stronger real-model local-stack scenarios.

The deterministic evaluation does not prove model quality. The live proof does
not claim production readiness. They prove different parts of the system.

## End-to-end flow

1. A Markdown note is supplied with a normalized vault-relative path.
2. Synapse assigns a stable note identity and content hash.
3. Ollama optionally formats a readable copy while the original source remains available.
4. Synapse chunks and embeds the source note through Ollama.
5. Qdrant stores the vectors and source metadata.
6. Synapse publishes the formatted copy and original source to the stable Wiki.js path.
7. Ask sends a question to the Synapse Ask webhook.
8. Ollama embeds the question and Qdrant returns candidate chunks.
9. Synapse grounds the candidates, builds quoted support, and asks Ollama for one concise answer.
10. The answer gate requires a usable locator, a trailing citation, and overlap with quoted support by default.

## What the system does not claim

This knowledge system is a private local lab. It does not claim public hosting,
multi-user authorization, enterprise security, cloud-scale retrieval, or
production deployment. A source-grounded answer is only as strong as the note
text and retrieval evidence supplied to it.
