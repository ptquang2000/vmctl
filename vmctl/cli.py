import json
import sys

import click

from . import VMCtl, VMCtlError
from .registry import _normalize_path


# Sentinel that replaces a leading ``--`` (the "no VM name here" marker). It
# stands in for the omitted name positional so trailing positionals still bind
# correctly; the resolution layer treats it the same as an absent name.
_AUTO = "\x00__vmctl_auto__"

# Top-level command/group aliases (ADR-0006). Additive ergonomics: each resolves
# to the canonical command but never appears as the canonical name in help.
_ALIASES = {
    "ss": "snapshot",
    "net": "network",
    "dev": "peripheral",
    "in": "inspect",
    "re": "restart",
    "ex": "exec",
}


def _out(data: dict) -> None:
    click.echo(json.dumps(data, indent=2))


def _out_vm(vm, data: dict) -> None:
    """Emit a command result prefixed with the canonical VM name."""
    _out({"vm": vm.name, **data})


def _err(msg: str) -> None:
    click.echo(json.dumps({"error": msg}), err=True)
    sys.exit(1)


def _vmctl() -> VMCtl:
    return VMCtl()


def _resolve(name):
    """Resolve a possibly-omitted VM name to a VM. A ``None`` name or the
    leading-``--`` sentinel triggers auto-selection of the single running VM."""
    explicit = None if (name is None or name == _AUTO) else name
    return _vmctl().resolve(explicit)


class VMCommand(click.Command):
    """A command whose VM-name positional may be dropped via a leading ``--``.

    Click natively consumes ``--`` (end-of-options) and shifts nothing, so we
    intercept the ``--`` that stands in for a dropped name and swap in the
    auto-select sentinel for the name positional. The marker may follow leading
    options (e.g. ``exec --interactive -- cmd.exe …``), so we accept the first
    ``--`` that is preceded only by option tokens. A ``--`` that comes after a
    real positional (an explicit VM name) keeps its conventional end-of-options
    meaning.
    """

    def parse_args(self, ctx, args):
        for i, tok in enumerate(args):
            if tok == "--":
                if all(a.startswith("-") for a in args[:i]):
                    args = list(args[:i]) + [_AUTO] + list(args[i + 1:])
                break
            if not tok.startswith("-"):
                break
        return super().parse_args(ctx, args)


class VMGroup(click.Group):
    command_class = VMCommand


class AliasedGroup(click.Group):
    """Top-level group that resolves command aliases (``ss`` -> ``snapshot``).

    Aliases stay out of ``list_commands`` so ``--help`` shows only canonical
    names, and ``resolve_command`` reports the canonical name so usage/errors
    never echo the alias the user typed."""

    def get_command(self, ctx, name):
        return super().get_command(ctx, _ALIASES.get(name, name))

    def resolve_command(self, ctx, args):
        _, cmd, rest = super().resolve_command(ctx, args)
        return (cmd.name if cmd else None), cmd, rest

    def format_commands(self, ctx, formatter):
        """Render the command list with each command's alias shown inline.

        Aliases are kept out of ``list_commands`` (so they are not listed as
        separate commands), but the help is more discoverable when the canonical
        name carries its short form, e.g. ``snapshot (ss)``.
        """
        canon_to_alias = {canon: alias for alias, canon in _ALIASES.items()}
        rows = []
        for name in self.list_commands(ctx):
            cmd = self.get_command(ctx, name)
            if cmd is None or cmd.hidden:
                continue
            alias = canon_to_alias.get(name)
            label = f"{name} ({alias})" if alias else name
            rows.append((label, cmd.get_short_help_str()))
        if rows:
            with formatter.section("Commands"):
                formatter.write_dl(rows)


@click.group(cls=AliasedGroup)
def cli():
    """Control VMware Workstation VMs from the terminal.

    The command surface mirrors docker/git: `ps`, `start`, `stop`, `kill`,
    `restart`, `exec`, `cp`, `inspect`, plus `snapshot` (git-style log/commit/
    reset/rm) and grouped `network`/`peripheral`/`shares`/`clipboard` commands.
    Every result is JSON on stdout.

    The leading VM name is optional on VM commands: omit it to auto-select the
    single running in-scope VM. When other positionals follow, mark the omitted
    name with a leading `--` (e.g. `snapshot commit -- nightly`). Commands with a
    short alias show it in parentheses below (e.g. `snapshot (ss)`).
    """
    pass


