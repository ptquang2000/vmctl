# Optional VM name selected by a leading `--` marker

## Status

accepted

## Context and decision

Nearly every `vmctl` command takes the VM **name** as its first positional
argument. We wanted to let users omit it when exactly one VM is running, but
Click cannot make a *leading* positional optional when other required positionals
follow it (`snapshot take init` is ambiguous: is `init` the VM name or the snap
name?).

We decided: **omit the name; add a leading `--` only when other positionals
follow.** Bare commands work for name-only commands (`power state`); the marker
disambiguates multi-positional ones (`snapshot take -- s1`,
`guest run -- cmd.exe /c echo hi`). Auto-select resolves to the single **running
in-scope VM** (`vmrun list` intersected with the registry). Every result carries
a `vm` key (typed or auto) for a uniform output shape. Scope is all VM-operating
commands except `vm list` and `auth set`.

## Considered options

- **`--vm`/`-m` option** instead of a positional — uniform and cleanly optional,
  but a breaking change to *every* current positional invocation.
- **Silent count-based fill** (infer the omitted name from how many positionals
  were supplied) — backward-compatible, but introduces a wrong-VM footgun: a
  forgotten argument (`snapshot take myvm`) gets silently reinterpreted as another
  positional and acts on the running VM. Rejected for this reason.
- **Leading `--` marker (chosen)** — fully explicit, no footgun, keeps the
  existing positional grammar backward-compatible.

## Consequences

- `--` is repurposed from Click's "end of options" terminator into a custom
  "no VM name here" marker. Because Click natively consumes `--` and shifts
  nothing, the CLI must intercept and strip a *leading* `--` itself before Click
  parses. Only the leading `--` is special, so flags after it still parse
  (`snapshot take -- s1 --memory`). A `--` anywhere but first keeps its
  conventional meaning. This is the surprising part a future reader needs.
- Adding the `vm` key to every result changes the output shape of all commands;
  existing exact-match unit tests must be updated.
- This is a CLI grammar users will script against — hence the ADR.
