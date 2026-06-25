import json
import sys

import click

from . import VMCtl, VMCtlError


# Sentinel that replaces a leading ``--`` (the "no VM name here" marker). It
# stands in for the omitted name positional so trailing positionals still bind
# correctly; the resolution layer treats it the same as an absent name.
_AUTO = "\x00__vmctl_auto__"


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
    intercept a *leading* ``--`` here and swap in the auto-select sentinel for
    the name positional. Only the leading ``--`` is special; later ``--`` and
    flags keep their conventional meaning.
    """

    def parse_args(self, ctx, args):
        if args and args[0] == "--":
            args = [_AUTO] + list(args[1:])
        return super().parse_args(ctx, args)


class VMGroup(click.Group):
    command_class = VMCommand


@click.group()
def cli():
    pass


# ---------------------------------------------------------------------------
# vm
# ---------------------------------------------------------------------------
@cli.group(cls=VMGroup)
def vm():
    pass


@vm.command("list")
def vm_list():
    try:
        _out(_vmctl().list_vms())
    except VMCtlError as e:
        _err(str(e))


@vm.command("clone")
@click.argument("name", required=False)
@click.argument("dest")
@click.option("--linked", is_flag=True)
def vm_clone(name, dest, linked):
    try:
        ctl = _vmctl()
        vm = ctl.resolve(None if (name is None or name == _AUTO) else name)
        _out_vm(vm, ctl.clone(vm.name, dest, linked))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------
@cli.group()
def auth():
    pass


@auth.command("set")
@click.argument("name")
@click.option("--user", required=True)
@click.option("--password", required=True)
def auth_set(name, user, password):
    try:
        _vmctl().set_credentials(name, user, password)
        _out({"success": True})
    except Exception as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# power
# ---------------------------------------------------------------------------
@cli.group(cls=VMGroup)
def power():
    pass


@power.command("start")
@click.argument("name", required=False)
@click.option("--paused", is_flag=True)
def power_start(name, paused):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.power.start(paused=paused))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@power.command("stop")
@click.argument("name", required=False)
@click.option("--hard", is_flag=True)
def power_stop(name, hard):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.power.stop(hard=hard))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@power.command("reset")
@click.argument("name", required=False)
@click.option("--hard", is_flag=True)
def power_reset(name, hard):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.power.reset(hard=hard))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@power.command("suspend")
@click.argument("name", required=False)
def power_suspend(name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.power.suspend())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@power.command("pause")
@click.argument("name", required=False)
def power_pause(name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.power.pause())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@power.command("unpause")
@click.argument("name", required=False)
def power_unpause(name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.power.unpause())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@power.command("state")
@click.argument("name", required=False)
def power_state(name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.power.state())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------
@cli.group(cls=VMGroup)
def snapshot():
    pass


@snapshot.command("list")
@click.argument("name", required=False)
def snapshot_list(name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.snapshot.list())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@snapshot.command("take")
@click.argument("name", required=False)
@click.argument("snap_name")
@click.option("--memory", is_flag=True)
@click.option("--description", default=None)
def snapshot_take(name, snap_name, memory, description):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.snapshot.take(snap_name, memory=memory, description=description))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@snapshot.command("revert")
@click.argument("name", required=False)
@click.argument("snap_name")
def snapshot_revert(name, snap_name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.snapshot.revert(snap_name, ensure_running=True))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@snapshot.command("delete")
@click.argument("name", required=False)
@click.argument("snap_name")
@click.option("--delete-children", is_flag=True)
def snapshot_delete(name, snap_name, delete_children):
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
    pass


@network.command("list")
@click.argument("name", required=False)
def network_list(name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.network.list())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@network.command("ip")
@click.argument("name", required=False)
def network_ip(name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.network.ip())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@network.command("connect")
@click.argument("name", required=False)
@click.argument("label")
def network_connect(name, label):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.network.connect(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@network.command("disconnect")
@click.argument("name", required=False)
@click.argument("label")
def network_disconnect(name, label):
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
    pass


@peripheral.command("list")
@click.argument("name", required=False)
def peripheral_list(name):
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
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.peripheral.mount_iso(label, iso_path))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("eject")
@click.argument("name", required=False)
@click.argument("label")
def peripheral_eject(name, label):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.peripheral.eject(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("connect-disk")
@click.argument("name", required=False)
@click.argument("label")
def peripheral_connect_disk(name, label):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.peripheral.connect_disk(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("disconnect-disk")
@click.argument("name", required=False)
@click.argument("label")
def peripheral_disconnect_disk(name, label):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.peripheral.disconnect_disk(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("connect-usb")
@click.argument("name", required=False)
@click.argument("device_name")
def peripheral_connect_usb(name, device_name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.peripheral.connect_usb(device_name))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("disconnect-usb")
@click.argument("name", required=False)
@click.argument("device_name")
def peripheral_disconnect_usb(name, device_name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.peripheral.disconnect_usb(device_name))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("connect-serial")
@click.argument("name", required=False)
@click.argument("label")
def peripheral_connect_serial(name, label):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.peripheral.connect_serial(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("disconnect-serial")
@click.argument("name", required=False)
@click.argument("label")
def peripheral_disconnect_serial(name, label):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.peripheral.disconnect_serial(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# guest
# ---------------------------------------------------------------------------
@cli.group(cls=VMGroup)
def guest():
    pass


@guest.command("run")
@click.argument("name", required=False)
@click.argument("program_args", nargs=-1)
def guest_run(name, program_args):
    if not program_args:
        _err("program is required")
    try:
        program, *args = program_args
        vm = _resolve(name)
        _out_vm(vm, vm.guest.run(program, *args))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@guest.command("ps")
@click.argument("name", required=False)
def guest_ps(name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.guest.ps())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@guest.command("kill")
@click.argument("name", required=False)
@click.argument("pid", type=int)
def guest_kill(name, pid):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.guest.kill(pid))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@guest.command("copy-to")
@click.argument("name", required=False)
@click.argument("host_path")
@click.argument("guest_path")
@click.option("--overwrite", is_flag=True)
def guest_copy_to(name, host_path, guest_path, overwrite):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.guest.copy_to(host_path, guest_path, overwrite=overwrite))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@guest.command("copy-from")
@click.argument("name", required=False)
@click.argument("guest_path")
@click.argument("host_path")
@click.option("--overwrite", is_flag=True)
def guest_copy_from(name, guest_path, host_path, overwrite):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.guest.copy_from(guest_path, host_path, overwrite=overwrite))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# fs
# ---------------------------------------------------------------------------
@cli.group(cls=VMGroup)
def fs():
    pass


@fs.command("ls")
@click.argument("name", required=False)
@click.argument("path")
@click.option("--regexp", default=None)
@click.option("--max", "max_results", type=int, default=None)
@click.option("--index", type=int, default=None)
def fs_ls(name, path, regexp, max_results, index):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.fs.ls(path, regexp=regexp, index=index, max=max_results))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@fs.command("env")
@click.argument("name", required=False)
def fs_env(name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.fs.env())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@fs.command("mkdir")
@click.argument("name", required=False)
@click.argument("path")
@click.option("--parents", is_flag=True)
def fs_mkdir(name, path, parents):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.fs.mkdir(path, parents=parents))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@fs.command("rm")
@click.argument("name", required=False)
@click.argument("path")
def fs_rm(name, path):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.fs.rm(path))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@fs.command("rmdir")
@click.argument("name", required=False)
@click.argument("path")
@click.option("--recursive", is_flag=True)
def fs_rmdir(name, path, recursive):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.fs.rmdir(path, recursive=recursive))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@fs.command("mv")
@click.argument("name", required=False)
@click.argument("src")
@click.argument("dst")
@click.option("--overwrite", is_flag=True)
def fs_mv(name, src, dst, overwrite):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.fs.mv(src, dst, overwrite=overwrite))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@fs.command("mvdir")
@click.argument("name", required=False)
@click.argument("src")
@click.argument("dst")
@click.option("--overwrite", is_flag=True)
def fs_mvdir(name, src, dst, overwrite):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.fs.mvdir(src, dst, overwrite=overwrite))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@fs.command("mktemp")
@click.argument("name", required=False)
@click.option("--dir", "as_dir", is_flag=True)
@click.option("--prefix", default="vmctl_", show_default=True)
@click.option("--suffix", default="")
@click.option("--directory", default=None)
def fs_mktemp(name, as_dir, prefix, suffix, directory):
    try:
        vm = _resolve(name)
        if as_dir:
            _out_vm(vm, vm.fs.create_temp_dir(prefix=prefix, suffix=suffix, directory=directory))
        else:
            _out_vm(vm, vm.fs.create_temp_file(prefix=prefix, suffix=suffix, directory=directory))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------
@cli.group(cls=VMGroup)
def tools():
    pass


@tools.command("query")
@click.argument("name", required=False)
def tools_query(name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.tools.query())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@tools.command("install")
@click.argument("name", required=False)
@click.option("--iso-path", default=None)
@click.option("--cmdline", default=None)
def tools_install(name, iso_path, cmdline):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.tools.install(iso_path=iso_path, cmdline=cmdline))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@tools.command("upgrade")
@click.argument("name", required=False)
@click.option("--iso-path", default=None)
@click.option("--cmdline", default=None)
def tools_upgrade(name, iso_path, cmdline):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.tools.upgrade(iso_path=iso_path, cmdline=cmdline))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# shares
# ---------------------------------------------------------------------------
@cli.group(cls=VMGroup)
def shares():
    pass


@shares.command("list")
@click.argument("name", required=False)
def shares_list(name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.shares.list())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@shares.command("add")
@click.argument("name", required=False)
@click.argument("host_path")
@click.option("--writable", is_flag=True)
@click.option("--guest-name", default=None)
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
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.shares.set_guest_name(label, guest_name))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# mks
# ---------------------------------------------------------------------------
@cli.group(cls=VMGroup)
def mks():
    pass


@mks.command("screenshot")
@click.argument("name", required=False)
@click.argument("output_path")
def mks_screenshot(name, output_path):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.mks.screenshot(output_path))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@mks.command("send-key")
@click.argument("name", required=False)
@click.argument("hidcode", type=int)
@click.argument("modifier", type=int)
def mks_send_key(name, hidcode, modifier):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.mks.send_key(hidcode, modifier))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@mks.command("send-keys")
@click.argument("name", required=False)
@click.argument("sequence")
def mks_send_keys(name, sequence):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.mks.send_key_sequence(sequence))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@mks.command("set-resolution")
@click.argument("name", required=False)
@click.argument("width", type=int)
@click.argument("height", type=int)
def mks_set_resolution(name, width, height):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.mks.set_resolution(width, height))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@mks.command("set-displays")
@click.argument("name", required=False)
@click.argument("count", type=int)
def mks_set_displays(name, count):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.mks.set_num_displays(count))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# vars
# ---------------------------------------------------------------------------
@cli.group(cls=VMGroup)
def vars_cmd():
    pass


cli.add_command(vars_cmd, name="vars")


@vars_cmd.command("read")
@click.argument("name", required=False)
@click.argument("namespace")
@click.argument("key")
def vars_read(name, namespace, key):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.vars.read(namespace, key))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@vars_cmd.command("write")
@click.argument("name", required=False)
@click.argument("namespace")
@click.argument("key")
@click.argument("value")
def vars_write(name, namespace, key, value):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.vars.write(namespace, key, value))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# clipboard
# ---------------------------------------------------------------------------
@cli.group(cls=VMGroup)
def clipboard():
    pass


@clipboard.command("push")
@click.argument("name", required=False)
@click.argument("text")
def clipboard_push(name, text):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.clipboard.push_text(text))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@clipboard.command("pull")
@click.argument("name", required=False)
def clipboard_pull(name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.clipboard.pull_text())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# inspect / parse-vmx
# ---------------------------------------------------------------------------
@cli.command("inspect", cls=VMCommand)
@click.argument("name", required=False)
def cmd_inspect(name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.inspect.inspect())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@cli.command("parse-vmx", cls=VMCommand)
@click.argument("name", required=False)
def cmd_parse_vmx(name):
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.inspect.parse_vmx())
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
@click.option("--optional", is_flag=True,
              help="Include optional (sync_optional) mappings from the profile.")
@click.option("--project-dir", default=None,
              help="Project dir whose git remote selects the sss profile "
                   "(default: cwd).")
def cmd_sync(name, optional, project_dir):
    """Sync this project into the running guest over SSH (full sss profile
    lifecycle). The VM must be running with a guest IP; sync never boots it.
    Build-config/arch come from the sss profile's variables, not flags. For an
    ad-hoc one-off transfer use `vmctl push`; for tiny files over VMware Tools
    use `vmctl guest copy-to`."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.sync.run(
            sync_optional=optional, project_dir=project_dir, log=_log_stderr,
        ))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@cli.command("push", cls=VMCommand)
@click.argument("name", required=False)
@click.argument("source")
@click.argument("dest")
def cmd_push(name, source, dest):
    """Copy SOURCE (file or directory, any size) into the running guest's remote
    directory DEST over SSH/SFTP. Unlike `guest copy-to` (VMware Tools, file
    dest, <=60 KB), `push` needs an SSH server in the guest, takes a directory
    dest, and has no size limit. Auto-select with a leading `--`:
    `vmctl push -- ./build C:\\app`."""
    try:
        vm = _resolve(name)
        _out_vm(vm, vm.sync.push(source, dest, log=_log_stderr))
    except (VMCtlError, ValueError) as e:
        _err(str(e))