# ---------------------------------------------------------------------------
# ps -- list VMs (docker `ps`)
# ---------------------------------------------------------------------------
def _ps_rows(data: dict, show_all: bool) -> list:
    """Reshape ``list_vms()`` output into docker-style ``ps`` rows.

    Running is derived by matching each discovered .vmx against the set of paths
    ``vmrun list`` reports (normalized for case/separators). Without ``-a`` only
    running VMs are listed; with it every discovered VM appears with its status.
    """
    running = {_normalize_path(p) for p in data.get("running", [])}
    rows = []
    for name, path in sorted(data.get("discovered", {}).items()):
        is_running = _normalize_path(path) in running
        if not show_all and not is_running:
            continue
        rows.append({"name": name, "status": "running" if is_running else "stopped"})
    return rows


@cli.command("ps")
@click.option("-a", "--all", "show_all", is_flag=True,
              help="Include stopped/suspended VMs (default: running only).")
def cmd_ps(show_all):
    """List running VMs (docker `ps`); `-a` includes stopped ones."""
    try:
        _out({"vms": _ps_rows(_vmctl().list_vms(), show_all)})
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# lifecycle (docker: start/stop/kill/restart/pause/unpause/suspend)
# ---------------------------------------------------------------------------
@cli.command("start", cls=VMCommand)
@click.argument("name", required=False)
@click.option("-P", "--paused", is_flag=True,
              help="Boot headless (no Workstation console window). A memory "
                   "snapshot's interactive session is still restored.")
def cmd_start(name, paused):
    """Power on the VM (docker `start`); opens the Workstation console by
    default. Use `-P` to boot headless."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.power.start(paused=paused))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@cli.command("stop", cls=VMCommand)
@click.argument("name", required=False)
def cmd_stop(name):
    """Gracefully shut down the guest. Use `kill` for a hard power-off."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.power.stop(hard=False))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@cli.command("kill", cls=VMCommand)
@click.argument("name", required=False)
def cmd_kill(name):
    """Hard power-off the VM (docker `kill`); pulls the virtual plug."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.power.stop(hard=True))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@cli.command("restart", cls=VMCommand)
@click.argument("name", required=False)
@click.option("-H", "--hard", is_flag=True,
              help="Reset the virtual power button instead of asking the guest "
                   "to reboot gracefully.")
def cmd_restart(name, hard):
    """Reboot the VM (docker `restart`); graceful by default, `-H` forces a hard
    reset."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.power.reset(hard=hard))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@cli.command("pause", cls=VMCommand)
@click.argument("name", required=False)
def cmd_pause(name):
    """Freeze the running VM's CPU (docker `pause`); resume with `unpause`. State
    stays in RAM and the VM keeps reporting as on."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.power.pause())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@cli.command("unpause", cls=VMCommand)
@click.argument("name", required=False)
def cmd_unpause(name):
    """Resume a VM frozen with `pause` (docker `unpause`)."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.power.unpause())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@cli.command("suspend", cls=VMCommand)
