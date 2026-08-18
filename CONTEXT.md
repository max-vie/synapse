# Synapse Context

Synapse is a local notes automation lab. It turns Markdown notes into searchable,
source-grounded answers while keeping the source files, infrastructure, and
verification evidence on the operator's machine.

## Language

**Note**:
A Markdown source record supplied by the operator. A note remains the source of
truth even when Synapse formats, publishes, or indexes a copy.
_Avoid_: document, page, record

**Note identity**:
The stable identity used to recognize the same note across revisions, title
changes, and deletion.
_Avoid_: title slug, Wiki.js page identity

**Source-grounded answer**:
An answer whose claims are supported by retrieved note text and a usable source
locator. A citation without supporting text is not enough.
_Avoid_: cited answer, generated answer

**Quoted support**:
The short piece of retrieved note text shown with a source-grounded answer so a
reviewer can inspect the evidence behind the claim.
_Avoid_: citation text, excerpt

**Evaluation proof**:
Repeatable evidence that checks grounding, refusal, citation, and safety
behavior under named scenarios.
_Avoid_: benchmark, demo

**Live proof**:
Evidence produced against the configured local Ollama, Qdrant, and Wiki.js
stack. It demonstrates integration behavior and is separate from model-quality
claims.
_Avoid_: production proof, deployment proof
