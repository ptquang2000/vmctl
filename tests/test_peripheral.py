"""Unit tests for PeripheralModule: the flat ``list`` inventory, id->type
resolution + dispatch in ``connect``/``disconnect``, and the error modes.

A fake runner stands in for vmcli/vmrun (the project's established pattern).
``list`` reads disk/serial via vmcli JSON and USB from the real .vmx, so the
module is pointed at a temp .vmx written per test.
"""

import pytest

from vmctl.exceptions import VMCtlError
from vmctl.modules.peripheral import PeripheralModule


# Mirrors the live shape of `vmcli Disk query -f json` against vmctl-unittest:
# cdroms carry connectionStatus + a cdrom_image backing; disks omit
# connectionStatus (a fixed disk is always attached while present).
DISK_QUERY = {
    "cdroms": [
        {
            "label": "sata0:1",
            "backingType": "cdrom_image",
            "backingPathName": r"C:\iso\foo.iso",
            "connectionStatus": "not_connected",
        }
    ],
    "disks": [
        {
            "label": "nvme0:0",
            "backingType": "disk",
            "backingPathName": r"C:\vm\disk.vmdk",
        }
    ],
    "scsis": [],
}

SERIAL_QUERY = {
    "devices": [
        {
            "label": "serial0",
            "backingPathName": r"\\.\pipe\com_1",
            "connectionStatus": "connected",
        }
    ]
}

# A .vmx with one connectable USB device (usb_xhci:4), its bare controllers
# (no colon -> not devices), and a non-present USB device that must be skipped.
VMX_TEXT = """\
.encoding = "UTF-8"
displayName = "Test VM"
usb.present = "TRUE"
usb_xhci.present = "TRUE"
ehci.present = "TRUE"
usb_xhci:4.present = "TRUE"
usb_xhci:4.deviceType = "hid"
usb_xhci:4.port = "4"
usb_xhci:5.present = "FALSE"
usb_xhci:5.deviceType = "host"
"""


@pytest.fixture
def vmx_path(tmp_path):
    p = tmp_path / "test.vmx"
    p.write_text(VMX_TEXT, encoding="utf-8")
    return str(p)


class FakeRunner:
    def __init__(self, disk=DISK_QUERY, serial=SERIAL_QUERY):
        self._disk = disk
        self._serial = serial
        self.vmcli_actions = []
        self.vmrun_calls = []

    def run_vmcli_json(self, vmx, *args):
        if args[0] == "Disk":
            return self._disk
        if args[0] == "Serial":
            return self._serial
        raise AssertionError(f"unexpected vmcli_json: {args}")

    def run_vmcli_action(self, vmx, *args):
        self.vmcli_actions.append(args)
        return {"success": True}

    def run_vmrun(self, *args):
        self.vmrun_calls.append(args)
        return ""


def make_module(vmx_path, **kwargs):
    runner = FakeRunner(**kwargs)
    return PeripheralModule(vmx_path, runner), runner


# --------------------------------------------------------------------------- #
# list shape                                                                  #
# --------------------------------------------------------------------------- #


def test_list_is_flat_devices_array(vmx_path):
    mod, _ = make_module(vmx_path)
    out = mod.list()
    assert set(out) == {"devices"}
    by_id = {d["id"]: d for d in out["devices"]}
    assert set(by_id) == {"sata0:1", "nvme0:0", "serial0", "usb_xhci:4"}
    # every entry has the uniform schema
    for d in out["devices"]:
        assert set(d) == {"id", "type", "connected", "backing"}


def test_list_derives_cdrom_vs_disk_from_backing(vmx_path):
    mod, _ = make_module(vmx_path)
    by_id = {d["id"]: d for d in mod.list()["devices"]}
    assert by_id["sata0:1"]["type"] == "cdrom"
    assert by_id["nvme0:0"]["type"] == "disk"


