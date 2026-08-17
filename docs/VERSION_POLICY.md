# Version Policy

Synapse pins container images so the local lab stays reproducible. Pins are not meant to be forgotten: they are reviewed on a monthly maintenance pass and before public portfolio refreshes.

## Current reviewed pins

These pins were reviewed against upstream release metadata on 2026-08-17:

- Qdrant: `qdrant/qdrant:v1.19.0@sha256:057ee3a8da769fe7310dd3537b4dc7583bf87a95ce8ac43c0af5a46bc580d1fc`
- Ollama: `ollama/ollama:0.32.14@sha256:9d30908e41144b1f1da89b9d8e33c07e4aeb43ff41a8660241b1686e2cc330ad`
- Synapse service runtime: digest-pinned `python:3.13-slim`
- Wiki.js: `ghcr.io/requarks/wiki:2.5.314@sha256:68f0d1848261ae76492ba358e30a96a76fed5d97a3fff381656082bf90f70d7e`
- Wiki.js Postgres: `postgres:16-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685`


`postgres:16-alpine` tracks the Postgres 16 Alpine maintenance stream. Do not move it to a new major version without a Wiki.js database backup/restore test.

## Monthly update check

Automated maintenance runs on a monthly CI schedule (`0 9 1 * *`) that reruns the normal checks plus dependency security scanning so stale pins do not rely only on a person remembering. The CI job uses `scripts/ci/scan-images.sh` with Trivy, generates CycloneDX SBOMs, and uploads them as artifacts.

Run locally when reviewing dependency updates:

```bash
make update-check
```

The check compares the tag portion of reviewed Compose image defaults with upstream GitHub releases for Qdrant, Ollama, and Wiki.js 2.x, and requires a valid sha256 digest for those external images. The Python service runtime and Postgres pins are policy-only checks because they track maintenance streams rather than project GitHub releases.

If a pin is stale:

1. Update `docker-compose.e2e.yml` and `.env.example` together.
2. Run `docker buildx imagetools inspect` for each new image tag and record its verified digest before starting the lab.
3. Run `make lab-up` only in a disposable local lab or after accepting the service upgrade risk.
4. Run the live proof with `make proof` after the stack starts.
5. Update this document with the reviewed date and image list.

## Security scanning

CI runs `scripts/ci/scan-images.sh` with Trivy against the reviewed digest-pinned images. The script pulls external images, builds the local Synapse image, saves each image for archive scanning, and generates CycloneDX SBOM files for every image instead of skipping local-only references. The default CI run is intentionally report-only: official Wiki.js and other vendor images can retain upstream findings that cannot be fixed from this repository without replacing the image. A local strict review can still set `TRIVY_EXIT_CODE=1`.

Known accepted findings should be documented in commit messages with CVE/advisory ID, affected component, scanner/date, reachability rationale, mitigation, and owner. The policy tracks accepted findings in Git history, not in a standing file that could become stale.

For local review, run the same scan script after Docker is available:

```bash
scripts/ci/scan-images.sh .local-artifacts/sbom
TRIVY_EXIT_CODE=1 scripts/ci/scan-images.sh .local-artifacts/sbom-strict
```

A scanner finding does not automatically mean the lab is broken. Treat HIGH/CRITICAL findings as maintenance work: read the advisory, check whether it affects the exposed local-only usage here, and either upgrade the pin or document why the finding is not reachable in this lab.

### Wiki.js residual findings

The reviewed official Wiki.js image (`ghcr.io/requarks/wiki:2.5.314@sha256:68f0d1848261ae76492ba358e30a96a76fed5d97a3fff381656082bf90f70d7e`) returned **126 HIGH/CRITICAL findings (115 HIGH, 11 CRITICAL)** in the 2026-08-17 Trivy 0.66.0 scan. The findings are in the image's Alpine and legacy Node.js dependency graph; they are upstream/vendor risk, not vulnerabilities introduced by Synapse application code.

This repository deliberately does not rebuild Wiki.js or run forced major-version dependency upgrades inside the vendor image. The lab reduces exposure through loopback-only ports, webhook authentication, read-only secret mounts, health-gated startup, and its documented local-only scope. The image findings remain report-only in CI and must be reassessed when a maintained Wiki.js release or compatible upstream patch is available.

## Major-version rule

Patch and minor updates can be reviewed during the monthly update pass. Major version jumps need their own proof because this repo depends on Wiki.js GraphQL behavior, Qdrant vector collection compatibility, FastAPI request handling, and Ollama API behavior.

Do not promote a new major image line by only updating the tag. Prove it with the local lab first.
