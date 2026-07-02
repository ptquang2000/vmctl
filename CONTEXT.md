# vmctl Context

vmctl wraps VMware Workstation's `vmcli.exe` and `vmrun.exe` into a **JSON-native Python API** and a **human-readable CLI** (ADR-0007): the library returns native dicts for programmatic callers; the CLI renders human-readable text and never emits JSON. This file records domain terms and conventions not obvious from the code. Deep rationale lives in `docs/adr/`.

## Language

- **Adapter config** — *static* virtual-NIC settings in the `.vmx` (connection type, MAC, network name). From `network.list()` via `vmcli Ethernet query`. Exists even when off. _Avoid_: "network settings".
- **Guest IP** — *runtime* IP the running guest reports via `guestInfo`. From `network.ip()` via `vmrun getGuestIPAddress`. Only exists once the guest is up and addressed. _Avoid_: "address", "network IP".
- **Stale guest IP** — a *suspended* VM still answers `getGuestIPAddress` with its last-known IP (exit 0, no error), which may be invalid after resume. Callers needing a live IP must confirm running first.

## Name aliases (config remapping)

A VM may be referred to by a **remapped name** (*alias*) in `~/.vmctl/config.json` under `"aliases"`, separate from the auto-discovered registry of `.vmx` stems:

```jsonc
{ "scan_roots": ["C:/Users/.../Virtual Machines"],
  "aliases": { "dev": "windows-10-x64",      // -> discovered VM (registry name)
               "db":  "D:/VMs/db/db.vmx" } } // -> .vmx path (may be OUT of scope)
```

- **Alias** — a hand-edited handle resolving to either a discovered VM **name** or a direct **.vmx path**. Value is **sniffed**: path-shaped *and* file exists ⇒ path; else ⇒ registry name. No `vmctl alias` CLI verb. _Avoid_: "rename" (the alias is an extra input-side handle).
- **Resolution order** (`VMRegistry.find()`): exact alias (case-insensitive) → exact stem → unique substring → error. An alias always wins over substring and over a same-named stem — explicit config beats fuzzy discovery.
- **Input-only — the real VM name stays canonical.** Resolving via alias does not change the `vm` output key or the credentials key; both stay the real registry name (`name_for_path()` unchanged). One *intrinsic* exception: an alias to a `.vmx` **outside scan roots** has no registry name, so `name_for_path()` returns `None` and the alias becomes canonical via `get()`'s `or name` clause (creds keyed by the alias). Auto-select never yields an alias.
- **One hop, no recursion** — an alias value is sniffed as path or stem, never as another alias.
- **Broken-alias errors name the alias** (`ValueError` from `find()`, caught by CLI alongside `VMCtlError`): path-shaped but missing ⇒ `alias 'dev' points to missing .vmx: <path>`; name-shaped but unresolvable ⇒ `alias 'dev' -> 'foo': VM not found`.

## CLI VM selection (optional VM name)

Every VM command takes the VM **name** as its first positional, which may be **omitted** to auto-select the single running VM. Use a leading `--` only when other positionals follow, so the first remaining token isn't read as the name.

| Command shape | Explicit | Auto-select |
|---|---|---|
| Name-only (`power state`, `network ip`, …) | `power state myvm` | `power state` |
| Extra positionals (`snapshot take`, `guest copy-to`) | `snapshot take myvm s1` | `snapshot take -- s1` |
| Variadic (`guest run`) | `guest run myvm cmd /c hi` | `guest run -- cmd /c hi` |

- **Trigger = exactly one *running* VM in scope** — `vmrun list` ∩ registry. Out-of-scope running VMs are ignored. So the resolved VM always has a **name** but not necessarily stored credentials; cred-dependent commands (`sync`/`push`) must tolerate an empty cred dict.
- **Off-by-nature targets can't auto-select** — `power start`, `clone`, offline `snapshot revert` rarely match the running-VM trigger (intended).
- **Scope** = all VM-operating commands except `vm list` and `auth set` (a config write keyed by name).
- **Leading `--` is a custom marker, not Click's terminator.** If the first token after the subcommand is `--`, the CLI strips it, auto-resolves, and hands the rest to Click. Only the *leading* `--` is special (`snapshot take -- s1 --memory` still parses `--memory`).
- **No silent count-based fill** — `snapshot take myvm` (forgot snap name) is a clean missing-argument error; `myvm` is never reinterpreted.
- **Every *library* result carries a `vm` key** (canonical registry name) for uniform dict shape `{"vm": "<name>", …}`. The **CLI** does not surface this as a field — it becomes the table header / the name in a confirmation line (see "CLI output rendering").
- **Reverse-mapping** a running `.vmx` to its name (for cred lookup) inverts the registry case-insensitively / path-normalized.
- **Failure modes:** zero running → `no running VM to auto-select; pass a name`; ≥2 → error listing them, `pass a name`.

