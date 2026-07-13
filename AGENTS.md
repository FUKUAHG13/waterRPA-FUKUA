# Repository guidance

This file gives human and automated contributors a compact map of the repository. It describes the current mainline implementation, not a restriction on what a fork or future variant may explore.

## Read first

- `README.md` explains the product and public entry points.
- `ARCHITECTURE.md` records module boundaries, runtime invariants, and release checks.
- `CONTEXT.md` defines the domain vocabulary used by code and tests.
- `ROADMAP.md` lists possible future directions; roadmap entries are not release commitments.

## Change discipline

- Prefer the existing module boundaries under `fukua_rpa/`; do not move business logic back into the entry point or UI widgets.
- Keep edits scoped to the requested behavior. Preserve unrelated local changes and user data.
- Never commit `config.ini`, credentials, imported user images, logs, crash reports, build output, or other machine-local state.
- Preserve privacy boundaries: ordinary and secret text must not enter logs, diagnostics, traces, or exported profiles.
- Keep optional native acceleration behind capability checks and a working Python/OpenCV fallback unless a separately documented variant intentionally chooses another contract.
- Product variants such as lightweight, legacy, or experimental builds are welcome as explicit proposals. Isolate their dependency and packaging differences instead of silently changing the behavior of the current mainline edition.

## Verification

- During development, run focused tests for the changed behavior and nearby contracts.
- Before publishing a binary release, run the complete release verification, including unit tests, Ruff, native rebuild, performance gates, soak tests, frozen startup checks, runtime-closure audit, and archive verification.
- Add or update tests when changing configuration defaults, persistence, migration, execution parameters, workflow behavior, packaging, or security boundaries.

## Packaging

- The current onedir and onefile packages share the same `fukua_rpa` business source and differ only in PyInstaller packaging.
- `python scripts/build_release.py` builds the current default onedir package.
- `python scripts/build_release.py --format onefile` builds the onefile package.
- `python scripts/build_release.py --format all` builds both formats.
- Both existing formats must use `scripts/runtime_pruning.py` and retain the verified Qt platform, JPEG, software OpenGL, native-core, and UI Automation runtime payloads they require.
- A new package variant should document its feature boundary, dependency boundary, target systems, and test matrix rather than copying the main application into an untracked second codebase.

## Compatibility and safety

- Profile migrations must preserve the original file or backup before conversion. Unsupported profiles must not be partially loaded and then overwritten.
- Background actions must not silently fall back to moving or clicking the real mouse when their result is unknown.
- External threads, hooks, and native jobs must have bounded work and repeatable shutdown behavior.
- Startup must remain offline. User-triggered links may open the system browser, but the application must not add hidden telemetry or automatic network checks.
