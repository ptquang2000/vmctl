# Integration-test setup — `vmctl-unittest` + the `init` snapshot

The live integration suite (`tests/test_integration.py`) drives a real VM
through guest operations. It is gated by `VMCTL_INTEGRATION=1` and skipped
otherwise. To run it you need the throwaway VM **`vmctl-unittest`** with a
snapshot named **`init`**.

This is a *one-time* manual setup. Once the snapshot exists it is reused by every
test run forever — the destructive `revert`/hard-stop fixtures only ever touch
`vmctl-unittest`, never a VM you use for other work.

## Why a manual step is required

VMware Tools cannot be installed into a *bare* guest headlessly. `vmcli Tools
Install` only **inserts** the Tools ISO into the CD drive — it does not launch
the in-guest installer. Every headless guest-control channel
(`vmrun runProgramInGuest`, `vmcli` guest ops, `vmrun installTools`'s
auto-trigger) needs Tools *already present*, so none can bootstrap the first
install. One interactive guest login breaks the chicken-and-egg.

The `init` snapshot is a **suspended, logged-in memory snapshot**: taken
while logged into the desktop, so `revert` + `power start` *resumes* a live
interactive session instead of cold-booting to the login screen. That removes
the login race entirely (no AutoAdminLogon, no auto-logon registry edits). It is
the same pattern the sibling VMs `windows-10-x64` / `windows-11-x64` use to run
these exact fixtures.

## One-time provisioning procedure

VMware binaries live at `C:\Program Files\VMware\VMware Workstation\{vmcli,vmrun}.exe`
(not on PATH). The `vmctl-unittest` VMX is under
`C:\Users\<you>\Documents\Virtual Machines\vmctl-unittest\`.

1. **Start the VM with a GUI console** and log in once as `test` / `test`:

   ```
   "C:\Program Files\VMware\VMware Workstation\vmrun.exe" -T ws start <path-to>\vmctl-unittest.vmx gui
   ```

2. **Install VMware Tools in the guest.** The bundled ISO is already mounted (if
   not, run `vmctl tools install`, which inserts it). Inside the guest, let the
   CD autorun, or run the silent installer from an elevated prompt:

   ```
   D:\setup64.exe /S /v"/qn"
   ```

3. **Reboot the guest** and confirm Tools is running. From the host:

   ```
   "C:\Program Files\VMware\VMware Workstation\vmcli.exe" <path-to>\vmctl-unittest.vmx Tools Query -f json
   ```

   Expect `running: true` and a non-zero `GuestCaps.copyPasteGuestVersion`
   (it reads `0` at the login screen, `> 0` once logged in — this is exactly
   what the fixture readiness gate checks).

4. **Log back into the desktop** so an interactive session is live, then **take
   the snapshot while logged in** (do *not* power off first — the memory state
   is the point):

   ```
   "C:\Program Files\VMware\VMware Workstation\vmrun.exe" -T ws snapshot <path-to>\vmctl-unittest.vmx init
   ```

   `vmctl snapshot take init` works too, as long as the VM is running and
   logged in when you take it.

5. Power the VM off. Each fixture's `revert` requires the VM off/suspended first.

## OpenSSH prerequisite for the sync/push tests

The two sync tests (`test_sync_push_lands_file`,
`test_sync_lifecycle_injected_profile`) transfer files **over SSH** via the `sss`
library — a different channel from the Tools-based `guest copy-to`. They share
the `guest_vm` boot (no extra cycle) but need an **OpenSSH server inside the
`init` snapshot**, reachable as `test` / `test` on **port 22**. This is the same
one-time-snapshot-update model as the Tools provisioning above.

To add it before re-taking the `init` snapshot (step 4), from an elevated guest
PowerShell:

```
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
```

Confirm the host can reach it (`Test-NetConnection <guest-ip> -Port 22`), then
take the `init` snapshot while logged in. Until the snapshot carries a reachable
sshd, the two sync tests **skip** (they probe port 22 first) rather than fail, so
the rest of the suite is unaffected.

## Running the suite

```
VMCTL_INTEGRATION=1 pytest tests/test_integration.py
```

Each domain group (fs / guest / clipboard / vars) reverts to `init`, boots
once, waits for an interactive session via `_wait_for_tools`, runs its tests, and
hard-stops the VM on teardown.

## Readiness gate

`_wait_for_tools` requires **both** `running is True` **and**
`GuestCaps.copyPasteGuestVersion > 0` from a single `tools.query()`. `running`
alone flips true at the login screen, before any interactive desktop exists,
which would race the `--interactive` clipboard test. `copyPasteGuestVersion`
comes from the per-user-session Tools agent (`vmtoolsd -n vmusr`) and is only
non-zero once logged in. `guestCapable` and `dndGuestVersion` are equivalent
signals if the chosen field ever needs revisiting.

## First-run note

The `guest ps` output format (`_parse_ps`) has not been verified against a live
guest; `test_guest_ps` only asserts the `processes` key is present. If the
parser misreads the real format, fix it on the first live run.
