# `cp` uses the vmrun VIX backend and stays single-file

## Status

accepted (supersedes the `vmcli Guest copyTo/copyFrom` backend and the
`_COPY_TO_MAX_BYTES` size refusal recorded for `guest.copy_to`/`copy_from`)

## Context and decision

`vmctl cp` is the **single-file host↔guest copy** built on VMware Tools. Its
`vm:path` grammar, `:path` auto-select, drive-path disambiguation, `-o/--overwrite`
flag, and cp/scp trailing-slash resolution are settled (see `_split_vm_path`,
`_resolve_dest`) and are **not** changed here. What changes is the transport
underneath and the directory story.

The reported bug: `vmctl cp ./big.msi vm:C:\dst` fails on a 6.5 MB payload.
Root cause pinned live (2026-07-02, `win10-x64`, bisected to the byte):
**`vmcli Guest copyTo` has a hard 65400-byte wall** — 65400 B copies, 65401 B
fails with an opaque `vmcli.exe: Unknown error` and lands a **0-byte stub** in
the guest. The wall is `vmcli`-channel-specific and content-independent. The
same VIX transfer through **`vmrun CopyFileFromHostToGuest` has no wall** —
6.5 MB (2.5 s) and 50 MB (17 s) land full-size. `vmrun CopyFileFromGuestToHost`
is likewise unbounded (verified to 1 GB) and surfaces access/missing errors
cleanly. The ~64 KB ceiling is purely a `vmcli Guest copyTo` message limit, not
a VIX/Tools limit.

**Decision: route both directions of `cp` through the vmrun VIX verbs, keep
`cp` single-file, and pre-flight the source for directory-ness.**

1. **Backend → vmrun, both directions.** `copy_to` calls
   `vmrun CopyFileFromHostToGuest <vmx> <host> <guest>`; `copy_from` calls
   `vmrun CopyFileFromGuestToHost <vmx> <guest> <host>`. Both pass guest creds
   as `-gu <user> -gp <pass>` **before** the verb (the `vars.py` `guestEnv`
   convention). One transport, one cred convention, one error surface. The
   opaque-`Unknown error`/0-byte-stub failure mode leaves the product entirely.
   `_COPY_TO_MAX_BYTES`, `_LARGE_FILE_HINT`, and the two vmcli-specific
   "not a file" catch-and-re-raise blocks are **deleted** — vmrun has no wall to
   guard and emits its own legible errors. `copy_from` was already unbounded on
   vmcli (no bug forced its switch); it moves anyway so the two directions stay
   symmetric rather than straddling two backends.

2. **Single-file only; directories point at `push`.** Neither vmcli nor vmrun
   copy trees — both are single-file primitives. `cp` does not hand-roll a
   tree-walk (per-file VIX spawns + guest-side `Guest ls` pagination, finding
   #19, would be a slow, fragile reimplementation of what `vmctl push` already
   does natively over SSH/sss, ADR-0003). A directory **source** is refused with
   an actionable error naming `vmctl push`. This holds the same host↔guest
   boundary drawn everywhere: `cp` = fast single file, `push` = trees + perms +
   unbounded.

3. **Proactive symmetric directory guard.** The source is checked *before* any
   copy call, both directions:
   - **copy_to** (host source): `os.path.isdir(host_path)` — a local check, no
     wasted VIX round-trip.
   - **copy_from** (guest source): `vmrun directoryExistsInGuest <vmx> <path>`.
     Verified live — `directoryExistsInGuest`/`fileExistsInGuest` exist, are
     mutually exclusive (a dir-check on a file cleanly answers "does not exist"),
     and need no `_parse_ls` columnar/pagination parsing. This is the exact
     question ("is the guest source a directory?") answered by a first-class VIX
     predicate on the transport we already use.

4. **Inverted-exit-code contract quarantined in a runner helper.** The existence
   verbs invert intuition: path **exists → exit 0** (stdout `"The directory
   exists."`); path **absent → exit 127** (stdout `"The directory does not
   exist."`, empty stderr). `Runner._exec` raises `VMCtlError` on any nonzero
   code, so a normal "false" answer would arrive as a raised exception
   indistinguishable from a real failure. A new `Runner.run_vmrun_test(*args) ->
   bool` runs the verb and inspects **stdout**: contains `"exists."` and not
   `"does not"` → `True`; `"does not exist"` → `False`; anything else (auth
   failure, VM off, Tools wedged) → still `raise VMCtlError`. The string-matching
   lives in exactly one place; `run_vmrun` stays untouched for the copy verbs;
   `guest.py` branches on a clean boolean.

### Consequences

- **6.5 MB MSI (and up) copies work** with no HGFS/SSH detour and no size
  warning — vmrun just transfers it.
- **`-o/--overwrite` is enforced by vmctl.** vmrun's copy verbs always overwrite
  (verified live: a repeat copy onto an existing dest returns exit 0). To preserve
  the flag's meaning, each direction pre-flights the destination when `-o` is
  absent (`fileExistsInGuest` for the guest dest, `os.path.exists` for the host
  dest) and refuses if it already exists; with `-o` the check is skipped.
- **`cp` help text is rewritten.** The old string ("<=60 KB, file dest; for
  large files use `vmctl push`") is now wrong. New: single-file, any size; for
  **directories** use `vmctl push`.
- **Guest ops run under vmtoolsd/SYSTEM privilege** (finding #25), so no guest
  destination path restrains the copy — `C:\`, `C:\Windows\`, `C:\Program Files\`
  all accept writes. Only directory-ness of the *source* gates `cp`.
- **One extra vmrun spawn per copy_from** for the directory pre-flight
  (sub-second against a multi-second transfer). copy_to's guard is a free local
  `isdir`.
- **`_resolve_dest`/`_basename`/`_is_abs` survive untouched** — they are
  backend-independent path arithmetic.

## Considered options

- **Hybrid backend — vmcli under 65400 B, vmrun above.** Rejected. Its only
  upside is unmeasured small-file speed; its cost is keeping the opaque
  silent-failure vmcli path alive as a live branch forever and making the
  threshold load-bearing (wrong → silent 0-byte stub). One backend = one error
  surface.
- **Leave `copy_from` on vmcli** (it has no wall). Rejected. Asymmetric — two
  transports, two cred conventions, two error-handling blocks for one command.
  vmrun copyFrom is proven unbounded and more legible.
- **Implement recursive directory copy in vmctl.** Rejected. Per-file VIX spawns
  + hand-rolled guest tree-walk (with `Guest ls` pagination) reinvents `push`
  badly. `push` is the tree path by design.
- **Pre-flight the guest source with `vmcli Guest ls`.** Rejected for the stat —
  paginates at ~25 entries and needs fragile columnar parsing (findings #16/#19);
  `directoryExistsInGuest` answers the question directly.
- **String-match `VMCtlError.message` at the call site** for the existence
  verbs, or **treat exit 127 as non-fatal globally.** Both rejected — the first
  spreads brittle exception-string-matching into `guest.py` (the exact opacity
  we are removing); the second masks genuine 127 failures elsewhere (HGFS finding
  #2, disk ConnectionControl on an offline VM finding #22).
- **`-a`/archive, `-L`/symlinks, `-`/stdin-stdout tar stream.** All rejected as
  out of scope — no VIX primitive, and perms/symlink semantics are empty against
  a Windows guest whose files land under SYSTEM context. That fidelity is
  `vmctl push` territory.
