# Security Policy

## Scope

Synapse is a **local lab tool**, not a production SaaS. It runs on developer machines and disposable local VMs behind `localhost`. Security posture assumes no public-facing exposure.

## Supported versions

Only the latest commit on `main` is supported. There are no LTS branches or backport releases. Update pins with `make update-check` and review `docs/VERSION_POLICY.md` before refreshing your local stack.

## Reporting

Report security issues **privately** — do not file a public GitHub issue.

- Email: open a GitHub Security Advisory on this repository, or contact the maintainer directly.
- Include: component, affected version pin, and a minimal reproduction.
- Do **not** include: real API tokens, webhook secrets, `.env` contents, or internal service URLs.

## What not to put in public issues

- `SYNAPSE_WEBHOOK_AUTH_TOKEN`, `WIKIJS_API_TOKEN`, `WIKIJS_DB_PASSWORD`, or any secret from `.env`
- Internal hostnames, container network addresses, or Qdrant/Ollama/Wiki.js URLs that expose your lab topology
- Docker image digests or SBOMs that reveal your local image versions if you consider those sensitive

## Accepted findings

There is no standing `SECURITY_ACCEPTED_FINDINGS.md` file. Accepted findings are tracked in **commit messages** with CVE/advisory ID, affected component, scanner/date, reachability rationale, mitigation, and owner. See `docs/VERSION_POLICY.md` for the full policy.