def test_list_connected_state(vmx_path):
    mod, _ = make_module(vmx_path)
    by_id = {d["id"]: d for d in mod.list()["devices"]}
    assert by_id["sata0:1"]["connected"] is False   # not_connected
    assert by_id["serial0"]["connected"] is True     # connected
    assert by_id["nvme0:0"]["connected"] is True      # fixed disk, no status
    assert by_id["usb_xhci:4"]["connected"] is None   # unknown from .vmx


def test_list_includes_only_present_usb(vmx_path):
    mod, _ = make_module(vmx_path)
    ids = [d["id"] for d in mod.list()["devices"]]
    assert "usb_xhci:4" in ids
    assert "usb_xhci:5" not in ids   # present=FALSE
    # bare controllers (no colon) are not connectable devices
    assert "usb" not in ids and "usb_xhci" not in ids and "ehci" not in ids


# --------------------------------------------------------------------------- #
# connect / disconnect dispatch                                               #
# --------------------------------------------------------------------------- #


def test_connect_disk_routes_to_vmcli(vmx_path):
    mod, runner = make_module(vmx_path)
    assert mod.connect("nvme0:0") == {"success": True}
    assert runner.vmcli_actions == [("Disk", "ConnectionControl", "nvme0:0", "connect")]
    assert runner.vmrun_calls == []


def test_disconnect_cdrom_uses_disk_backend(vmx_path):
    mod, runner = make_module(vmx_path)
    mod.disconnect("sata0:1")
    assert runner.vmcli_actions == [("Disk", "ConnectionControl", "sata0:1", "disconnect")]


def test_connect_serial_routes_to_vmcli(vmx_path):
    mod, runner = make_module(vmx_path)
    mod.connect("serial0")
    assert runner.vmcli_actions == [("Serial", "ConnectionControl", "serial0", "connect")]


def test_connect_usb_routes_to_vmrun(vmx_path):
    mod, runner = make_module(vmx_path)
    assert mod.connect("usb_xhci:4") == {"success": True}
    assert runner.vmrun_calls == [("connectNamedDevice", vmx_path, "usb_xhci:4")]
    assert runner.vmcli_actions == []


def test_disconnect_usb_routes_to_vmrun(vmx_path):
    mod, runner = make_module(vmx_path)
    mod.disconnect("usb_xhci:4")
    assert runner.vmrun_calls == [("disconnectNamedDevice", vmx_path, "usb_xhci:4")]


# --------------------------------------------------------------------------- #
# error modes                                                                 #
# --------------------------------------------------------------------------- #


def test_unknown_id_lists_valid_ids(vmx_path):
    mod, _ = make_module(vmx_path)
    with pytest.raises(VMCtlError) as ei:
        mod.connect("does-not-exist")
    msg = str(ei.value)
    assert "does-not-exist" in msg
    for valid in ("sata0:1", "nvme0:0", "serial0", "usb_xhci:4"):
        assert valid in msg


def test_cross_type_collision_is_hard_error(vmx_path):
    # Force a collision: a serial device sharing an id with a disk.
    disk = {"cdroms": [], "disks": [{"label": "dup", "backingType": "disk"}], "scsis": []}
    serial = {"devices": [{"label": "dup", "connectionStatus": "connected"}]}
    mod, runner = make_module(vmx_path, disk=disk, serial=serial)
    with pytest.raises(VMCtlError) as ei:
        mod.connect("dup")
    assert "ambiguous" in str(ei.value)
    # resolver never silently dispatched
    assert runner.vmcli_actions == [] and runner.vmrun_calls == []


# --------------------------------------------------------------------------- #
# mount-iso                                                                    #
# --------------------------------------------------------------------------- #


def test_mount_iso_rebinds_then_connects(vmx_path):
    mod, runner = make_module(vmx_path)
    mod.mount_iso("sata0:1", r"C:\iso\new.iso")
    assert runner.vmcli_actions == [
        ("Disk", "SetBackingInfo", "sata0:1", "cdrom_image", r"C:\iso\new.iso", "false"),
        ("Disk", "ConnectionControl", "sata0:1", "connect"),
    ]
