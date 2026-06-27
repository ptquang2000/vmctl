# vmctl

A JSON-native Python API and command-line wrapper around the VMware Workstation
CLI tools (`vmcli.exe` and `vmrun.exe`). `vmctl` turns the two stock binaries
into a single clean interface: every command returns structured JSON, VMs are
addressed by name (auto-discovered from configured scan roots), and quirks of
the underlying tools are smoothed over so you don't have to remember which
operation needs `vmrun` versus `vmcli`.

## Features

- **JSON everywhere** — every CLI command prints indented JSON; every library
  method returns a `dict`.
- **Name-based VM lookup** — reference VMs by name instead of `.vmx` paths; they
  are discovered by scanning configured roots.
- **Full surface coverage** — power, snapshots, networking, peripherals, guest
  operations, filesystem, VMware Tools, shared folders (HGFS), MKS
  (screenshot/keys/resolution), guest variables, clipboard, and VMX inspection.
- **Quirk handling baked in** — power mutations are routed through `vmrun`
  (which doesn't require the `__vmware__` group), HGFS shares are written via
  `ConfigParams` (the `HGFS Set*` commands are broken), and JSON output with
  stray text prefixes is parsed correctly.

## Requirements

- Windows with **VMware Workstation** installed (provides `vmcli.exe` /
  `vmrun.exe`).
- **Python 3.10+**
- Depends on [`click`](https://click.palletsprojects.com/) (installed
  automatically).

## Installation

vmctl depends on [`sss`](./sss) (SSH file-sync), embedded as a git submodule and
installed editable. Install the submodule **before** vmctl so its dependency is
satisfied:

```bash
git submodule update --init   # fetch ./sss
pip install -e ./sss          # the sync dependency (pulls in paramiko)
pip install -e .              # vmctl itself
```

This installs the `vmctl` console script and the `vmctl` Python package. (`sss`
is imported lazily, so the core VM commands still work if it is absent — only
`vmctl sync` / `vmctl push` require it.)

## Configuration

Configuration lives at `~/.vmctl/config.json`:

```json
{
  "vmware_home": "C:\\Program Files\\VMware\\VMware Workstation",
  "scan_roots": [
    "C:\\Users\\you\\Documents\\Virtual Machines"
  ],
  "credentials": {
    "myvm": { "user": "test", "password": "test" }
  }
}
```

- `scan_roots` — directories scanned for `.vmx` files so VMs can be addressed by
  name.
- `credentials` — per-VM guest credentials (keyed by lowercased VM name) used by
  guest operations. Set them with the CLI:

```bash
vmctl auth set myvm --user test --password test
```

## CLI usage

The CLI is grouped by subsystem. A few examples:

```bash
# Discover and list VMs (running + discovered)
vmctl vm list

# Power
vmctl power start myvm
vmctl power stop myvm --hard
vmctl power state myvm

# Snapshots
vmctl snapshot list myvm
vmctl snapshot take myvm clean --memory --description "fresh install"
vmctl snapshot revert myvm clean        # VM must be powered off
vmctl snapshot delete myvm clean --delete-children

# Guest operations (need credentials configured)
vmctl guest run myvm "cmd.exe" "/c echo hello > C:\\out.txt"
vmctl guest ps myvm
vmctl guest copy-to myvm ./local.txt "C:\\local.txt"
vmctl guest copy-from myvm "C:\\out.txt" ./out.txt

# Guest filesystem
vmctl fs ls myvm "C:\\"
vmctl fs mkdir myvm "C:\\new" --parents

# Shared folders (HGFS) — `add` returns the assigned label
vmctl shares add myvm "C:\\host\\dir" --writable --guest-name shared
vmctl shares list myvm

# VMware Tools
vmctl tools query myvm
vmctl tools install myvm

# Inspect raw VMX config
vmctl inspect myvm
vmctl parse-vmx myvm

# File sync into the running guest over SSH (via sss; VM must be running with a
# guest IP — sync never boots it). Build-config/arch come from the sss profile.
vmctl sync myvm                          # full profile lifecycle
vmctl sync                               # auto-select the single running VM
vmctl sync myvm -u test -p test          # one-off credential override (not saved)
vmctl push myvm ./build "C:\app"         # ad-hoc transfer (any size, dir dest)
vmctl push -- ./build "C:\app"           # auto-select (leading -- before paths)
```

Command groups: `vm`, `auth`, `power`, `snapshot`, `network`, `peripheral`,
`guest`, `fs`, `tools`, `shares`, `mks`, `vars`, `clipboard`, plus the top-level
`inspect`, `parse-vmx`, `sync`, and `push`.

**Short forms (ADR-0005).** Options have short flags (`-m`/`--memory`,
`-H`/`--hard`, `-p`/`--parents`, …) — they are per-command mnemonics, so the
authority is each command's `--help`, not a global letter map.

**Two file-into-guest paths — don't confuse them.** `guest copy-to` uses VMware
Tools, takes a **file** destination, and is capped at ~60 KB; `push` uses
SSH/SFTP, takes a **directory** destination, and has no size limit but needs an
OpenSSH server in the guest. Use `copy-to` for tiny files when only Tools is
available; use `push` for everything larger or when syncing a tree.

## Library usage

```python
from vmctl import VMCtl

ctl = VMCtl()
vm = ctl.get("myvm")

vm.power.start()
print(vm.tools.query())
vm.snapshot.take("clean", memory=True)

# Guest ops use credentials from config
vm.guest.copy_to("./local.txt", r"C:\local.txt")
print(vm.guest.ps())
```

Each `VM` exposes the same subsystems as the CLI groups: `power`, `snapshot`,
`network`, `peripheral`, `guest`, `clipboard`, `fs`, `tools`, `shares`, `mks`,
`vars`, `inspect`, and `sync` (`vm.sync.run()` / `vm.sync.push()`).

## Notes & known constraints

- **Power operations** go through `vmrun` because `vmcli` Power Start/Stop
  requires membership in the `__vmware__` group (or admin); `vmcli` is used only
  for `power state`.
- **Snapshot revert requires the VM to be powered off.**
- **Shared folders** are written directly to the `.vmx` via `ConfigParams`
  because `vmcli HGFS Set*` commands are non-functional. Share labels are
  `sharedFolder0`, `sharedFolder1`, … and assigned automatically on `add`.
- **Guest commands on Windows** should be funneled through `cmd.exe` with a
  single combined `/c …` argument — `vmcli Guest run` accepts only one program
  argument token.

## Development

```bash
# Full suite — unit tests plus the live integration tests
pytest

# Unit tests only (no VMware required)
pytest --ignore=tests/test_integration.py

# Integration tests only (drive a real VM)
pytest tests/test_integration.py
```

The integration tests are no longer opt-in: a plain `pytest` run drives a real
VM. They require a provisioned test VM (`vmctl`) with VMware Tools installed and
a reverting `init` snapshot. See `tests/INTEGRATION.md` for the one-time
provisioning runbook.
