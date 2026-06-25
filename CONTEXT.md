# vmctl Context

vmctl wraps VMware Workstation's `vmcli.exe` and `vmrun.exe` into a JSON-native Python API and CLI. This file records the domain terms and architectural conventions that are not obvious from the code alone.

## Language

**Adapter config**:
The *static* virtual-NIC settings stored in the `.vmx` (connection type, MAC, network name). Surfaced by `network.list()` via `vmcli Ethernet query`. Exists whether or not the VM is running.
_Avoid_: "network settings" (ambiguous with runtime state)

**Guest IP**:
The *runtime* IP address the running guest reports through `guestInfo`. Surfaced by `network.ip()` via `vmrun getGuestIPAddress`. Distinct from **adapter config** — it only exists once the guest is up and has been assigned an address.
_Avoid_: "address" (vague — could read as MAC or adapter), "network IP"

**Stale guest IP**:
A *suspended* VM still answers `getGuestIPAddress` with its last-known IP (exit 0) — it does **not** error. So `network.ip()` on a suspended VM may return an address that is no longer valid after resume. Callers needing a guaranteed-live IP must confirm the VM is running first.

## CLI VM selection (optional VM name)

Every command that operates on a VM takes the VM **name** as its first positional
argument. The name may be **omitted** to auto-select the single running VM:

> **Omit the name; use a leading `--` only when other positionals follow**, so the
> first remaining token isn't mistaken for the name.

| Command shape | Explicit | Auto-select single running VM |
|---|---|---|
| Name-only (`power state`, `network ip`, `tools query`, …) | `power state myvm` | `power state` (bare) |
| Extra positionals (`snapshot take`, `guest copy-to`, …) | `snapshot take myvm s1` | `snapshot take -- s1` |
| Variadic (`guest run`) | `guest run myvm cmd.exe /c echo hi` | `guest run -- cmd.exe /c echo hi` |

Rules and rationale:

- **Trigger = exactly one *running* VM in scope** — counted from `vmrun list`
  intersected with the registry (scan roots). Out-of-scope running VMs are
  ignored for both the count and selection (they can't be named via vmctl
  anyway). So the resolved VM always has a name + credentials.
- **Targets that are off by nature can't auto-select.** Because the trigger is a
  *running* VM, `power start`, `clone`, and offline `snapshot revert` rarely
  match — intended, not a bug.
- **Scope = all VM-operating commands except `vm list` (no name) and
  `auth set`** (a config write keyed by name, not an op on a live VM).
- **The leading `--` is a custom marker, not Click's option terminator.** Click
  natively consumes `--` and shifts nothing, so the CLI intercepts it: if the
  first token after the subcommand is `--`, it is stripped, the VM is
  auto-resolved, and the rest is handed to Click. Only the *leading* `--` is
  special, so later flags still parse (`snapshot take -- s1 --memory` → `--memory`
  is still a flag). A `--` anywhere but first keeps its conventional meaning.
- **No silent count-based fill.** `snapshot take myvm` (forgetting the snap name)
  is a clean "missing argument" error — `myvm` is the name, never reinterpreted
  as the snap name. Count-based omission and its wrong-VM footgun were
  deliberately rejected.
- **Every result carries a `vm` key** — typed or auto-selected — for a uniform,
  predictable output shape (`{"vm": "<name>", …}`). The name is the canonical
  registry name. (Existing exact-match unit tests must be updated for this.)
- **Reverse-mapping** a running `.vmx` back to its name (for credential lookup)
  inverts the registry **case-insensitively / path-normalized**, since
  `vmrun list` and `rglob` paths may differ.
- **Failure modes:** zero running in scope → `no running VM to auto-select; pass
  a name`; two or more → error listing them, `pass a name`.

## snapshot revert lifecycle

`snapshot revert` is a lifecycle macro, not a bare vmcli call, because vmcli
`Snapshot Revert` **errors while the VM is "online"** (running/paused) but
tolerates **off or suspended** (see `tests/INTEGRATION.md`). The name is always
**resolved/validated first**, so a typo'd snapshot name never powers off the VM.

**Library `SnapshotModule.revert(name)` — restores prior power state:**

| Prior state | Action |
|---|---|
| Online (running/paused) | hard-stop → revert → start (ends running) |
| Suspended | revert only (stays suspended) |
| Off | revert only (stays off) |

- **Hard stop, not soft.** Revert discards the running state anyway, so a
  graceful guest shutdown is wasted effort (and can hang without Tools).