@click.argument("name", required=False)
def cmd_suspend(name):
    """Suspend the VM to disk (save state and stop). `start` resumes from where
    it left off; unlike `pause` the VM is no longer running."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.power.suspend())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# clone (VMware term; no docker analog)
# ---------------------------------------------------------------------------
@cli.command("clone", cls=VMCommand)
@click.argument("name", required=False)
@click.argument("dest")
@click.option("-l", "--linked", is_flag=True,
              help="Make a linked clone (fast, shares the source's disk via a "
                   "delta) instead of a full independent copy.")
def cmd_clone(name, dest, linked):
    """Clone the VM to DEST (a new .vmx path). Full copy by default; `-l` for a
    linked clone."""
    try:
        ctl = _vmctl()
        vm = ctl.resolve(None if (name is None or name == _AUTO) else name)
        _out_vm(vm, ctl.clone(vm.name, dest, linked))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# exec (docker `exec`) -- headless by default; -t shell wrap, -i desktop
# ---------------------------------------------------------------------------
_CMD_EXE = r"C:\Windows\System32\cmd.exe"


def _build_exec(program_args, guest_os: str, tty: bool):
    """Translate `exec` tokens + the ``-t`` flag into (program, prog_args).

    With ``-t`` the whole command line is wrapped in the guest shell as a single
    detaching token -- ``cmd.exe /c start "" <cmd>`` on Windows, ``/bin/sh -c
    '<cmd> &'`` elsewhere -- so PATH, builtins, pipes, and multiple arguments all
    work and the launcher exits as soon as the program detaches. Without ``-t``
    the program runs directly via vmcli, which accepts the program plus at most
    one argument token; more than one raises (pointing at ``-t``).
    """
    if tty:
        cmd = " ".join(program_args)
        if "windows" in (guest_os or "").lower():
            return _CMD_EXE, [f'/c start "" {cmd}']
        return "/bin/sh", ["-c", f"{cmd} &"]
    if len(program_args) > 2:
        raise VMCtlError(
            "multiple arguments need a shell; use: "
            f"vmctl exec -t <vm> {' '.join(program_args)}"
        )
    program, *args = program_args
    return program, args


@cli.command("exec", cls=VMCommand,
             context_settings=dict(ignore_unknown_options=True))
@click.argument("name", required=False)
@click.option("-i", "--interactive", is_flag=True,
              help="Run on the guest's interactive desktop (GUI window appears); "
                   "fire-and-forget. Alone it does not search the guest PATH, so "
                   "the program must be an absolute path -- combine with -t to "
                   "PATH-resolve via the shell.")
@click.option("-t", "--tty", is_flag=True,
              help="Run the command line through the guest shell (cmd.exe / sh) "
                   "so PATH, builtins, pipes, and multiple arguments work; the "
                   "program detaches so the call returns at launch.")
@click.argument("program_args", nargs=-1)
def cmd_exec(name, interactive, tty, program_args):
    """Run a command in the guest (docker `exec`); headless by default.

    vmcli `Guest run` only launches -- it never returns the guest program's
    stdout -- so `exec` captures no output. `-t` wraps through the guest shell,
    `-i` launches on the interactive desktop, `-it` combines both (the GUI sweet
    spot: `vmctl exec -it notepad`)."""
    if not program_args:
        _err("program is required")
    try:
        vm = _resolve(name)
        guest_os = vm._guest_os if tty else ""
        program, args = _build_exec(program_args, guest_os, tty)
        # -i launches fire-and-forget (--noWait); headless modes wait on the
        # launch (which is immediate for -t, since the program detaches).
        _out_vm(vm, vm.guest.run(
            program, *args, no_wait=interactive, interactive=interactive))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# cp (docker `vm:path`) -- merges the old copy-to/copy-from
# ---------------------------------------------------------------------------
def _split_vm_path(token: str):
    """Split a ``cp`` token into ``(vm, path)`` or ``(None, host_path)``.

    A token shaped ``vm:path`` carries the VM name before the first colon; a
    leading colon (``:path``) yields an empty VM name (auto-select). A Windows
    drive path -- exactly one alpha char before the colon and a ``\\``/``/``
    right after (``C:\\dir``) -- is a host path, not ``vm:path``."""
    idx = token.find(":")
    if idx == -1:
        return None, token
    if (idx == 1 and token[0].isalpha()
            and idx + 1 < len(token) and token[idx + 1] in "\\/"):
        return None, token
    return token[:idx], token[idx + 1:]


@cli.command("cp")
@click.argument("src")
@click.argument("dst")
@click.option("-o", "--overwrite", is_flag=True,
              help="Overwrite the destination file if it already exists.")
def cmd_cp(src, dst, overwrite):
    """Copy a file between host and guest using docker `vm:path` syntax.

    Direction is inferred from which side carries the `vm:` prefix:
    `vmctl cp ./f myvm:C:\\dir` (host->guest), `vmctl cp myvm:C:\\f ./` (guest->
    host). A leading `:` auto-selects the running VM (`vmctl cp ./f :C:\\dir`).
    Subject to `guest copy-to`'s limits (<=60 KB, file dest); for large files use
    `vmctl push`."""
    try:
        src_vm, src_path = _split_vm_path(src)
        dst_vm, dst_path = _split_vm_path(dst)
        if (src_vm is None) == (dst_vm is None):
            raise VMCtlError(
                "exactly one of SRC and DST must be a guest path written as "
                "'vm:path' (use ':path' to auto-select the running VM); the "
                "other is a host path"
            )
        if dst_vm is not None:
            vm = _resolve(None if dst_vm == "" else dst_vm)
            _out_vm(vm, vm.guest.copy_to(src_path, dst_path, overwrite=overwrite))
        else:
            vm = _resolve(None if src_vm == "" else src_vm)
            _out_vm(vm, vm.guest.copy_from(src_path, dst_path, overwrite=overwrite))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# inspect (absorbs the old `power state` + `parse-vmx`)
# ---------------------------------------------------------------------------
@cli.command("inspect", cls=VMCommand)
@click.argument("name", required=False)
def cmd_inspect(name):
    """Show full VM state: live queries (power, disks, network, …) plus the
    parsed .vmx/.vmsd dump."""
    try:
        vm = _resolve(name)
        data = vm.inspect.inspect()
        data.update(vm.inspect.parse_vmx())
        _out_vm(vm, data)
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------
@cli.group()
def auth():
    """Manage stored guest login credentials (saved in ~/.vmctl/config.json)."""
    pass


@auth.command("set")
@click.argument("name")
@click.option("-u", "--user", required=True, help="Guest login username.")
@click.option("-p", "--password", required=True, help="Guest login password.")
def auth_set(name, user, password):
    """Store the guest username/password for VM NAME. Guest operations (exec, cp,
    sync, …) use these credentials to authenticate into the guest OS."""
    try:
        _vmctl().set_credentials(name, user, password)
        _out({"success": True})
    except Exception as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# snapshot (git: log/commit/reset/rm)
# ---------------------------------------------------------------------------
@cli.group(cls=VMGroup)
def snapshot():
    """Manage VM snapshots (git-style: log/commit/reset/rm)."""
    pass


@snapshot.command("log")
@click.argument("name", required=False)
def snapshot_log(name):
    """List snapshots (git `log`)."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.snapshot.list())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@snapshot.command("commit")
