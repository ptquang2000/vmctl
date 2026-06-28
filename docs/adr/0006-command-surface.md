# Restructured command surface

## Status

accepted

## Context and decision

The CLI verbs and grouping had grown ad hoc — `power start`, `snapshot take`,
`guest run`/`copy-to`, plus low-value groups (`fs`, `tools`, `vars`, `mks`) —
and were "not universal and hard to use." The user asked to align the surface
with concise, familiar CLI conventions: **high-frequency VM-lifecycle
operations should be short top-level verbs**, and **snapshots should be a verb
group**.

We adopt a **hybrid** structure (not fully flat): the high-frequency
lifecycle and exec/copy verbs are **promoted to the top level** (the VM is the
implicit subject), while specialized domains stay as **named groups**
(`snapshot`, `network`, `shares`, `clipboard`, `auth`, `sync`/`push`).
`snapshot` keeps its group because its verbs form a natural namespace, so
`vmctl snapshot <verb>` reads cleanly.

### Target surface

Top level:

| New | Was | Notes |
|---|---|---|
| `ps [-a]` | `vm list` | **lists running VMs**; `-a` includes stopped/suspended |
| `start [vm] [-P]` | `power start` | |
| `stop [vm]` | `power stop` | graceful |
| `kill [vm]` | `power stop --hard` | hard power-off |
| `restart [vm] [-H]` | `power reset` | |
| `pause` / `unpause [vm]` | `power pause`/`unpause` | |
| `suspend [vm]` | `power suspend` | kept |
| `inspect [vm]` | `inspect` + `power state` + `parse-vmx` | absorbs state/vmx dump |
| `clone [vm] <dest>` | `vm clone` | VMware term |
| `exec [vm] <cmd…>` | `guest run` | headless by default, `-t` shell, `-i` desktop, `-it` both |
| `cp <src> <dst>` | `guest copy-to` + `copy-from` | merged; `vm:path` syntax |

`snapshot` group:

| New | Was | Notes |
|---|---|---|
| `snapshot log` | `snapshot list` | |
| `snapshot commit <name> -m <msg>` | `snapshot take` | memory-default; `--disk-only` escape |
| `snapshot reset <name>` | `snapshot revert` | discard current state and jump to the snapshot |
| `snapshot rm <name> [-c]` | `snapshot delete` | |

Kept groups, `list`→`ls` for consistency: `network` (ls/ip/connect/disconnect/
set-type/set-name), `shares` (ls/add/remove/set-*). Unchanged: `clipboard
push/pull`, `auth set`, top-level `sync`/`push`.

**Removed entirely:** the `power` group (flattened), the `guest` group
(`run`→`exec`, `copy-*`→`cp`, and **`guest ps`/`guest kill` dropped** so `ps`
means list-VMs and `kill` means hard-stop-VM with no collision), and the
`fs`, `tools`, `vars`, `mks` groups.

### Key sub-decisions (grilled)

- **`ps` = list running VMs**, not guest processes. Dropping
  `guest ps`/`guest kill` is what frees the words `ps` and `kill` for their
  VM-level meanings.