- This **overturns the earlier "library stays faithful to the must-be-off
  constraint" rule** (project finding #15): the library now owns the
  stop/revert/restore lifecycle. `revert(name, ensure_running=True)` forces a
  start regardless of prior state (used by the CLI below).

**CLI `vmctl snapshot revert` — always ends running:** after the revert it
ensures the VM is started regardless of prior state (suspended → resume, off →
cold boot). Implemented via `revert(..., ensure_running=True)`.

## Flagged ambiguities

**"query" does not imply vmcli.** The earlier shorthand "queries go through vmcli, mutations through vmrun" is wrong as a general rule. The actual convention is:

> Use `vmcli` where it works; fall back to `vmrun` where `vmcli` has no equivalent or is broken.

Both *reads* and *writes* use `vmrun` when vmcli can't serve them:
- `power.state()` reads via vmcli; all power *mutations* use vmrun (vmcli `Power Start` needs `__vmware__`-group/admin).
- `vars.read()`/`vars.write()` both use vmrun (no vmcli variable namespace).
- `network.ip()` reads via vmrun — `vmcli Ethernet query` only returns **adapter config**, never the **guest IP**. This is *not* an exception to the rule; it is the rule.

## network.ip() contract (verified live against `vmctl-unittest`, 2026-06-22)

`network.ip()` → `vmrun -T ws getGuestIPAddress <vmx>` (no `-wait`), returns `{"ip": <str>}`.

| VM state | vmrun exit | `network.ip()` result |
|---|---|---|
| Running, IP assigned | 0 (~0.6s) | `{"ip": "192.168.x.x"}` |
| Running, no IP yet (DHCP pending / no Tools) | 0 | `{"ip": ""}` — empty, does not raise |
| Suspended | 0 | `{"ip": "<stale last-known IP>"}` — see **Stale guest IP** |
| Powered off | 127, `Error: ...not powered on` on **stdout** | raises `VMCtlError` (Runner falls back to stdout for the message) |

- No guest credentials required (host-side `guestInfo` read, unlike `guestEnv`).
- `-wait` (block until an IP exists) is intentionally **not** exposed — it can hang indefinitely; callers poll instead.
- `-snapshot=` is irrelevant to a live query and ignored.

**Resume wedges the VIX channel — `ip()` falls back to `guestinfo.ip`.** After
resuming a *suspended / memory snapshot*, `vmrun getGuestIPAddress` can fail with
`Error: The VMware Tools are not running in the virtual machine` for the **entire
resumed session**, even though Tools are fully up (vmcli `Tools Query` reports
`running: true`, guest ops work) and the guest is networked. `getGuestIPAddress`
gates on a VIX Tools **heartbeat** that the resume leaves wedged; only a guest
**reboot** re-establishes it (restarting the in-guest Tools service does not).
Because `getGuestIPAddress` is effectively `guestinfo.ip` **plus** that heartbeat
gate, `ip()` catches the "not running" failure and falls back to
`vmrun readVariable <vmx> guestVar ip` (host-side `guestinfo.ip`, no heartbeat
gate, no guest creds). The fallback fires **only** on a "not running" message —
"not powered on" still raises, so a genuinely-off VM is never masked. If the
cached `guestinfo.ip` is also empty, the original error is re-raised. (Verified
live against `vmctl-unittest`, 2026-06-25.)

## Guest file copy (`guest.copy_to` / `guest.copy_from`)

`vmcli Guest copyTo/copyFrom` require `<toPath>` to be a full **file** path. Verified live
against `vmctl-unittest` (which now has Tools):

