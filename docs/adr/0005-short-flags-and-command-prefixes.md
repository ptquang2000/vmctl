# Repo-wide short option flags and unambiguous command-prefix resolution

## Status

accepted

## Context and decision

The CLI was long-form-only: every option was `--long`, every command spelled
in full. Adding the `sync`/`push` credential override (`-u`/`--user`,
`-p`/`--password`, see `docs/prd-sync-credential-override.md`) raised the
deferred question that PRD flagged as Out of Scope — give the *whole* CLI a
short form. This ADR is that decision.

Two independent mechanisms, chosen for opposite reasons:

**1. Short option flags are command-scoped mnemonics, not a global bijection.**
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

**2. Every command gets a short form for free via unambiguous-prefix
resolution** (`AliasedGroup`). Any prefix of a command name that matches exactly
one command resolves to it (`po stat` → `power state`, `sn ta` → `snapshot
take`, `per conn` → `peripheral connect`); a prefix matching more than one is a
**hard error** listing the candidates (`po sta` → ambiguous: start, state); no
match defers to Click's normal "no such command". Long names stay canonical for
help, docs, and completion.

## Considered options

- **Hand-curated alias table** (a fixed short name per command, a fixed letter
  per option globally) — what the PRD anticipated. Rejected: it must be kept
  collision-free by hand as commands are added, forces unnatural option letters
  to dodge cross-command clashes that don't actually exist (Click scopes short
  flags per command), and a static command alias is one more name to learn and
  keep stable.
- **Prefix resolution + per-command mnemonics (chosen)** — self-maintaining
  (new commands get a short form automatically; new options only need
  within-command uniqueness), convention-friendly, and collisions surface as
  loud errors rather than silent picks.
- **Third-party `click-aliases`** — extra dependency for less than the prefix
  resolver gives.

## Consequences

- **New commands need no alias bookkeeping**; their shortest unambiguous prefix
  just works. Adding a command whose name shares a prefix with an existing one
  only shortens the unambiguous prefix — it never silently reroutes an old
  short form (ambiguity errors instead).
- **New options need only within-command uniqueness** for their short letter,
  checked at import time by Click (a clash raises immediately).
- **Short flags are not portable across commands** by design; the help text per
  command is the source of truth. Documented in `CONTEXT.md`.
- **`-h` is intentionally not bound** to `--help` (Click's default), leaving it
  free; no option currently claims it.
- Prefix resolution lives in `AliasedGroup`; `VMGroup` extends it so the
  leading-`--` auto-select marker (ADR-0001) and prefixes compose. The root
  group uses `AliasedGroup` too, so top-level groups/commands abbreviate.
- **Reversible CLI ergonomics**, consistent with the project's prior CLI
  changes (ADR-0001/0004). No library or schema change.