@click.argument("name", required=False)
@click.argument("snap_name")
@click.option("-m", "--message", default=None, help="Snapshot description.")
@click.option("--disk-only", is_flag=True,
              help="Force a fast no-RAM snapshot on a running VM.")
def snapshot_commit(name, snap_name, message, disk_only):
    """Create a snapshot (git `commit`). Captures memory when the VM is running
    (disk-only when off, matching the GUI); `--disk-only` forces no-RAM."""
    try:
        vm = _resolve(name)
        if disk_only:
            memory = False
        else:
            memory = vm.power.state().get("PowerState") == "on"
        _out_vm(vm, vm.snapshot.take(snap_name, memory=memory, description=message))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@snapshot.command("reset")
@click.argument("name", required=False)
@click.argument("snap_name")
def snapshot_reset(name, snap_name):
    """Discard current state and jump back to a snapshot (git `reset --hard`)."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.snapshot.revert(snap_name, ensure_running=True))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@snapshot.command("rm")
@click.argument("name", required=False)
@click.argument("snap_name")
@click.option("-c", "--delete-children", is_flag=True,
              help="Also delete all snapshots descended from this one.")
def snapshot_rm(name, snap_name, delete_children):
    """Delete a snapshot (docker `rm`)."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.snapshot.delete(snap_name, delete_children=delete_children))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# network
# ---------------------------------------------------------------------------
@cli.group(cls=VMGroup)
def network():
    """Inspect and configure the VM's network adapters."""
    pass


@network.command("ls")
@click.argument("name", required=False)
def network_ls(name):
    """List the VM's Ethernet adapters and their static config (connection type,
    MAC, network name)."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.network.list())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@network.command("ip")
@click.argument("name", required=False)
def network_ip(name):
    """Show the running guest's current IP address. Returns an empty string if
    the guest has no IP yet; the VM must be powered on."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.network.ip())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@network.command("connect")
