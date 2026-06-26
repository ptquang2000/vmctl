# Repo-wide short option flags

## Status

accepted

## Context and decision

The CLI was long-form-only: every option was `--long`. Adding the `sync`/`push`
credential override (`-u`/`-p`, see `docs/prd-sync-credential-override.md`)
raised the deferred question that PRD flagged as Out of Scope — give the *whole*
CLI a short form. This ADR is that decision.

**Short option flags are command-scoped mnemonics, not a global bijection.**
Click resolves short flags per command, so the only hard constraint is
within-command uniqueness. We exploit that instead of fighting it: each option
gets the clearest in-command mnemonic, preferring established Unix conventions
(`fs mkdir -p` = `--parents`, `fs rmdir -r` = `--recursive`). The same letter
therefore means different things across commands (`-d` is `--description` on
`snapshot take`, `--dir` on `fs mktemp`, `--project-dir` on `sync`; `-p` is
`--password` on `auth`/`sync`/`push` but `--parents` on `fs mkdir` and
`--prefix` on `fs mktemp`). This is deliberate — a global letter→concept map
would force unnatural choices (no `mkdir -p`) to avoid clashes that Click's
per-command scoping makes irrelevant. The one soft convention we keep: where a
command takes credentials, `-u`/`-p` are user/password.

## Considered options

- **Hand-curated alias table** (a fixed letter per option globally) — what the
  PRD anticipated. Rejected: it forces unnatural option letters to dodge
  cross-command clashes that don't actually exist (Click scopes short flags per
  command).
- **Per-command mnemonics (chosen)** — new options only need within-command
  uniqueness, it is convention-friendly, and clashes surface at import time.

## Consequences

- **New options need only within-command uniqueness** for their short letter,
  checked at import time by Click (a clash raises immediately).
- **Short flags are not portable across commands** by design; the help text per
  command is the source of truth. Documented in `CONTEXT.md`.
- **`-h` is intentionally not bound** to `--help` (Click's default), leaving it
  free; no option currently claims it.
- **Reversible CLI ergonomics**, consistent with the project's prior CLI
  changes (ADR-0001/0004). No library or schema change.
