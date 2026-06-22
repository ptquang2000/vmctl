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

## Example dialogue

> **Dev:** The `network` command already lists the NIC — why add `ip`?
> **Expert:** `network list` gives you the **adapter config** — connection type, MAC, the network it's wired to. That's static `.vmx` data; it's there even when the VM is off. It never tells you the **guest IP**.
> **Dev:** So `network ip` asks the guest?
> **Expert:** It reads `guestInfo` through `vmrun`. Running with an address → you get it. Booting but no lease yet → empty string, not an error. Powered off → it raises. And watch out for a **suspended** VM: it hands back the last IP it saw, which may be a lie after resume.
