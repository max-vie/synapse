# Version Policy

Synapse pins container images so the local lab stays reproducible. Pins are not meant to be forgotten: they are reviewed on a monthly maintenance pass and before public portfolio refreshes.

## Current reviewed pins

These pins were reviewed against upstream release metadata on 2026-06-01:

- Qdrant: `qdrant/qdrant:v1.18.1`
- Ollama: `ollama/ollama:0.24.0`
- Synapse service runtime: `python:3.13-slim`
- Wiki.js: `ghcr.io/requarks/wiki:2.5.314`
- Wiki.js Postgres: `postgres:16-alpine`


`postgres:16-alpine` tracks the Postgres 16 Alpine maintenance stream. Do not move it to a new major version without a Wiki.js database backup/restore test.

## Monthly update check

Automated maintenance runs on a monthly CI schedule (`0 9 1 * *`) that reruns the normal checks plus dependency security scanning so stale pins do not rely only on a person remembering. The CI job uses `scripts/ci/scan-images.sh` with Trivy, generates CycloneDX SBOMs, and uploads them as artifacts.

Run locally when reviewing dependency updates:

```bash
make update-check
```

The check compares reviewed Compose image defaults with upstream GitHub releases for Qdrant, Ollama, and Wiki.js 2.x. The Python service runtime and Postgres pins are policy-only checks because they track maintenance streams rather than project GitHub releases. It exits nonzero when an automatically checked pin is behind its tracked release line.

If a pin is stale:

1. Update `docker-compose.e2e.yml` and `.env.example` together.
2. Run `docker manifest inspect` for each new image tag before starting the lab.
3. Run `make lab-up` only in a disposable local lab or after accepting the service upgrade risk.
4. Run the live proof with `make proof` after the stack starts.
5. Update this document with the reviewed date and image list.

## Security scanning

CI runs `scripts/ci/scan-images.sh` with Trivy against the reviewed image pins. The job generates CycloneDX SBOM files for each pinned image and uploads them as the `synapse-image-sboms` artifact. The default CI run is report-only for image vulnerabilities because the lab depends on third-party images that can report transient upstream findings before a patched image exists. For a strict local review, set `TRIVY_EXIT_CODE=1` when running the scan script.

Known accepted findings should be documented in commit messages with CVE/advisory ID, affected component, scanner/date, reachability rationale, mitigation, and owner. The policy tracks accepted findings in Git history, not in a standing file that could become stale.

For local review, run the same scan script after Docker is available:

```bash
scripts/ci/scan-images.sh .local-artifacts/sbom
TRIVY_EXIT_CODE=1 scripts/ci/scan-images.sh .local-artifacts/sbom-strict
```

A scanner finding does not automatically mean the lab is broken. Treat HIGH/CRITICAL findings as maintenance work: read the advisory, check whether it affects the exposed local-only usage here, and either upgrade the pin or document why the finding is not reachable in this lab.

## Major-version rule

Patch and minor updates can be reviewed during the monthly update pass. Major version jumps need their own proof because this repo depends on Wiki.js GraphQL behavior, Qdrant vector collection compatibility, FastAPI request handling, and Ollama API behavior.

Do not promote a new major image line by only updating the tag. Prove it with the local lab first.
