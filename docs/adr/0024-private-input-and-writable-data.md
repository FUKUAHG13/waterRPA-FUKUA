# ADR 0024: Private input and writable runtime data

## Status

Accepted for v1.0.11.

## Decision

Text actions use Windows Unicode input events and do not replace the clipboard.
Logs report only character counts. Secret text resolves a credential name through a
DPAPI store scoped to the current Windows user; workflow files and full packages
never contain the secret value.

Frozen builds keep portable data beside the executable when the directory is
writable. Otherwise they use `%LOCALAPPDATA%\\fukuaRPA`. A `portable.flag` explicitly
forbids this fallback and produces a clear error when the directory is read-only.
Bundled resources continue to resolve independently from the writable data path.

Full package export is transactional and refuses to produce a package when any
referenced image is missing.

## Consequences

Credentials must be recreated on a different machine or Windows account. Unicode
input may still be rejected by elevated or unusual targets, but failure is preferable
to silently exposing secrets or destroying non-text clipboard contents.
