# PRD — Name aliases (config remapping)

*Generated from conversation context on 2026-06-25*

## Problem Statement

A VM can only be referred to by the auto-discovered registry name — the `.vmx`
file's stem (lowercased). That handle is whatever VMware named the folder/file,
which is often long or unmemorable (`windows-10-x64`, `vmctl`), and is
strictly limited to VMs found under the configured `scan_roots`. There is no way
to:

- give a VM a short, stable nickname (`dev`, `build`) to type instead of its full stem;
- refer to a VM that lives **outside** the scan roots without adding its whole
  directory tree to discovery;
- pin a stable handle when the substring matcher would otherwise be ambiguous.

The existing `find()` substring matching helps a little but is fuzzy and can
collide; users want an explicit, user-controlled name.

## Solution

Add a **remapped name** (an *alias*) layer in `~/.vmctl/config.json`. Under a new
`"aliases"` block, the user maps a chosen handle to either a discovered VM's
name **or** a direct `.vmx` path:

```jsonc
{
  "scan_roots": ["C:/Users/.../Virtual Machines"],
  "aliases": {
    "dev": "windows-10-x64",       // -> a discovered VM (registry name)
    "db":  "D:/VMs/db/db.vmx"       // -> a .vmx path (may be OUT of scope)
  }
}
```

Any command that accepts a VM name accepts an alias in its place
(`vmctl power state dev`). Aliases are **input-only**: they are a shortcut for
addressing a VM, and do not rename it. The output `vm` key and credential lookup
continue to use the VM's real registry name. Aliases are edited by hand in the
config file (like `scan_roots`); there is no new CLI verb.

## User Stories

1. As a vmctl user, I want to type a short alias instead of a long `.vmx` stem,
   so that everyday commands are quicker to type.
2. As a vmctl user, I want an alias to point at a `.vmx` file outside my scan
   roots, so that I can drive a VM without adding its directory to discovery.
3. As a vmctl user, I want an explicit alias to win over the fuzzy substring
   matcher, so that a stable handle never resolves ambiguously.
4. As a vmctl user, I want command output and stored credentials to keep using
   the VM's real name regardless of which alias I typed, so that one VM has one
   identity no matter how I address it.
5. As a vmctl user, I want a clear error when an alias is broken (missing `.vmx`
   or unresolvable name), so that I can fix the config quickly instead of seeing
   a misleading "not found".

## Implementation Decisions

**Modules touched** (all small, no new module):

- **`config.py`** — add `"aliases": {}` to `_DEFAULTS` so a missing block loads
  as empty.
- **`VMRegistry` (`registry.py`)** — the deep module that owns all name
  resolution. Constructor gains an `aliases` mapping (keys lowercased for
  case-insensitive match). `find()` gains a single new first branch; everything
  downstream is unchanged.
- **`VMCtl` (`__init__.py`)** — pass `self._config.get("aliases", {})` into
  `VMRegistry`. No other change: `get()` already derives canonical identity via
  `name_for_path(vmx_path) or name`, and credentials are already keyed by the
  canonical name.

**Resolution contract** (precedence, inside `find()`):

```
find(name):
  1. exact alias match (case-insensitive)  -> resolve the alias value (see below)
  2. exact stem match                      -> path
  3. unique substring match                -> path
  4. error
```

An alias therefore **always beats** a substring match and a same-named stem —
explicit config beats fuzzy discovery.

**Alias value sniffing** (one hop, never recursive — a value is a path or a
stem, never another alias):

- *Path-shaped* = ends in `.vmx` **or** contains a path separator.
- Path-shaped **and the file exists** ⇒ return that path directly.
- Path-shaped **but missing** ⇒ raise `alias '<a>' points to missing .vmx: <path>`.
- Otherwise (name-shaped) ⇒ resolve as a registry name via the normal stem
  lookup; if that fails, raise `alias '<a>' -> '<value>': VM not found`.

**Canonical identity (input-only aliases).** `name_for_path()` is untouched.
Resolving via an alias does not change the `vm` output key or credential key:

- Alias → in-registry VM: `name_for_path(path)` returns the real name; the alias
  is erased from the identity. `vmctl power state dev` → `{"vm": "windows-10-x64", …}`.
- Alias → `.vmx` **outside** scan roots: `name_for_path(path)` returns `None`, so
  `get()`'s existing `or name` clause makes the alias canonical (credentials then
  keyed by the alias). This is intrinsic fallthrough, **not** special-cased.

**Error type.** Alias errors raise `ValueError` from `find()`, consistent with
its existing resolution errors; the CLI already catches `(VMCtlError, ValueError)`
uniformly, so they surface identically to every other resolution error.

**Auto-select is unaffected.** The optional-VM-name auto-select path reverse-maps
a running `.vmx` via `name_for_path()` and only ever knows real names — it never
emits an alias.

## Testing Decisions

Follow the existing `tests/test_*.py` unit-test style (pure, no live VM; the
registry is constructed from in-memory `scan_roots`/`aliases`, no mocking of
VMware needed for resolution). Prior art: existing registry/`find()` tests and
`test_cli.py`'s resolution cases.

Tests for `VMRegistry.find()` (the module under test):

1. Alias → existing stem resolves to that VM's path.
2. Alias → in-scope `.vmx` path resolves to the path.
3. Alias → out-of-scope `.vmx` path resolves; via `VMCtl.get()` the **alias
   becomes canonical** (`name_for_path` is `None`) — assert the `vm` identity and
   credential key.
4. Alias → in-registry VM keeps the **real name canonical** (alias does not leak
   into `vm`/credentials).
5. Alias beats a unique substring that would otherwise match a different VM.
6. Alias beats a same-named exact stem (alias-first precedence).
7. Case-insensitive alias key match.
8. Path-shaped-but-missing value → `points to missing .vmx` error.
9. Name-shaped-but-unresolvable value → `alias '<a>' -> '<value>': VM not found`.
10. No alias→alias recursion (a value equal to another alias key is treated as a
    stem/path, not followed).

Confirm with the user which of these to land; suggested minimum = 1, 2, 3, 5, 6,
8, 9.

## Out of Scope

- **No `vmctl alias` CLI verbs** (`set`/`rm`/`list`). Aliases are edited by hand
  in the config file, like `scan_roots`.
- **No alias surfacing in `vm list` output** (could be a cheap follow-up; not in
  this pass).
- **No alias→alias chaining / recursion.**
- **No renaming** of the underlying VM — aliases are an addressing shortcut only.
- Adding an out-of-scope alias path to the discovered registry (`list_all`) is
  not done.

## Further Notes

- An ADR was considered but deferred. The genuine trade-off worth recording is
  "aliases are input-only / the real name stays canonical" (vs a sticky alias
  that follows the VM through output and credentials). It is fully documented in
  `CONTEXT.md` → **"Name aliases (config remapping)"** and is not hard to reverse,
  so it did not meet the ADR bar. Offer again if the input-only choice proves
  contentious.
- Domain language for this feature is recorded in `CONTEXT.md` (the **Alias**
  term, resolution order, and broken-alias error wording).
