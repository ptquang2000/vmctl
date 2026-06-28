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
- **docker/git-flavored CLI** — VM lifecycle reads like docker (`ps`, `start`,
  `stop`, `kill`, `exec`, `cp`) and snapshots read like git (`snapshot log`/
  `commit`/`reset`/`rm`); see ADR-0006. Plus networking, peripherals, shared
  folders (HGFS), clipboard, and VMX inspection.
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

The CLI reads like **docker** for VM lifecycle and **git** for snapshots
(ADR-0006). The VM is the container: lifecycle and exec/copy verbs are top-level.

```bash
# List VMs (docker `ps`): running only, or `-a` for all discovered
vmctl ps
vmctl ps -a

# Lifecycle (docker): stop is graceful, kill is a hard power-off
vmctl start myvm
vmctl stop myvm
vmctl kill myvm
vmctl restart myvm
vmctl suspend myvm                       # also pause / unpause
vmctl clone myvm dest                    # VMware full/linked clone (-l)

# Snapshots (git)
vmctl snapshot log myvm
vmctl snapshot commit myvm clean -m "fresh install"   # memory when running,
                                                      # disk-only when off
vmctl snapshot commit myvm clean --disk-only          # fast no-RAM while running
vmctl snapshot reset myvm clean          # discard state, jump back (git reset --hard)
vmctl snapshot rm myvm clean -c          # -c deletes children

# exec (docker): headless by default; no stdout capture (vmcli only launches)
vmctl exec myvm ipconfig                 # headless, program + <=1 arg, run directly
vmctl exec -t myvm "dir C:\\ & echo done"  # -t wraps through the guest shell
                                           # (PATH, builtins, pipes, multi-arg)
vmctl exec -i myvm "C:\\Windows\\System32\\notepad.exe"  # -i: interactive desktop
                                           # (absolute path; --interactive won't
                                           #  search PATH)
vmctl exec -it myvm notepad              # -it: GUI on the desktop, PATH-resolved

# cp (docker vm:path): direction inferred from the vm: side
vmctl cp ./local.txt myvm:C:\\local.txt   # host -> guest
vmctl cp myvm:C:\\out.txt ./out.txt       # guest -> host
vmctl cp ./local.txt :C:\\local.txt       # leading `:` auto-selects the running VM

# Inspect (folds in the old `power state` + `parse-vmx`)
vmctl inspect myvm

# Networking / peripherals / shares (list -> `ls`)
vmctl network ls myvm
vmctl peripheral ls myvm
vmctl shares add myvm "C:\\host\\dir" --writable --guest-name shared
vmctl shares ls myvm

# Clipboard / credentials
vmctl clipboard pull myvm
vmctl auth set myvm --user test --password test

# File sync into the running guest over SSH (via sss; VM must be running with a
# guest IP — sync never boots it). Build-config/arch come from the sss profile.
vmctl sync myvm                          # full profile lifecycle
vmctl sync                               # auto-select the single running VM
vmctl sync myvm -u test -p test          # one-off credential override (not saved)
vmctl push myvm ./build "C:\app"         # ad-hoc transfer (any size, dir dest)
vmctl push -- ./build "C:\app"           # auto-select (leading -- before paths)
```

Top-level verbs: `ps`, `start`, `stop`, `kill`, `restart`, `pause`, `unpause`,
`suspend`, `inspect`, `clone`, `exec`, `cp`, `sync`, `push`. Groups: `snapshot`
(`log`/`commit`/`reset`/`rm`), `network`, `peripheral`, `shares` (all use `ls`),
`clipboard`, `auth`.

**Aliases (ADR-0006).** Longer names have short forms: `ss`=`snapshot`,
`net`=`network`, `dev`=`peripheral`, `in`=`inspect`, `re`=`restart`, `ex`=`exec`.

**Optional VM name (ADR-0001).** The leading VM name may be omitted to
auto-select the single running VM; use a leading `--` when other positionals
follow (`vmctl snapshot commit -- clean -m msg`).

**Short option flags (ADR-0005).** Options have short flags (`-m`/`--message`,
`-H`/`--hard`, …) — per-command mnemonics, so the authority is each command's
`--help`, not a global letter map. `exec` follows docker: `-i`/`-t` combine as
`-it`.

**Two file-into-guest paths — don't confuse them.** `cp` uses VMware Tools,
takes a **file** destination, and is capped at ~60 KB; `push` uses SSH/SFTP,
takes a **directory** destination, and has no size limit but needs an OpenSSH
server in the guest. Use `cp` for tiny files when only Tools is available; use
`push` for everything larger or when syncing a tree.

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
  requires membership in the `__vmware__` group (or admin); `vmcli` supplies the
  power state shown by `inspect`.
- **`snapshot reset` owns the power lifecycle** — `vmcli Snapshot Revert` errors
  while the VM is online, so `reset` hard-stops, reverts, then restarts (always
  ending running). The snapshot name is validated first, so a typo never powers
  the VM off.
- **Shared folders** are written directly to the `.vmx` via `ConfigParams`
  because `vmcli HGFS Set*` commands are non-functional. Share labels are
  `sharedFolder0`, `sharedFolder1`, … and assigned automatically on `add`.
- **`exec` captures no output and launches only.** `vmcli Guest run` cannot
  return the guest program's stdout and accepts the program plus at most one
  argument token, so bare `exec` runs the program directly (absolute path
  safest); `-t` wraps the whole command line through the guest shell
  (`cmd.exe /c start "" …` / `sh -c '… &'`) to get PATH, builtins, pipes, and
  multiple args, detaching the program so the call returns at launch.
- **GUI programs need `exec -i` (or `-it`).** Without `-i` the program runs in
  the non-interactive Session 0, so any window it opens is invisible (the call
  still reports `"success": true` because the process launched). `-i` places it
  on the interactive desktop but does **not** search the guest `PATH`, so the
  program must be an **absolute path**; `-it` adds the shell wrap so a bare name
  (`vmctl exec -it notepad`) resolves via PATH and the window still appears.

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
