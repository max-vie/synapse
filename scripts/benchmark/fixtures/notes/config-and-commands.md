# Config and Commands

Messy notes from operator console. Exact values must survive.

```yaml
services:
  qdrant:
    collection: synapse_benchmark_notes
    api_key: "[REDACTED]"
  synapse-api:
    webhook_path: "/webhook/synapse-benchmark"
```

```toml
[benchmark]
fixture_set = "sanitized-adversarial-v1"
max_parallel_models = 1
allow_public_ingress = false
```

exact command:
```bash
python3 scripts/benchmark/ollama_models.py smoke --models tinyllama:latest,gemma2:2b --skip-pull
```

Pasted terminal log:
$ ollama list
NAME                       ID              SIZE
gemma2:2b                  8ccf136fdd52    1.6 GB
tinyllama:latest           2644915ede35    637 MB

Do not turn [REDACTED] into a key. Do not turn [TOKEN] into a bearer token.
