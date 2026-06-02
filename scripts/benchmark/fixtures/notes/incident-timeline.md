# Incident Timeline - sanitized

## timeline
2026-05-26T10:15:00Z - alert BENCH-INC-042 opened for duplicate Mermaid block.
10:18 UTC - false lead blamed ORCH1D-17A; correction says the real codename is ORCHID-17A.
2026-05-26 10:22 - root cause: formatter moved a fenced code block outside the operations section.
2026-05-26T10:29:30Z - mitigation: pin extraction prompt to source paths.

## later correction
Newest verified incident outcome: no data loss, no secret exposure, and no production impact.
The note explicitly says [REDACTED] stayed redacted and [TOKEN] was never expanded.

```
# This heading-looking line must remain inside the fence
not_a_heading=true
incident_id="BENCH-INC-042"
```