@click.argument("name", required=False)
@click.argument("label")
def network_connect(name, label):
    """Connect (plug in) the network adapter LABEL."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.network.connect(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@network.command("disconnect")
@click.argument("name", required=False)
@click.argument("label")
def network_disconnect(name, label):
    """Disconnect (unplug) the network adapter LABEL."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.network.disconnect(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@network.command("set-type")
@click.argument("name", required=False)
@click.argument("label")
@click.argument("type_")
def network_set_type(name, label, type_):
    """Set adapter LABEL's connection type TYPE_ (e.g. bridged, nat, hostonly)."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.network.set_type(label, type_))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@network.command("set-name")
@click.argument("name", required=False)
@click.argument("label")
@click.argument("network_name")
def network_set_name(name, label, network_name):
    """Set adapter LABEL's virtual network name (e.g. VMnet0)."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.network.set_name(label, network_name))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# peripheral
# ---------------------------------------------------------------------------
@cli.group(cls=VMGroup)
def peripheral():
    """Manage virtual devices: disks, CD/DVD drives, serial ports, USB."""
    pass


@peripheral.command("ls")
@click.argument("name", required=False)
def peripheral_ls(name):
    """List the VM's devices as a flat table of {id, type, connected, backing}.
    Copy an `id` to use with connect/disconnect/mount-iso."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.peripheral.list())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("mount-iso")
@click.argument("name", required=False)
@click.argument("label")
@click.argument("iso_path")
def peripheral_mount_iso(name, label, iso_path):
    """Back the CD/DVD drive LABEL with the ISO at ISO_PATH (host-side path)."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.peripheral.mount_iso(label, iso_path))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("connect")
@click.argument("name", required=False)
@click.argument("device_id")
def peripheral_connect(name, device_id):
    """Connect the device with id DEVICE_ID (copy it from `peripheral ls`).
    The device type is resolved from the id; no type needs to be supplied."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.peripheral.connect(device_id))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("disconnect")
@click.argument("name", required=False)
@click.argument("device_id")
def peripheral_disconnect(name, device_id):
    """Disconnect the device with id DEVICE_ID (copy it from `peripheral ls`).
    The device type is resolved from the id; no type needs to be supplied."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.peripheral.disconnect(device_id))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# shares
# ---------------------------------------------------------------------------
@cli.group(cls=VMGroup)
def shares():
    """Manage HGFS shared folders (host directories visible inside the guest)."""
    pass


@shares.command("ls")
@click.argument("name", required=False)
def shares_ls(name):
    """List the VM's HGFS shared folders with their labels, host paths, and
    flags."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.shares.list())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@shares.command("add")
@click.argument("name", required=False)
@click.argument("host_path")
@click.option("-w", "--writable", is_flag=True,
              help="Allow the guest to write to the share (default: read-only).")
@click.option("-g", "--guest-name", default=None,
              help="Name the share appears under in the guest (default: the "
                   "assigned sharedFolderN label).")
def shares_add(name, host_path, writable, guest_name):
    """Add an HGFS share. Returns the assigned label (e.g. "sharedFolder0");
    pass that label to remove/set-* commands."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.shares.add(host_path, writable=writable, guest_name=guest_name))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@shares.command("remove")
@click.argument("name", required=False)
@click.argument("label")
def shares_remove(name, label):
    """Remove the HGFS share LABEL."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.shares.remove(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@shares.command("set-path")
@click.argument("name", required=False)
@click.argument("label")
@click.argument("host_path")
def shares_set_path(name, label, host_path):
    """Repoint share LABEL at a different host directory HOST_PATH."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.shares.set_path(label, host_path))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@shares.command("set-writable")
@click.argument("name", required=False)
@click.argument("label")
@click.argument("value", type=click.Choice(["true", "false"]))
def shares_set_writable(name, label, value):
    """Set whether the guest may write to share LABEL (VALUE: true|false)."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.shares.set_writable(label, value == "true"))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@shares.command("set-enabled")
@click.argument("name", required=False)
@click.argument("label")
@click.argument("value", type=click.Choice(["true", "false"]))
def shares_set_enabled(name, label, value):
    """Enable or disable share LABEL without removing it (VALUE: true|false)."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.shares.set_enabled(label, value == "true"))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@shares.command("set-guest-name")