- **`snapshot commit` memory default.** Memory is captured when the VM is
  running, disk-only automatically when off (matches the Workstation GUI;
  reverses today's disk-only default — findings #17/#20). `-m`/`--message` is
  now the snapshot description; the old `-m`=`--memory` short flag is gone.
  `--disk-only` forces a fast no-RAM snapshot on a running VM.
- **`snapshot reset`, not `revert`/`restore`.** Reverting discards current
  state and jumps to the saved point — a destructive whole-state jump. `reset`
  was chosen because its destructive connotation is accurate; `revert` and
  `restore` both suggest softer, more selective operations than what actually
  happens.
- **`cp` merges both directions** with a `vm:path` syntax; direction is
  inferred from which side carries the `vm:` prefix; leading `:` auto-selects.
  **Windows drive-letter disambiguation:** a token whose colon is preceded by
  exactly one alpha char and followed by `\` or `/` (`C:\dir`) is a host drive
  path; otherwise the part before the first colon is the VM name.
- **`stop` stays graceful, `kill` stays hard.** The graceful/hard split is
  preserved; `stop` is *not* changed to default to a hard power-off. `vmrun stop
  soft` can hang on a guest without Tools, but the remedy is to reach for
  `kill`, not to overload `stop`'s default (which would make `stop` and `kill`
  identical).
- **`exec` is headless by default, with two orthogonal flags.**
  This *keeps* the Session-0 default rather than reversing it (an earlier draft
  proposed interactive-by-default; rejected once two vmcli realities were pinned
  live). vmcli `Guest run` **cannot return the guest program's stdout** to the
  host (it only launches), and accepts the program **plus exactly one argument
  token**. So `exec` does no output capture, and the shell wrap is what unlocks
  multi-arg commands and bare-name/builtin resolution.
  - **bare `exec`** → headless Session 0, program run directly via vmcli (so
    absolute path is safest; bare program + ≤1 arg only — >1 token errors with a
    pointer to `-t`).
  - **`-t/--tty`** → wrap the whole command line as a single
    `cmd.exe /c start "" <cmd>` token (`/bin/sh -c '<cmd> &'` on Linux, by sniffed
    `guestOS`); the shell resolves PATH, builtins, pipes, and multiple args, and
    **`start`/`&` detaches the program into its own process so the shell exits
    immediately** — the call waits only for the launch, not the program's
    lifetime, so long-running/GUI programs don't hang the CLI. Headless.
  - **`-i/--interactive`** → vmcli `--interactive`, run on the interactive
    desktop (GUI window appears), fire-and-forget. `--interactive` does not search
    PATH, so `-i` alone **requires an absolute program path**.
  - **`-it`** → `cmd.exe /c start "" <cmd>` on the interactive desktop: a GUI app
    launches PATH-resolved, no absolute path needed (`vmctl exec -it notepad`),
    and the `start`-detach leaves no lingering `cmd`. The GUI sweet spot.

  Flags are booleans with long + short forms (`-i/--interactive`,
  `-t/--tty`) whose single-letter forms combine (`-it` == `-i -t`, native Click).

  Rejected **interactive-by-default**: it optimizes only the GUI-launch case but
  makes the common `vmctl exec ipconfig` reflex silently return nothing,
  and conflates two unrelated axes — *which session* (headless vs desktop) and
  *whether to use a shell* (PATH/builtins) — into one flag. Splitting them into
  `-i` (session) and `-t` (shell) keeps each reflex intact.
- **Command short-forms (aliases).** Longer groups/verbs get Click aliases —
  `ss`/`snapshot`, `net`/`network`, `in`/`inspect`,
  `re`/`restart`, `ex`/`exec`; the already-short lifecycle verbs get none. New
  convention beyond ADR-0005 (which covered only option short flags); aliases are
  additive and never canonical in help/output, a deliberate vmctl-only
  ergonomics addition.

## Considered options

- **Fully flat** — flatten even guest fs/snapshot verbs to the
  root. Rejected: forces unnatural names on guest-interior ops and piles up
  collisions (`ps`, `cp`, `commit`, `rm` all contend at the root).
- **Keep groups, rename leaves only** — lowest churn but barely improves
  ergonomics; the common verbs stay two tokens deep (`power start`).
- **Hybrid: flatten lifecycle + exec/cp, keep the rest grouped (chosen)** —
  the verbs typed constantly are one token; specialized domains keep a
  clear namespace.

## Consequences

- **Large breaking CLI change** (consistent with ADR-0001/0002). Every
  lifecycle invocation changes shape; four whole groups disappear; `list`→`ls`
  across groups. README, CONTEXT.md, and the CLI tests need rewriting.
- **Optional-VM-name / leading-`--` rules (ADR-0001) carry over unchanged** —
  the flattened verbs are still `VMCommand`s with an optional leading name.
- **`inspect` widens** to cover the dropped `power state` and `parse-vmx`
  outputs; its result shape must include power state.
- **Dropping `fs`/`tools`/`vars`/`mks` removes capability**, not just names.
  Only `fs` is genuinely *replaced* — by `exec` (guest-native file commands) +
  `cp` (small) + `sync`/`push` (large). `tools` (host-side `--backingType`
  install), the host-side `vars` namespaces (guestVar/runtimeConfig), and all of
  `mks` (screenshot, send-key, set-resolution/displays) are **cut, not
  relocated** — no `exec`/`cp`/`sync`/`push` equivalent. Acceptable per the user.
  (guestVar survives internally for `network.ip()`'s fallback; only its CLI
  surface goes.)
- **Library (`__init__.py` modules) can stay** — this is primarily a CLI
  re-layering; the underlying `power`/`snapshot`/`guest` modules need not be
  renamed, only the Click wiring. (To confirm at implementation.)
