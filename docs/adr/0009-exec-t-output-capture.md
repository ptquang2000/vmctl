# `exec -t` captures guest output via a vmrun temp file

`exec` historically returned no guest stdout: `vmcli Guest run` only launches a
program, it never hands back the program's output (ADR-0006). We reverse that
**for `-t`/`-it` only**: those modes now run the command **to completion**,
capture its merged output, print it, and propagate the guest exit code.

## Decision

For a captured run (`-t`, with or without `-i`):

1. **Provision** a guest temp file with `vmrun CreateTempfileInGuest` — it returns
   a guaranteed-unique, guest-writable path in the guest's own `%TEMP%`/`/tmp`.
   We never guess the name host-side (we couldn't know the name the guest picked).
2. **Run blocking** via `vmrun runProgramInGuest` (add `-interactive` for `-it`),
   with the command wrapped to redirect *all* streams into that temp file:
   - Windows: `powershell.exe -NoProfile -EncodedCommand <b64 of
     `& { <cmd> } *>&1 | Out-File -FilePath '<gf>' -Encoding utf8 ; exit $LASTEXITCODE`>`
   - Linux: `/bin/sh -c '{ <cmd>; } > <gf> 2>&1; exit $?'`
3. **Copy back** with `vmrun CopyFileFromGuestToHost` into a host temp file.
4. **Decode & print** the captured bytes verbatim to host **stdout** (UTF-8;
   strip a leading BOM on Windows — PS 5.1 `Out-File -Encoding utf8` writes one).
5. **Propagate** the guest exit code as `vmctl`'s process exit code.
6. **Clean up** both temp files best-effort (`vmrun deleteFileInGuest` +
   the host file), in a `finally`.

The non-capture paths are unchanged: a bare program and `-i`-alone stay
fire-and-forget (`vmcli Guest run --noWait`) and still print `launched on <vm>`.

## Why vmrun, not vmcli

`vmcli Guest run` **never blocks** — even without `--noWait` it returns
immediately with a PID and gives no completion signal (verified live: a 2-second
guest sleep returned in 0.5s, capturing only pre-sleep output). It therefore
cannot support wait-then-capture. `vmrun runProgramInGuest` blocks until the
guest program exits (both plain and `-interactive`, verified live) and
propagates the guest exit code (guest `exit 42` → vmrun exit 42). This is the
"vmrun where vmcli can't serve us" rule (CONTEXT.md "vmcli vs vmrun"), and it
corrects the earlier belief that vmcli `Guest run` has a usable synchronous wait.

## Considered and rejected

- **Split stdout/stderr into two temp files.** Faithful stream separation, but
  doubles the temp-file/copy/cleanup machinery. We merge (`*>&1` / `2>&1`) into
  one file and send it all to stdout — a guest-shell convenience command doesn't
  warrant the extra plumbing. Consequence: guest stderr lands on host stdout.
- **A truncation cap on captured output.** Unnecessary: `CopyFileFromGuestToHost`
  is effectively unbounded (verified into the MB range; the ~64 KB wall is a
  `copyTo`-only quirk).
- **A `--timeout`.** `-t` blocks until the command finishes, like any shell.
  Non-terminating programs are out of scope for `-t` — use `-i`/fire-and-forget.

## Consequences

- Capture must **not** treat a non-zero guest exit as a runner error — the
  capture path needs a runner variant that returns `(exit_code, output)` instead
  of raising `VMCtlError` on non-zero (the default `Runner._exec` raises).
- `render.exec_launched` stays for the fire-and-forget paths; captured runs
  print raw text and set the exit code (no `launched on` line).
- Under `-it`, a GUI program that never exits blocks the CLI until its window is
  closed — accepted, consistent with "`-t` is for terminating commands".