@click.argument("name", required=False)
@click.argument("label")
@click.argument("guest_name")
def shares_set_guest_name(name, label, guest_name):
    """Rename how share LABEL appears inside the guest to GUEST_NAME."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.shares.set_guest_name(label, guest_name))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# clipboard
# ---------------------------------------------------------------------------
@cli.group(cls=VMGroup)
def clipboard():
    """Push/pull text between the host and the guest clipboard."""
    pass


@clipboard.command("push")
@click.argument("name", required=False)
@click.argument("text", required=False)
def clipboard_push(name, text):
    """Set the guest clipboard to TEXT. TEXT may be piped on stdin instead; to
    push literal text to the auto-selected VM use `clipboard push -- TEXT`."""
    try:
        if text is None and not sys.stdin.isatty():
            text = sys.stdin.read()
        if not text:
            # Both positionals are optional, so a lone token binds to NAME, not
            # TEXT. Rather than silently reinterpret it (rejected: see the
            # "no silent count-based fill" rule), name what happened and point to
            # the canonical forms. A real name here + no text is the footgun;
            # an omitted/auto-selected name is just an empty push.
            if name is not None and name != _AUTO:
                _err(
                    f"no clipboard text given -- '{name}' was read as the VM name. "
                    f"To push literal text to the auto-selected VM use "
                    f"`clipboard push -- {name}`, pipe it "
                    f"(`... | clipboard push`), or name the VM explicitly "
                    f"(`clipboard push <vm> <text>`)."
                )
            _err("clipboard text is empty (pipe it, or use `clipboard push -- TEXT`)")
        vm = _resolve(name)
        _out_vm(vm, vm.clipboard.push_text(text))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@clipboard.command("pull")
@click.argument("name", required=False)
def clipboard_pull(name):
    """Read the guest clipboard's current text and print it."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.clipboard.pull_text())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# sync / push (file-sync into the running guest, via sss)
# ---------------------------------------------------------------------------
def _log_stderr(msg: str) -> None:
    """Sync/push progress callback: progress on stderr, JSON result on stdout."""
    click.echo(msg, err=True)


@cli.command("sync", cls=VMCommand)
@click.argument("name", required=False)
@click.option("-o", "--optional", is_flag=True,
              help="Include optional (sync_optional) mappings from the profile.")
@click.option("-d", "--project-dir", default=None,
              help="Project dir whose git remote selects the sss profile "
                   "(default: cwd).")
@click.option("-u", "--user", default=None,
              help="Override the SSH login user for this run (pass with "
                   "--password, or neither; never persisted).")
@click.option("-p", "--password", default=None,
              help="Override the SSH login password for this run (pass with "
                   "--user, or neither; never persisted).")
def cmd_sync(name, optional, project_dir, user, password):
    """Sync this project into the running guest over SSH (full sss profile
    lifecycle). The VM must be running with a guest IP; sync never boots it.
    Build-config/arch come from the sss profile's variables, not flags. For an
    ad-hoc one-off transfer use `vmctl push`; for tiny files over VMware Tools
    use `vmctl cp`."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.sync.run(
            sync_optional=optional, project_dir=project_dir, log=_log_stderr,
            user=user, password=password,
        ))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@cli.command("push", cls=VMCommand)
@click.argument("name", required=False)
@click.argument("source")
@click.argument("dest")
@click.option("-u", "--user", default=None,
              help="Override the SSH login user for this run (pass with "
                   "--password, or neither; never persisted).")
@click.option("-p", "--password", default=None,
              help="Override the SSH login password for this run (pass with "
                   "--user, or neither; never persisted).")
def cmd_push(name, source, dest, user, password):
    """Copy SOURCE (file or directory, any size) into the running guest's remote
    directory DEST over SSH/SFTP. Unlike `cp` (VMware Tools, file dest, <=60 KB),
    `push` needs an SSH server in the guest, takes a directory dest, and has no
    size limit. Auto-select with a leading `--`: `vmctl push -- ./build C:\\app`."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.sync.push(source, dest, log=_log_stderr,
                                 user=user, password=password))
    except (VMCtlError, ValueError) as e:
        _err(str(e))
