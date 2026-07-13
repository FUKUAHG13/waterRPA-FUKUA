# ADR 0023: Stable workflow references

## Status

Accepted for v1.0.11.

## Decision

Each task owns a stable `step_id`. Branches store both a user-facing numeric step
and an internal target ID. Reordering recomputes only the displayed number. Copying
creates a new ID, rebases self-references to the clone, and preserves external
references. Deleting a referenced task requires confirmation and turns surviving
references into normal fall-through branches.

The two `until_*` references apply only to command 15. Their defaults may exist on
other task dictionaries for UI compatibility, but they must never create hidden
edges in the workflow graph.

## Consequences

Drag, insert, copy, paste, delete, migration, validation, runtime snapshots and full
exports all pass through `workflow_document.py`. Numeric fields remain in the file
so a non-programmer can inspect them, but they are no longer authoritative identity.
