import json
import sys

import click

from . import VMCtl, VMCtlError


def _out(data: dict) -> None:
    click.echo(json.dumps(data, indent=2))


def _err(msg: str) -> None:
    click.echo(json.dumps({"error": msg}), err=True)
    sys.exit(1)


def _vmctl() -> VMCtl:
    return VMCtl()


def _vm(name: str):
    return _vmctl().get(name)


@click.group()
def cli():
    pass


# ---------------------------------------------------------------------------
# vm
# ---------------------------------------------------------------------------
@cli.group()
def vm():
    pass


@vm.command("list")
def vm_list():
    try:
        _out(_vmctl().list_vms())
    except VMCtlError as e:
        _err(str(e))


@vm.command("clone")
@click.argument("name")
@click.argument("dest")
@click.option("--linked", is_flag=True)
def vm_clone(name, dest, linked):
    try:
        _out(_vmctl().clone(name, dest, linked))
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
@cli.group()
def power():
    pass


@power.command("start")
@click.argument("name")
@click.option("--paused", is_flag=True)
def power_start(name, paused):
    try:
        _out(_vm(name).power.start(paused=paused))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@power.command("stop")
@click.argument("name")
@click.option("--hard", is_flag=True)
def power_stop(name, hard):
    try:
        _out(_vm(name).power.stop(hard=hard))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@power.command("reset")
@click.argument("name")
@click.option("--hard", is_flag=True)
def power_reset(name, hard):
    try:
        _out(_vm(name).power.reset(hard=hard))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@power.command("suspend")
@click.argument("name")
def power_suspend(name):
    try:
        _out(_vm(name).power.suspend())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@power.command("pause")
@click.argument("name")
def power_pause(name):
    try:
        _out(_vm(name).power.pause())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@power.command("unpause")
@click.argument("name")
def power_unpause(name):
    try:
        _out(_vm(name).power.unpause())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@power.command("state")
@click.argument("name")
def power_state(name):
    try:
        _out(_vm(name).power.state())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------
@cli.group()
def snapshot():
    pass


@snapshot.command("list")
@click.argument("name")
def snapshot_list(name):
    try:
        _out(_vm(name).snapshot.list())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@snapshot.command("take")
@click.argument("name")
@click.argument("snap_name")
@click.option("--memory", is_flag=True)
@click.option("--description", default=None)
def snapshot_take(name, snap_name, memory, description):
    try:
        _out(_vm(name).snapshot.take(snap_name, memory=memory, description=description))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@snapshot.command("revert")
@click.argument("name")
@click.argument("snap_name")
def snapshot_revert(name, snap_name):
    try:
        _out(_vm(name).snapshot.revert(snap_name))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@snapshot.command("delete")
@click.argument("name")
@click.argument("snap_name")
@click.option("--delete-children", is_flag=True)
def snapshot_delete(name, snap_name, delete_children):
    try:
        _out(_vm(name).snapshot.delete(snap_name, delete_children=delete_children))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# network
# ---------------------------------------------------------------------------
@cli.group()
def network():
    pass


@network.command("list")
@click.argument("name")
def network_list(name):
    try:
        _out(_vm(name).network.list())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@network.command("connect")
