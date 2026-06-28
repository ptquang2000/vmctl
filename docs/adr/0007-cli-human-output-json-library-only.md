# CLI emits human text; JSON is the library's contract

## Status

accepted

## Context and decision

vmctl started as "JSON-native API **and CLI**" — every CLI command did
`json.dumps(result_dict)` on stdout (`_out`/`_out_vm`/`_err`). In practice the
CLI is used by humans at a terminal, and JSON dumps are a poor terminal UX. We
split the contract by audience: **the library returns native dicts (the
JSON-native, programmatic interface); the CLI renders human-readable text.**
Raw JSON is **hard-removed** from the CLI — not demoted to a `--json` flag. A
caller who wants structured data imports the library (`VMCtl(...)`), which is
the integration path already used by the test suite.

This extends ADR-0006 from the command *surface* (the restructured verbs) to the
command *output* (per-command rendering): the verbs were already restructured,
now the output is tuned to match.

### Rendering rules (per-command tuning)

- **Collections** → aligned column tables. `ps`
  (`NAME STATUS`); `snapshot log` as a log
  (current-marker `*`, name, description); `network ls` plain table
  (`LABEL TYPE NETWORK CONNECTED`). Booleans render `yes`/`no`; an unknown/`null`
  value renders `-`. Empty collection → header row only, nothing to
  stderr.
- **Scalar value-reads** (`network ip`, `clipboard pull`) → the **bare value,
  nothing else** — no label, no `vm:` prefix — so they stay pipeable
  (`vmctl network ip | …`). An empty IP prints a blank line (correct for scripts).
- **Mutations** (`start`/`stop`/`kill`/`restart`/`pause`/`unpause`/`suspend`/
  `clone`/`snapshot commit`/`reset`/`rm`, network writes) → a terse
  **verb + canonical VM name** confirmation line (`started windows-10-x64`).
  Library mutation returns are contentless (`{"success": True}`), so the line is
  **synthesized in the CLI** from the verb + resolved name, not rendered from the
  return. Naming the VM also discloses which one auto-select chose.
- **`exec`** → `launched on <vm>` (vmcli `Guest run` cannot return guest stdout —
  ADR-0006 — so "launched" is the honest signal). **`cp`** →
  `copied <src> -> <vm>:<dest>`. **`push`** → progress on stderr,
  `pushed <src> -> <vm>:<dest>` on stdout. **`sync`** → progress on stderr,
  `synced <vm>` on stdout. **`auth set`** → `credentials set for <name>`.
- **`inspect`** → a **curated human summary** (power/identity header, then
  `snapshots`/`disks`/`network`/`tools` as the Q5 tables), **not** the full dump.
  The exhaustive structured data (10 live queries + full `.vmx`/`.vmsd`) stays
  available to programmatic callers via the library (`vm.inspect.inspect()` +
  `parse_vmx()`). A debug dump is exactly the use case that should drop into the
  library — this is the JSON-is-library-only principle working as intended.
- **Errors** → `error: <msg>` on stderr (lowercase, no JSON wrapper, single
  line), exit 1. stdout stays clean, so a failed value-read in a pipe yields
  empty stdout + a stderr message.

### Structure

Rendering lives in a new pure **`vmctl/render.py`** — `dict -> str` functions,
one per command shape, with **zero Click imports** — so output is unit-tested as
plain strings (the testable-without-Click pattern used throughout the codebase).
`cli.py` calls `render.*` then `click.echo`s the result. `_out`/`_out_vm`/`_err`
and all `json.dumps` calls are deleted from `cli.py`.

## Considered options

- **Global `--json` flag (default human)** — keeps a scripting escape hatch.
  Rejected: the library is the structured interface, so the flag is redundant
  insurance, and "one CLI, one output format" is simpler. Can be added later
  non-breakingly if a shell-only consumer ever needs it.
- **Generic dict-introspecting renderer** (lists→table, scalars→`key: value`) —
  uniform but generic-looking; ignores the per-command shaping ADR-0006
  committed to. Rejected for per-command tuning.
- **Keep `inspect` structured** (carve-out) — rejected; reopens the hard-remove
  decision. The library already serves the full dump.

## Consequences

- **Breaking CLI change.** Every command's stdout changes from JSON to text.
  CLI tests that assert JSON are rewritten to assert rendered strings (or moved
  to test `render.py` directly). README + CONTEXT.md self-description ("uniform
  `{"vm": …}` output") are rewritten.
- **The `vm` key is no longer in CLI output** as a field — it survives as the
  table header / the name in confirmation lines. Auto-select disclosure is
  preserved because mutations name the VM and value-reads only auto-select when
  exactly one VM runs (unambiguous).
- **Two verify-live gaps, both confirmed at implementation (2026-06-28):**
  `vmcli Snapshot query` exposes `currentUID` (drives the `snapshot log` `*`
  marker), and `vmcli Ethernet query` devices carry
  `label`/`connectionType`/`networkName`/`connectionStatus` (the `network ls`
  columns). `render.py` still reads these defensively (`.get`, alternate
  spellings) so the columns degrade rather than crash if a field is ever absent.
- **Library untouched** — modules already return native dicts; this is purely a
  CLI-layer change plus the new `render.py`.
