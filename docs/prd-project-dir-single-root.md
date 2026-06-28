# PRD — Collapse `base_dir` into `--project-dir` as the single source-resolution root

*Generated from conversation context on 2026-06-28*

## Problem Statement

When configuring file sync, developers face **two** directory inputs that look
interchangeable but aren't:

- `--project-dir` — a per-invocation path used only to pick the sync profile (it reads
  the dir's git remote and matches it against `~/.sss/config.json`). Defaults to cwd.
- `base_dir` — a global key in `~/.sss/config.json` that a profile's relative
  `source_dirs` / `source_files` / `optional_dirs` keys resolve against. Defaults to
  `%USERPROFILE%`. Not exposed as a CLI flag.

They deliberately anchor at *different* directories: `base_dir` is the **parent** of the
repo, so every profile source key carries a repo-name prefix (`barapp/bin/{build_cfg}`),
while `--project-dir` points at the repo itself. Developers conflate the two, and the
extra config-only `base_dir` knob is ceremony: in practice all source paths live **inside
the project repo**, so the two inputs always point at the same place anyway.

## Solution

Make **`--project-dir` the single directory input.** It does double duty — git-remote
profile selection *and* the root that a profile's relative source paths resolve against.
`base_dir` is removed entirely. Source paths in a profile become repo-relative, and the
common case needs no path tuning in config at all: run sync from inside the repo (or pass
`--project-dir <repo>`) and everything resolves from there.

## User Stories

1. As a developer, I want one directory flag (`--project-dir`) that both selects my sync
   profile and roots my source paths, so that I don't have to reason about two
   separately-anchored directory concepts.
2. As a developer, I want a profile's `source_dirs`/`source_files` keys to be relative to
   my repo root, so that the paths read naturally as the tree I'm syncing.
3. As a developer running sync from inside my repo checkout, I want sources to resolve
   against my current directory by default, so that the zero-config path "just works".
4. As a maintainer, I want `base_dir` gone from config, the library API, and the docs, so
   that there's one source-resolution concept to learn, document, and test.
5. As a test author, I want to keep injecting a throwaway resolution root, so that sync
   tests still run hermetically without touching real user directories.

## Implementation Decisions

- **`SyncEngine` (sss):** constructor takes `project_dir` instead of `base_dir`; the
  resolution root defaults to **cwd** (was `%USERPROFILE%`). This rename is the surviving
  test-injection seam.
- **`connect` / `Sss` / `_SyncSubsystem` (sss):** drop `base_dir` entirely; thread the
  single `project_dir` through to the engine. The one `project_dir` value is used for both
  `select_profile(...)` (git-remote match) and the engine's source root.
- **Config (sss):** remove `base_dir` from `_DEFAULTS` and from config docstrings. No
  automatic migration — this is a **breaking config-format change**.
- **Profile format (sss):** `source_dirs` / `source_files` / `optional_dirs` keys become
  repo-relative — drop the repo-name prefix (`barapp/bin/{build_cfg}` → `bin/{build_cfg}`).
  Update `config.example.json` and `README.md` accordingly.
- **vmctl (`vm.sync`):** drop the `base_dir` passthrough on `run`/`push`/`_connect`;
  `--project-dir` remains the only sync-path knob. vmctl forwards `project_dir` to
  `sss.connect`.
- **`push` is unchanged** — its `source` is resolved as-typed (absolute, else cwd-relative)
  and never used `base_dir` (sss ADR-0003).
- **Recorded as sss ADR-0005** (`sss/docs/adr/0005-project-dir-is-the-source-root.md`),
  status Accepted.

## Testing Decisions

- **A good test** injects a throwaway resolution root (`tmp_path`) and asserts the engine
  resolves a profile's relative source key against `project_dir`, not `%USERPROFILE%` or
  cwd-by-accident. Mirror the existing `SyncEngine(base_dir=str(tmp_path)).run(profile, conn)`
  pattern, renamed to `project_dir=`.
- **Modules tested:** `SyncEngine` (resolution root), `connect`/`Sss` wiring (single value
  flows to both profile selection and engine), and vmctl `vm.sync.run`/`push` (no `base_dir`
  kwarg; `--project-dir` forwarded).
- **Prior art:** `sss/tests/test_sync.py` (~13 `SyncEngine(base_dir=…)` sites),
  `sss/tests/test_config.py` (`base_dir` defaults), `tests/test_integration.py:415-439` and
  `:847` (injected-profile + root seam), and
  `test_push_resolves_source_against_cwd_not_base_dir` (keep, asserting `push` is unaffected
  — rename only the comment/fixture).

## Out of Scope

- Automatic migration of existing `~/.sss/config.json` files (prefix-stripping / `base_dir`
  removal). Users edit configs by hand.
- Supporting source paths that live **outside** the repo via a profile. (`push` still
  handles one-off out-of-tree files.)
- Any change to `push` semantics, profile selection by git remote, the `{var}` substitution
  mechanism, or the sole-profile fallback.

## Further Notes

- **Sharpest behavior shift:** default resolution root changes from `%USERPROFILE%` to cwd.
  Running sync from *outside* the repo without `--project-dir` now resolves against the wrong
  cwd instead of a stable home dir. The ADR records this as accepted.
- **Open question (flagged in conversation):** alternatively, make the resolution root
  **required** (no cwd fallback) so that "ran it from the wrong place" fails loud instead of
  silently resolving against cwd. Decide before implementing.
- **Docs to update with the code** (intentionally not edited ahead of implementation, to keep
  them honest about live behavior): `CONTEXT.md:139`, `sss/CONTEXT.md:13`,
  `sss/config.example.json`, `sss/README.md`.
