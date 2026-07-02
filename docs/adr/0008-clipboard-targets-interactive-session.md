# Clipboard targets the interactive guest session

## Status

accepted (supersedes the `interactive=False` clipboard recipe recorded during the
2026-06-22 integration pass)

## Context and decision

`vmctl clipboard push/pull` is the **host↔guest text bridge**: `push` sets the
guest's clipboard so a logged-in user can Ctrl+V it; `pull` prints the guest's
clipboard to host stdout (pipeable into the host's own clipboard). Both halves
must touch the clipboard the logged-in guest user actually sees.

The original recipe ran `clip.exe` / `Get-Clipboard` through
`vmcli Guest run` **without** `--interactive` and reported `{"success": True}`.
It was wrong: a non-interactive `Guest run` executes in a **separate window
station** with its **own clipboard**, invisible to the interactive desktop
(`WinSta0\Default`). `clip.exe` exited 0 into a phantom clipboard nobody sees,
and `Get-Clipboard` read that same phantom back — so the push→pull round-trip
was internally self-consistent (the integration test passed) while being
completely invisible to the real user. This is the reported "returns success
but does nothing" bug.

**Decision: run both halves with `--interactive` so they touch the logged-in
desktop's clipboard, and gate on an interactive session existing.** Proven live
(2026-07-02, `win10-x64`, logged-in memory snapshot):

- push `interactive=False`, then read `interactive=True` → the read returned the
  *desktop's* real clipboard, NOT our pushed marker. push `interactive=True`,
  read `interactive=True` → round-tripped. Reading `interactive=False` after the
  interactive push still showed the old phantom value. Two clipboards, proven.
- The `pull` still uses the **file-redirect artifact channel** (`> out.txt`,
  `--noWait`, poll, `copyFrom`), not stdout capture — an interactive program's
  stdout isn't ours to inherit, but `cmd` performs the `>` redirect in-guest
  regardless of window station. (The earlier pass blamed the empty pull on
  interactivity; the real cause was relying on stdout instead of the file.)

### Consequences

- **`--interactive` does not search `PATH`.** Bare `cmd.exe` fails with
  "A file was not found"; the program must be an **absolute path**
  (`C:\Windows\System32\cmd.exe`). This is a general `--interactive` property
  (see ADR-0006 `exec -i`), surfaced here for the first time in a *waited*
  console-tool run.
- **Precondition gate (fail loud).** No interactive desktop means no clipboard
  to touch — a cold boot sitting at the login/lock screen reports
  `running=true` but `GuestCaps.copyPasteGuestVersion=0` for minutes, whereas a
  resumed logged-in memory snapshot reports `> 0` at once (verified live
  2026-07-02: the `vmctl` `init` snapshot resumes straight to a logged-in
  desktop and reads `copyPasteGuestVersion=4` immediately — the full integration
  suite, both clipboard round-trips included, passes against it. The `=0`
  login-screen case is a cold boot, not this snapshot).
  `ClipboardModule.push_text`/`pull_text` each query `Tools Query` first and
  raise `VMCtlError` unless `running is True AND copyPasteGuestVersion > 0`. The
  gate lives in the **module** (not the CLI) so the library also tells the
  truth, mirroring the `guest.copy_to` size-check placement. `copyPasteGuestVersion`
  is chosen over the broader `guestCapable` because it is the exact capability
  this feature depends on.
- **Waited interactive run is fine for quick tools.** `clip.exe < file` runs
  `--interactive` and *waited* (`no_wait=False`) and completes — contrary to the
  "interactive = always fire-and-forget" shorthand; the pull's nested powershell
  still needs `--noWait` + poll (unchanged reason).
- **Windows-only fix.** The Linux (`xclip`) path has the same isolation class
  (needs the X session's `DISPLAY`), but no Linux guest is available to verify;
  it stays best-effort and is documented as unverified in `CONTEXT.md`. No gate
  is added to the Linux path (no proven equivalent signal).

## Considered options

- **Keep `interactive=False`** — rejected; it is the bug (phantom clipboard).
- **Gate in the CLI** — rejected; the library must not silently mislead
  programmatic callers.
- **Hard-refuse non-Windows guests** — rejected; forecloses a path that may
  already partly work. Best-effort + honest docs preferred.