## CLI short forms — option flags (ADR-0005)

Options carry short flags. **Short flags are command-scoped mnemonics, not a global letter map** — Click resolves them per command; the only rule is within-command uniqueness. Each option takes the clearest *local* mnemonic, preferring Unix convention (`fs mkdir -p`=`--parents`, `fs rmdir -r`=`--recursive`). The same letter varies by command — `-d` is `--description`/`--dir`/`--project-dir`; `-p` is `--password`/`--parents`/`--prefix`. **Per-command `--help` is the source of truth.** Soft convention: where a command takes credentials, `-u`/`-p` = user/password.

## Command surface (ADR-0006)

The CLI is laid out so **VM lifecycle verbs sit at the top level** and
**snapshots form a `snapshot` group**. Structure is **hybrid**: lifecycle +
exec/copy verbs flatten to the top level, everything else stays grouped.

- **Top level:** `ps` (lists *running* VMs; `-a` = all), `start`,
  `stop` (graceful), `kill` (hard power-off), `restart`, `pause`/`unpause`,
  `suspend`, `inspect` (absorbs old `power state` + `parse-vmx`), `clone`,
  `exec` (was `guest run`; **headless by default** — `-t/--tty` wraps through the
  guest shell (PowerShell via `-EncodedCommand` on Windows / `/bin/sh -c` on
  Linux) for PATH/builtins/pipes and detaches at launch; without `-t` you name
  the program + args directly (mode B); `-i/--interactive` runs on the
  interactive desktop fire-and-forget for GUI apps (absolute path); `-it` = both
  (GUI sweet spot, no absolute path); short flags combine (`-it`);
  no stdout capture since vmcli `Guest run` can't return guest output), `cp`
  (merges `copy-to`/`copy-from`, `vm:path` syntax — direction from the
  `vm:` side, leading `:` auto-selects, a one-alpha prefix + `:\`/`:/` is a host
  drive not a VM).
- **`snapshot` group:** `log`, `commit <name> -m <msg>` (**memory-default** when
  running / disk-only when off; `--disk-only` forces fast no-RAM; old
  `-m`=memory short flag gone), `reset` (was `revert`), `rm`.
- **Kept groups** (`list`→`ls`): `network`, `shares`; unchanged
  `clipboard`, `auth`, top-level `sync`/`push`.
- **Removed:** the `power` group (flattened), the `guest` group (`guest ps`/
  `kill` dropped so `ps`/`kill` are free for the new top-level meaning), and `fs`,
  `tools`, `vars`, `mks` entirely.

## CLI output rendering — human text, JSON is library-only (ADR-0007)

The CLI **never emits JSON**; raw JSON is the *library's* return contract for
programmatic callers. The CLI renders human-readable text (extends ADR-0006
from verbs to output). Rendering lives in pure `vmctl/render.py` (`dict -> str`,
no Click) so it's unit-tested as strings.

- **Collections → aligned tables.** `ps` as a table;
  `snapshot log` as a log (`*` current-marker); `network ls` plain table.
  Booleans → `yes`/`no`; unknown/`null` → `-`. Empty → header
  row only.
- **Scalar value-reads stay bare** (`network ip`, `clipboard pull`): the value
  alone, no label/`vm:` prefix, so they're **pipeable**. Empty IP → blank line.
- **Mutations → `verb + canonical name`** (`started windows-10-x64`).
  Synthesized in the CLI (library returns are contentless `{"success": True}`);
  naming the VM discloses auto-select.
- **`exec`** → `launched on <vm>` (no guest stdout to return — ADR-0006).
  **`cp`** → `copied <src> -> <vm>:<dest>`. **`push`/`sync`** → progress on
  stderr, `pushed …`/`synced <vm>` on stdout. **`auth set`** →
  `credentials set for <name>`.
- **`inspect` → curated summary** (power/identity header + the snapshot/disk/
  network/tools tables), **not** the full dump — the exhaustive 10-query +
  `.vmx`/`.vmsd` data stays available via the library (`vm.inspect.inspect()` +
  `parse_vmx()`). A debug dump is the use case meant to drop into the library.
- **Errors → `error: <msg>`** on stderr, exit 1; stdout stays clean for pipes.
- _Verified live (2026-06-28):_ `Snapshot query` exposes `currentUID` (drives the
  `snapshot log` `*` marker); `Ethernet query` devices carry
  `label`/`connectionType`/`networkName`/`connectionStatus` (the `network ls`
  columns). `Tools Query` uses `running` + `version` (the `inspect` tools facts).

## snapshot reset lifecycle (ADR-0002, ADR-0006)

> Renamed `snapshot revert` → `snapshot reset` (ADR-0006): reverting discards
> current state and jumps to the saved point. Behavior unchanged.

`snapshot reset` is a lifecycle macro, not a bare vmcli call: vmcli `Snapshot Revert` **errors while the VM is online** (running/paused) but tolerates off/suspended. The snapshot name is **resolved/validated first**, so a typo never powers off the VM.

`SnapshotModule.revert(name)` restores prior power state: online → hard-stop → revert → start; suspended/off → revert only (state preserved).

- **Hard stop, not soft** — revert discards running state anyway; a graceful shutdown is wasted and can hang without Tools.
- Overturns the earlier "library stays faithful to must-be-off" rule: the library now owns the stop/revert/restore lifecycle. `revert(name, ensure_running=True)` forces a start regardless of prior state.
- **CLI `vmctl snapshot reset` always ends running** (suspended→resume, off→cold boot) via `revert(..., ensure_running=True)`. (Library method stays `SnapshotModule.revert`; only the CLI verb is `reset` — ADR-0006.)

## vmcli vs vmrun

**"query" does not imply vmcli.** The rule is:

> Use `vmcli` where it works; fall back to `vmrun` where vmcli has no equivalent or is broken.

Both reads and writes use vmrun when vmcli can't serve them: `power.state()` reads via vmcli but all power *mutations* use vmrun (vmcli `Power Start` needs `__vmware__`-group/admin); `vars.read()`/`write()` both use vmrun (no vmcli variable namespace); `network.ip()` reads via vmrun because `vmcli Ethernet query` returns only adapter config, never the guest IP.

## network.ip() contract (verified live, 2026-06-22)

`network.ip()` → `vmrun -T ws getGuestIPAddress <vmx>` (no `-wait`), returns `{"ip": <str>}`.

| VM state | vmrun exit | Result |
|---|---|---|
| Running, IP assigned | 0 (~0.6s) | `{"ip": "192.168.x.x"}` |
| Running, no IP yet | 0 | `{"ip": ""}` — empty, no raise |
| Suspended | 0 | `{"ip": "<stale IP>"}` — see Stale guest IP |
| Powered off | 127, error on stdout | raises `VMCtlError` |

- No guest credentials required (host-side `guestInfo` read).
- `-wait` intentionally **not** exposed (can hang forever; callers poll). `-snapshot=` irrelevant and ignored.
- **Resume wedges the VIX channel — falls back to `guestinfo.ip`.** After resuming a suspended/memory snapshot, `getGuestIPAddress` can fail with `The VMware Tools are not running` for the **whole resumed session** even though Tools are up (it gates on a VIX heartbeat the resume leaves wedged; only a guest **reboot** fixes it). Since `getGuestIPAddress` ≈ `guestinfo.ip` + heartbeat gate, `ip()` catches the "not running" failure and falls back to `vmrun readVariable <vmx> guestVar ip` (no heartbeat, no creds). Fires **only** on "not running" — "not powered on" still raises, so an off VM is never masked. If cached `guestinfo.ip` is also empty, the original error re-raises. (Verified 2026-06-25.)

## Guest file copy (`guest.copy_to` / `guest.copy_from`) — vmrun VIX backend (ADR-0010)

`cp` is the **single-file** host↔guest copy over VMware Tools. Both directions
run the **vmrun VIX** verbs (not `vmcli Guest copyTo/copyFrom`), with guest creds
as `-gu <user> -gp <pass>` **before** the verb (the `vars.py` `guestEnv` convention):
`copy_to` → `CopyFileFromHostToGuest <vmx> <host> <guest>`; `copy_from` →
`CopyFileFromGuestToHost <vmx> <guest> <host>`.

- **No size wall (ADR-0010).** The ~64 KB ceiling was `vmcli Guest copyTo`-specific
  (65400 B OK / 65401 B → opaque `Unknown error` + 0-byte stub). vmrun's VIX
  channel is unbounded both directions (verified: 6.5 MB/50 MB in, 1 GB out). The
  old `_COPY_TO_MAX_BYTES` guard, `_LARGE_FILE_HINT`, and the vmcli "not a file"
  re-raises are **gone** — the 6.5 MB MSI copies with no HGFS/SSH detour.
- **Single-file only; directories → `push`.** Neither backend copies trees. A
  directory **source** is refused up front with an actionable error naming
  `vmctl push` (which does trees natively over SSH/sss). vmctl does **not**
  hand-roll a tree-walk. The guard is proactive and symmetric: `copy_to` checks
  `os.path.isdir(host)`; `copy_from` checks `vmrun directoryExistsInGuest <path>`.
- **`directoryExistsInGuest`/`fileExistsInGuest` — inverted exit code.** exists →
  exit 0 (`"The … exists."`); absent → exit **127** (`"The … does not exist."`,
  stdout only, empty stderr). Since `Runner._exec` raises on any nonzero code, the
  boolean-false would look like a real failure — so `Runner.run_vmrun_test(*args)
  -> bool` runs the verb without raising, parses **stdout** (`"exists."` & not
  `"does not"` → True; `"does not exist"` → False; anything else → raise). One
  helper owns the string-matching; `run_vmrun` is untouched for the copy verbs.
- **Path arithmetic unchanged.** `_split_vm_path`, `_resolve_dest`, `_basename`,
  `_is_abs` (cp/scp trailing-slash + bare-drive-root resolution) are
  backend-independent and survive verbatim. Missing / access-locked sources are
  left to vmrun's own legible errors (`A file was not found` / `access rights`,
  finding #25) — no redundant pre-flight.
- **`-o/--overwrite` is enforced by vmctl, not vmrun.** vmrun's copy verbs
  *always* overwrite (verified live 2026-07-02: a second `CopyFileFromHostToGuest`
  onto an existing dest returns exit 0, no refusal). To keep the flag meaningful,
  each direction pre-flights the *destination* when `-o` is absent and refuses if
  it exists — `fileExistsInGuest` for `copy_to`'s guest dest, `os.path.exists` for
  `copy_from`'s host dest. With `-o` the pre-flight is skipped and vmrun's native
  overwrite takes over.
- **Guest ops run under vmtoolsd/SYSTEM privilege**, so no guest destination path
  restrains the copy (`C:\`, `C:\Windows\`, `C:\Program Files\` all accept writes).
- **No programmatic copy-paste / drag-and-drop.** The GUI host↔guest file CP/DnD has **no CLI/API/RPC** — it's a GUI-only feature of Workstation + `vmtoolsd -n vmusr` on the CP/DnD backdoor channel, undrivable by vmcli/vmrun. Do not re-investigate. The `clipboard` module handles **text only**, unrelated to file paste.

## clipboard text (push / pull) — the host↔guest text bridge (ADR-0008)

The `clipboard` module is the **host↔guest text bridge**: `push` sets the guest's clipboard (Ctrl+V-able by the logged-in user; feed the host clipboard in via `Get-Clipboard | vmctl clipboard push`), `pull` prints the guest clipboard to host stdout (pipe into the host's `Set-Clipboard`). It round-trips by staging a temp file via `Guest copyTo`/`copyFrom` and driving the native tool: Windows pushes via `clip.exe`, pulls via `powershell Get-Clipboard`; Linux uses `xclip`. Guest OS sniffed once via `ConfigParams query` (`guestOS`), with a `guest_os_fn` injection seam for tests.

- **Interactive-session clipboard, NOT the phantom one (ADR-0008).** Both halves run `vmcli Guest run --interactive` so they touch the logged-in desktop's clipboard (`WinSta0\Default`). A *non*-interactive `Guest run` has its own separate window-station clipboard, invisible to the user — the source of the old "reports success but pastes nothing" bug (push→pull was self-consistent against the phantom clipboard). Proven live 2026-07-02.
- **`--interactive` does not search `PATH`** — the program must be an absolute path (`C:\Windows\System32\cmd.exe`), else vmcli errors `A file was not found`.
- **Precondition gate — fail loud (ADR-0008).** No logged-in desktop = no clipboard to touch. `push_text`/`pull_text` each run `Tools Query` first and raise `VMCtlError` unless `running is True AND GuestCaps.copyPasteGuestVersion > 0`. A cold boot at the login/lock screen reports `running=true` but `copyPasteGuestVersion=0` for minutes — that's the "does nothing" case, now a clear error. Gate lives in the **module** so the library also tells the truth.
- **Windows pull is `--noWait` + poll, not synchronous** — vmcli's synchronous wait returns before the nested `cmd → powershell` grandchild finishes, so the read fires `--noWait` and its artifact file is polled (`_poll_guest_file`, bounded by `_PULL_POLL_TIMEOUT_S`); on timeout (or genuinely empty clipboard) returns `""`. Push uses `clip.exe` as a **direct** child of cmd, so a waited run (`--interactive`, `no_wait=False`) reliably sets the clipboard before return.
- **Linux is unverified (ADR-0008).** The `xclip` path shares the isolation class (needs the X session's `DISPLAY`) but no Linux guest exists to verify it; it's best-effort and carries no session gate. Do not claim it works.
- **`clipboard push` lone-token case.** Both positionals (`name`, `text`) are optional, so `clipboard push hello` binds `hello` to the **VM name**. We don't silently reinterpret it (would violate *no silent fill*). It raises an actionable error naming the three working forms:
  - **pipe:** `echo hello | vmctl clipboard push` (text omitted ⇒ non-tty stdin read; no `--` needed with no trailing positional),
  - **leading `--`:** `vmctl clipboard push -- hello` (the `--` fills the name slot),
  - **name explicitly:** `vmctl clipboard push myvm hello`.
- **Only command with this ambiguity** — an audit found `clipboard push` is the sole command with two optional positionals (caused by the piped-stdin feature making `text` optional); every other command makes non-name positionals required. The empty-text guard, stdin read, and disambiguation live in the **CLI** (`clipboard_push`), not the module; an explicit `text` arg always wins over stdin.

## File sync via sss (ADR-0003)

vmctl **depends on** `sss` (the `./sss` git submodule) and inherits file-sync by composition — the inverse of the original direction (see ADR-0003 and sss ADR-0004). sss is target-agnostic and knows nothing about VMs; vmctl resolves the VM and feeds it a host + credentials.

The seam is **`vm.sync`** (a `SyncModule`), surfaced as **`vmctl sync`** and **`vmctl push`** only:

- `vm.sync.run(sync_optional=False, project_dir=None)` — full profile lifecycle (`pre_sync` → sync → `post_sync`). Profile auto-selects from `project_dir`'s git remote in `~/.sss/config.json`. **Build-config/arch are not vmctl flags** — `{build_cfg}`/`{arch}` come from the profile's `variables` block; `vmctl sync` exposes only `--optional` and `--project-dir` (which both selects the profile and roots its relative source paths — see sss ADR-0005). (The `profile` kwarg is a test seam.)
- `vm.sync.push(source, dest)` — ad-hoc, profile-less transfer.

- **IP read once; sync never boots the VM.** `SyncModule` requires `PowerState == "on"` and non-empty `network.ip()`, else an actionable `VMCtlError` (suspended IP is stale, off has none, just-booted has no lease). Deliberately does **not** follow the snapshot-revert lifecycle-ownership precedent — the caller readies the guest. `import sss` is **lazy** (VM commands work without sss/paramiko) and `SssError` wraps to `VMCtlError`.
- **Credential resolution — stored, with optional inline override.** By default both reuse the VM's stored guest creds from `~/.vmctl/config.json`. `sync`/`push` also accept `-u`/`--user` + `-p`/`--password` under a **both-or-neither** rule: both ⇒ the pair fully replaces stored creds for that run; neither ⇒ stored creds; exactly one ⇒ clean `VMCtlError`. **No field-mixing.** Override is **runtime-only, never persisted** (`auth set` is the sole config writer).
- If no creds resolve, `user`/`password` stay `None` and sss still attempts **publickey/agent** auth (keyless preserved). A password-less `Authentication failed` from sss is caught and re-wrapped with an actionable hint (use `auth set` or pass `--user`/`--password`).
- Resolution, the both-or-neither check, and catch-and-rewrap all live in **`SyncModule`** (CLI just declares options), so they're unit-testable without Click or real sss.

### Two file-into-guest paths (opposite dest and size rules)

| | `cp` (`guest.copy_to`/`copy_from`) | `push` (sss / SSH) |
|---|---|---|
| Channel | `vmrun` VIX (Tools) | SSH / SFTP (needs sshd) |
| Source | single **file** — dir refused (→ `push`) | file or **directory** (tree) |
| Dest arg | full **file** path (dir forms resolved cp/scp-style) | remote **directory** — lands at `dest/<basename>` |
| Size | **unbounded** (vmrun has no wall) | unbounded |
| Needs | Tools running | OpenSSH server + reachable guest IP |

`cp` is single-file over Tools (any size, ADR-0010); a **directory** is exactly what `push` is for. Help strings cross-reference each other.