@click.argument("name")
@click.argument("label")
def network_connect(name, label):
    try:
        _out(_vm(name).network.connect(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@network.command("disconnect")
@click.argument("name")
@click.argument("label")
def network_disconnect(name, label):
    try:
        _out(_vm(name).network.disconnect(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@network.command("set-type")
@click.argument("name")
@click.argument("label")
@click.argument("type_")
def network_set_type(name, label, type_):
    try:
        _out(_vm(name).network.set_type(label, type_))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@network.command("set-name")
@click.argument("name")
@click.argument("label")
@click.argument("network_name")
def network_set_name(name, label, network_name):
    try:
        _out(_vm(name).network.set_name(label, network_name))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# peripheral
# ---------------------------------------------------------------------------
@cli.group()
def peripheral():
    pass


@peripheral.command("list")
@click.argument("name")
def peripheral_list(name):
    try:
        _out(_vm(name).peripheral.list())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("mount-iso")
@click.argument("name")
@click.argument("label")
@click.argument("iso_path")
def peripheral_mount_iso(name, label, iso_path):
    try:
        _out(_vm(name).peripheral.mount_iso(label, iso_path))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("eject")
@click.argument("name")
@click.argument("label")
def peripheral_eject(name, label):
    try:
        _out(_vm(name).peripheral.eject(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("connect-disk")
@click.argument("name")
@click.argument("label")
def peripheral_connect_disk(name, label):
    try:
        _out(_vm(name).peripheral.connect_disk(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("disconnect-disk")
@click.argument("name")
@click.argument("label")
def peripheral_disconnect_disk(name, label):
    try:
        _out(_vm(name).peripheral.disconnect_disk(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("connect-usb")
@click.argument("name")
@click.argument("device_name")
def peripheral_connect_usb(name, device_name):
    try:
        _out(_vm(name).peripheral.connect_usb(device_name))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("disconnect-usb")
@click.argument("name")
@click.argument("device_name")
def peripheral_disconnect_usb(name, device_name):
    try:
        _out(_vm(name).peripheral.disconnect_usb(device_name))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("connect-serial")
@click.argument("name")
@click.argument("label")
def peripheral_connect_serial(name, label):
    try:
        _out(_vm(name).peripheral.connect_serial(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@peripheral.command("disconnect-serial")
@click.argument("name")
@click.argument("label")
def peripheral_disconnect_serial(name, label):
    try:
        _out(_vm(name).peripheral.disconnect_serial(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# guest
# ---------------------------------------------------------------------------
@cli.group()
def guest():
    pass


@guest.command("run")
@click.argument("name")
@click.argument("program_args", nargs=-1)
def guest_run(name, program_args):
    if not program_args:
        _err("program is required")
    try:
        program, *args = program_args
        _out(_vm(name).guest.run(program, *args))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@guest.command("ps")
@click.argument("name")
def guest_ps(name):
    try:
        _out(_vm(name).guest.ps())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@guest.command("kill")
@click.argument("name")
@click.argument("pid", type=int)
def guest_kill(name, pid):
    try:
        _out(_vm(name).guest.kill(pid))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@guest.command("copy-to")
@click.argument("name")
@click.argument("host_path")
@click.argument("guest_path")
@click.option("--overwrite", is_flag=True)
def guest_copy_to(name, host_path, guest_path, overwrite):
    try:
        _out(_vm(name).guest.copy_to(host_path, guest_path, overwrite=overwrite))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@guest.command("copy-from")
@click.argument("name")
@click.argument("guest_path")
@click.argument("host_path")
@click.option("--overwrite", is_flag=True)
def guest_copy_from(name, guest_path, host_path, overwrite):
    try:
        _out(_vm(name).guest.copy_from(guest_path, host_path, overwrite=overwrite))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# fs
# ---------------------------------------------------------------------------
@cli.group()
def fs():
    pass


@fs.command("ls")
@click.argument("name")
@click.argument("path")
@click.option("--regexp", default=None)
@click.option("--max", "max_results", type=int, default=None)
@click.option("--index", type=int, default=None)
def fs_ls(name, path, regexp, max_results, index):
    try:
        _out(_vm(name).fs.ls(path, regexp=regexp, index=index, max=max_results))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@fs.command("env")
@click.argument("name")
def fs_env(name):
    try:
        _out(_vm(name).fs.env())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@fs.command("mkdir")
@click.argument("name")
@click.argument("path")
@click.option("--parents", is_flag=True)
def fs_mkdir(name, path, parents):
    try:
        _out(_vm(name).fs.mkdir(path, parents=parents))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@fs.command("rm")
@click.argument("name")
@click.argument("path")
def fs_rm(name, path):
    try:
        _out(_vm(name).fs.rm(path))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@fs.command("rmdir")
@click.argument("name")
@click.argument("path")
@click.option("--recursive", is_flag=True)
def fs_rmdir(name, path, recursive):
    try:
        _out(_vm(name).fs.rmdir(path, recursive=recursive))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@fs.command("mv")
@click.argument("name")
@click.argument("src")
@click.argument("dst")
@click.option("--overwrite", is_flag=True)
def fs_mv(name, src, dst, overwrite):
    try:
        _out(_vm(name).fs.mv(src, dst, overwrite=overwrite))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@fs.command("mvdir")
@click.argument("name")
@click.argument("src")
@click.argument("dst")
@click.option("--overwrite", is_flag=True)
def fs_mvdir(name, src, dst, overwrite):
    try:
        _out(_vm(name).fs.mvdir(src, dst, overwrite=overwrite))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@fs.command("mktemp")
@click.argument("name")
@click.option("--dir", "as_dir", is_flag=True)
@click.option("--prefix", default="vmctl_", show_default=True)
@click.option("--suffix", default="")
@click.option("--directory", default=None)
def fs_mktemp(name, as_dir, prefix, suffix, directory):
    try:
        if as_dir:
            _out(_vm(name).fs.create_temp_dir(prefix=prefix, suffix=suffix, directory=directory))
        else:
            _out(_vm(name).fs.create_temp_file(prefix=prefix, suffix=suffix, directory=directory))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------
@cli.group()
def tools():
    pass


@tools.command("query")
@click.argument("name")
def tools_query(name):
    try:
        _out(_vm(name).tools.query())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@tools.command("install")
@click.argument("name")
@click.option("--iso-path", default=None)
@click.option("--cmdline", default=None)
def tools_install(name, iso_path, cmdline):
    try:
        _out(_vm(name).tools.install(iso_path=iso_path, cmdline=cmdline))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@tools.command("upgrade")
@click.argument("name")
@click.option("--iso-path", default=None)
@click.option("--cmdline", default=None)
def tools_upgrade(name, iso_path, cmdline):
    try:
        _out(_vm(name).tools.upgrade(iso_path=iso_path, cmdline=cmdline))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# shares
# ---------------------------------------------------------------------------
@cli.group()
def shares():
    pass


@shares.command("list")
@click.argument("name")
def shares_list(name):
    try:
        _out(_vm(name).shares.list())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@shares.command("add")
@click.argument("name")
@click.argument("host_path")
@click.option("--writable", is_flag=True)
@click.option("--guest-name", default=None)
def shares_add(name, host_path, writable, guest_name):
    """Add an HGFS share. Returns the assigned label (e.g. "sharedFolder0");
    pass that label to remove/set-* commands."""
    try:
        _out(_vm(name).shares.add(host_path, writable=writable, guest_name=guest_name))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@shares.command("remove")
@click.argument("name")
@click.argument("label")
def shares_remove(name, label):
    try:
        _out(_vm(name).shares.remove(label))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@shares.command("set-path")
@click.argument("name")
@click.argument("label")
@click.argument("host_path")
def shares_set_path(name, label, host_path):
    try:
        _out(_vm(name).shares.set_path(label, host_path))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@shares.command("set-writable")
@click.argument("name")
@click.argument("label")
@click.argument("value", type=click.Choice(["true", "false"]))
def shares_set_writable(name, label, value):
    try:
        _out(_vm(name).shares.set_writable(label, value == "true"))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@shares.command("set-enabled")
@click.argument("name")
@click.argument("label")
@click.argument("value", type=click.Choice(["true", "false"]))
def shares_set_enabled(name, label, value):
    try:
        _out(_vm(name).shares.set_enabled(label, value == "true"))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@shares.command("set-guest-name")
@click.argument("name")
@click.argument("label")
@click.argument("guest_name")
def shares_set_guest_name(name, label, guest_name):
    try:
        _out(_vm(name).shares.set_guest_name(label, guest_name))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# mks
# ---------------------------------------------------------------------------
@cli.group()
def mks():
    pass


@mks.command("screenshot")
@click.argument("name")
@click.argument("output_path")
def mks_screenshot(name, output_path):
    try:
        _out(_vm(name).mks.screenshot(output_path))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@mks.command("send-key")
@click.argument("name")
@click.argument("hidcode", type=int)
@click.argument("modifier", type=int)
def mks_send_key(name, hidcode, modifier):
    try:
        _out(_vm(name).mks.send_key(hidcode, modifier))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@mks.command("send-keys")
@click.argument("name")
@click.argument("sequence")
def mks_send_keys(name, sequence):
    try:
        _out(_vm(name).mks.send_key_sequence(sequence))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@mks.command("set-resolution")
@click.argument("name")
@click.argument("width", type=int)
@click.argument("height", type=int)
def mks_set_resolution(name, width, height):
    try:
        _out(_vm(name).mks.set_resolution(width, height))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@mks.command("set-displays")
@click.argument("name")
@click.argument("count", type=int)
def mks_set_displays(name, count):
    try:
        _out(_vm(name).mks.set_num_displays(count))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# vars
# ---------------------------------------------------------------------------
@cli.group()
def vars_cmd():
    pass


cli.add_command(vars_cmd, name="vars")


@vars_cmd.command("read")
@click.argument("name")
@click.argument("namespace")
@click.argument("key")
def vars_read(name, namespace, key):
    try:
        _out(_vm(name).vars.read(namespace, key))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@vars_cmd.command("write")
@click.argument("name")
@click.argument("namespace")
@click.argument("key")
@click.argument("value")
def vars_write(name, namespace, key, value):
    try:
        _out(_vm(name).vars.write(namespace, key, value))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# clipboard
# ---------------------------------------------------------------------------
@cli.group()
def clipboard():
    pass


@clipboard.command("push")
@click.argument("name")
@click.argument("text")
def clipboard_push(name, text):
    try:
        _out(_vm(name).clipboard.push_text(text))
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@clipboard.command("pull")
@click.argument("name")
def clipboard_pull(name):
    try:
        _out(_vm(name).clipboard.pull_text())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


# ---------------------------------------------------------------------------
# inspect / parse-vmx
# ---------------------------------------------------------------------------
@cli.command("inspect")
@click.argument("name")
def cmd_inspect(name):
    try:
        _out(_vm(name).inspect.inspect())
    except (VMCtlError, ValueError) as e:
        _err(str(e))


@cli.command("parse-vmx")
@click.argument("name")
def cmd_parse_vmx(name):
    try:
        _out(_vm(name).inspect.parse_vmx())
    except (VMCtlError, ValueError) as e:
        _err(str(e))
