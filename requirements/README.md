# Requirements

- `runtime.txt` — dependencies for the Synapse service image. Must stay minimal.
- `dev.txt` — includes `runtime.txt` plus test and development tooling.

## Policy

- Runtime dependencies must stay minimal. Every entry in `runtime.txt` should be required at service startup.
- All pins are exact (`==`). When adding a dependency, add a short reason in a comment.
- Do not change existing dependency versions without a specific reason.