- **Directory destinations are rejected.** Any path that resolves to an existing directory —
  `C:\`, `C:\Users`, bare `C:` — fails with `The object is not a file`. It is a guest-side
  stat, not a path-string check (`C:\Users` with no trailing separator fails too). vmctl
  applies cp/scp semantics for the *explicit* directory forms (trailing `\`/`/`, or bare
  drive root) by appending the source basename; an existing directory given without a
  trailing separator can't be detected locally and instead raises an actionable `VMCtlError`.
- **"The object is not a file" is direction-sensitive.** For `copy_to` the directory is the
  guest **destination**; for `copy_from` it is the guest **source**. `copy_from` to an
  existing *host* directory reports `File already exists`, not `not a file`.
- **Large files fail — `copy_to` is small-files-by-design.** Threshold pinned live:
  **≤60 KB copies fine, ≥64 KB fails** with the opaque `Unknown error` and the file does
  **not** land in the guest; the wall sits in the (60 KB, 64 KB] gray zone. Sub-threshold
  files copy fine to any writable location (incl. `C:\` root — it is *not* a permission
  issue). This is a `vmcli`/Tools limitation, not a vmctl bug. To avoid a silent mid-flight
  failure, `guest.copy_to` **refuses up front** any file larger than
  `_COPY_TO_MAX_BYTES = 60 * 1024` (the highest proven-good size) with an actionable
  `VMCtlError` naming the alternatives; it does not call vmcli in that case. If the host
  file can't be stat'd (e.g. it doesn't exist) the size check is skipped so unrelated errors
  surface unchanged. **For large transfers (e.g. an installer MSI), use an HGFS shared
  folder** (`shares add`) or attach the file as an ISO (`peripheral mount-iso`) instead of
  `guest copy-to`. Large-file transfer is intentionally **not** a feature of this command.
- **No programmatic copy-paste / drag-and-drop.** The VMware GUI host↔guest file
  copy-paste / DnD that "just works" has **no CLI/API/RPC** — it is a GUI-only feature of
  Workstation + `vmtoolsd -n vmusr` riding the CP/DnD backdoor channel, which neither
  `vmcli` nor `vmrun` can drive (open-vm-tools `dndcp` is an unofficial, versioned binary
  GuestRPC protocol; `vmware-rpctool` only does `guestinfo`). Broadcom docs also restrict
  GUI copy-paste to text/images <4 MB, not files between VMs. Do not re-investigate wiring
  it into vmctl. Note: the `clipboard` module (see `vmctl/modules/clipboard.py`) handles the
  **text clipboard** only — it is unrelated to host↔guest file paste.

## File sync via sss (vmctl → sss)

vmctl **depends on** `sss` (embedded as the `./sss` git submodule) and inherits
file-sync by composition — the inverse of the original direction (see
[docs/adr/0003](docs/adr/0003-depend-on-sss-for-file-sync.md) and sss's
[ADR-0004](sss/docs/adr/0004-standalone-no-vm-coupling.md)). sss is
target-agnostic and knows nothing about VMs; vmctl resolves the VM and feeds it a
host + credentials.

The seam is **`vm.sync`** (a `SyncModule`), surfaced on the CLI as **`vmctl sync`**
and **`vmctl push`** only (the full sss verb set is not mirrored):

- `vm.sync.run(sync_optional=False, project_dir=None)` — full profile lifecycle
  (`pre_sync` → sync → `post_sync`). The profile auto-selects from
  `project_dir`'s git remote in `~/.sss/config.json`. **Build-config/arch are not
  vmctl flags** — `{build_cfg}`/`{arch}` substitution comes from the profile's own
  `variables` block; `vmctl sync` exposes only `--optional` and `--project-dir`.
  (`profile`/`base_dir` kwargs exist as a test-injection seam.)
- `vm.sync.push(source, dest)` — ad-hoc, profile-less transfer.

**The IP is read once; sync never boots the VM.** `SyncModule` requires
`PowerState == "on"` and a non-empty `network.ip()`, else it raises an actionable
`VMCtlError` (a suspended VM's IP is **stale**, a powered-off VM has none, and a
just-booted VM has no lease yet — see **Guest IP** / **Stale guest IP** above).
This deliberately does **not** follow the `snapshot revert` lifecycle-ownership
precedent (it does not wait or boot) — the caller readies the guest.
Credentials come from `~/.vmctl/config.json`; if absent, `user`/`password` are
`None` and sss attempts publickey/agent auth. The `import sss` is **lazy** (VM
commands work without sss/paramiko installed) and `SssError` is wrapped as
`VMCtlError` so the CLI surface stays uniform.

### Two file-into-guest paths (do not confuse them)

vmctl now has two ways to put a file in the guest, with **opposite** dest and
size rules — pick by transport availability and file size:

| | `guest copy-to` | `push` (sss / SSH) |
|---|---|---|
| Channel | `vmcli Guest copyTo` (VMware Tools) | SSH / SFTP (needs sshd in guest) |
| Dest arg | a full **file** path — a directory is rejected (`not a file`) | a remote **directory** — file lands at `dest/<basename>` |
| Size | **≤ 60 KB** (refused above; vmcli fails silently) | unbounded |
| Needs | Tools running | OpenSSH server + reachable guest IP |

So a `dest` that works for `push` (a directory) is rejected by `copy-to`, and a
file too big for `copy-to` is exactly what `push` is for. Command help strings
cross-reference each other.

## peripheral devices (unified connect/disconnect)

`peripheral` was 9 verbs (`connect-disk`/`disconnect-disk`/`connect-serial`/
`disconnect-serial`/`connect-usb`/`disconnect-usb`/`eject`/`mount-iso`/`list`).
It is now **4**: `list`, `connect`, `disconnect`, `mount-iso` (see
[docs/adr/0004](docs/adr/0004-unified-peripheral-connect-via-list.md)).

**Device id**:
The *native* identifier of a connectable device, exactly as VMware names it — the
**vmcli label** for disks/serial (`sata0:1`, `nvme0:0`, `serial0`) and the
**named-device string** for USB. The id you see in `list` is the id you type into
`connect`/`disconnect`. There is **no synthesized/friendly id** layered on top.
_Avoid_: "device name" alone (ambiguous between the vmcli label and the USB
named-device string).

**Device type**:
One of `disk`, `cdrom`, `serial`, `usb`. Derived, not typed by the user:
`cdrom` vs `disk` comes from the backing (`cdrom_image` ⇒ `cdrom`). `type` is
what `connect`/`disconnect` dispatch on, and what tells you a device is a `cdrom`
(the only type `mount-iso` targets).

### `list` is the contract backbone

`peripheral.list()` returns a **flat, uniform** inventory — one schema per device:

```
{"vm": "<name>", "devices": [
  {"id": "sata0:1", "type": "cdrom",  "connected": true,  "backing": "foo.iso"},
  {"id": "serial0", "type": "serial", "connected": false, "backing": ...},
  {"id": "<usb name>", "type": "usb", "connected": true,  "backing": ...}
]}
```

This replaces the old grouped `{"disks", "serial"}` (which omitted USB entirely).
Disks/serial come from `vmcli Disk query` / `Serial Query`; **USB entries come
from the `.vmx` named-device config** — there is **no vmcli/vmrun verb that
enumerates connectable *host* hardware**, so "available devices from host" means
"devices the VM knows about and can connect," not a live host-USB probe.

> ⚠️ **Verify live at implementation:** the exact `.vmx` key(s) and the precise
> name string that `vmrun connectNamedDevice` accepts for a USB device, and
> whether a USB device's `connected` state is readable from the `.vmx`. These are
> the only pieces not confirmable from the tools' help alone.

### connect/disconnect resolve id → type via `list`

`connect(id)`/`disconnect(id)` call `self.list()`, find the entry whose `id`
exactly matches, read its `type`, and dispatch to a private helper. The user sees
**one id namespace**; the per-type backend split is hidden.

- **Zero matches** → actionable error listing the valid ids.
- **Id collides across types** → **hard error** asking to disambiguate (no
  priority order baked in). Collision is near-impossible given the distinct
  native namespaces, but the resolver must not silently pick one.
- Resolution + dispatch + error modes live in the **library** (`PeripheralModule`),
  not the CLI, so they are unit-testable without Click. The old public typed
  methods (`connect_disk`, `connect_usb`, …) are **removed** in favour of private
  `_connect_disk`/`_connect_serial`/`_connect_usb` helpers.

### Backend stays split (dispatch by type)

| type | backend | id |
|---|---|---|
| disk / serial / cdrom | `vmcli ... ConnectionControl <label> connect|disconnect` | vmcli label |
| usb | `vmrun connectNamedDevice` / `disconnectNamedDevice <name>` | named-device string |

`vmrun connectNamedDevice` is **not** USB-specific — it connects any named VMX
device — so converging *all* dispatch onto it is tempting. We **kept the split**:
vmcli supplies the `connected` state `list` depends on and likely works while the
VM is off, whereas `connectNamedDevice` typically needs the VM running.
Collapsing onto `connectNamedDevice` is a **logged follow-up to verify live**, not
part of this change.

`mount-iso <id> <iso>` is kept separate because it rebinds the device **backing**
(sets the ISO path) and *then* connects — something plain `connect` cannot do.
`eject` was dropped: it was exactly `disconnect <cdrom-id>`.

## Example dialogue

> **Dev:** The `network` command already lists the NIC — why add `ip`?
> **Expert:** `network list` gives you the **adapter config** — connection type, MAC, the network it's wired to. That's static `.vmx` data; it's there even when the VM is off. It never tells you the **guest IP**.
> **Dev:** So `network ip` asks the guest?
> **Expert:** It reads `guestInfo` through `vmrun`. Running with an address → you get it. Booting but no lease yet → empty string, not an error. Powered off → it raises. And watch out for a **suspended** VM: it hands back the last IP it saw, which may be a lie after resume.
