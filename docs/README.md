# Synapse Documentation

Read the documents in this order:

1. [Setup](SETUP.md) for the safe local workflow and verification commands.
2. [Architecture](ARCHITECTURE.MD) for the note, retrieval, publishing, and proof flows.
3. [Context glossary](CONTEXT.md) for the project vocabulary.
4. [Version policy](VERSION_POLICY.md) for reviewed runtime and image versions.
5. [Ask client](../Ask/README.md) for terminal usage.

## Verification levels

`make demo` proves deterministic local behavior without credentials, Docker, or
network access.

`make evaluate` proves the source-grounded contract with in-memory adapters and
reports separate metrics for grounding, refusal, citation, and prompt-injection
behavior.

`make mocked-fastapi-qdrant-e2e` proves service and vector-store plumbing with a
synthetic Ollama adapter. It does not prove model quality.

`make proof` and `make real-local-stack-proof` exercise the configured local
stack. Review the generated evidence before sharing it.
