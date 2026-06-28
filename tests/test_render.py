"""Unit tests for ``vmctl.render`` -- the pure ``dict -> str`` CLI rendering
layer (ADR-0007).

This is the primary test target for CLI output: because rendering is pure
(dict-in / string-out, no Click), every output shape is asserted directly here
as plain strings -- table alignment, the ``yes``/``no``/``-`` boolean mapping,
empty-collection header-only output, bare scalar value-reads (including the
empty-string IP), the synthesized mutation confirmation lines, and the curated
``inspect`` summary. The CLI tests then only need a thin "wired to render" check.
"""

from vmctl import render


# --------------------------------------------------------------------------- #
# ps                                                                          #
# --------------------------------------------------------------------------- #


def test_ps_table_aligns_columns():
    out = render.ps([
        {"name": "windows-10-x64", "status": "running"},
        {"name": "box", "status": "stopped"},
    ])
    assert out == (
        "NAME             STATUS\n"
        "windows-10-x64   running\n"
        "box              stopped"
    )


def test_ps_empty_is_header_only():
    assert render.ps([]) == "NAME   STATUS"


# --------------------------------------------------------------------------- #
# snapshot log                                                                #
# --------------------------------------------------------------------------- #


def test_snapshot_log_marks_current_and_shows_description():
    data = {
        "currentUID": 2,
        "snapshots": [
            {"displayName": "init", "uid": 1, "parentUID": 0},
            {"displayName": "with-tools", "uid": 2, "parentUID": 1,
             "description": "tools installed"},
        ],
    }
    out = render.snapshot_log(data)
    assert out == (
        "    NAME         DESCRIPTION\n"
        "    init\n"
        "*   with-tools   tools installed"
    )


def test_snapshot_log_empty_is_header_only():
    assert render.snapshot_log({"snapshots": []}) == "   NAME   DESCRIPTION"


def test_snapshot_log_tolerates_missing_description():
    data = {"currentUID": 1, "snapshots": [{"displayName": "init", "uid": 1}]}
    assert render.snapshot_log(data) == "    NAME   DESCRIPTION\n*   init"


# --------------------------------------------------------------------------- #
# network ls / ip                                                            #
# --------------------------------------------------------------------------- #


def test_network_ls_table():
    data = {"devices": [
        {"label": "ethernet0", "connectionType": "nat",
         "networkName": "VMnet8", "connectionStatus": "connected"},
        {"label": "ethernet1", "connectionType": "bridged",
         "networkName": "", "connectionStatus": "not_connected"},
    ]}
    out = render.network_ls(data)
    assert out == (
        "LABEL       TYPE      NETWORK   CONNECTED\n"
        "ethernet0   nat       VMnet8    yes\n"
        "ethernet1   bridged             no"
    )


def test_network_ls_unknown_connection_is_dash():
    data = {"devices": [{"label": "ethernet0", "connectionType": "nat"}]}
    out = render.network_ls(data)
    assert out.splitlines()[1] == "ethernet0   nat              -"


def test_network_ls_empty_header_only():
    assert render.network_ls({"devices": []}) == "LABEL   TYPE   NETWORK   CONNECTED"


def test_network_ip_is_bare_value():
    assert render.network_ip({"ip": "192.168.1.5"}) == "192.168.1.5"


def test_network_ip_empty_is_blank():
    # An empty IP renders as the empty string (click.echo prints a blank line) --
    # correct for scripts that pipe the value.
    assert render.network_ip({"ip": ""}) == ""


# --------------------------------------------------------------------------- #
# peripheral ls                                                               #
# --------------------------------------------------------------------------- #


def test_peripheral_ls_table_with_tristate_connected():
    data = {"devices": [
        {"id": "sata0:1", "type": "cdrom", "connected": True,
         "backing": r"C:\iso\foo.iso"},
        {"id": "nvme0:0", "type": "disk", "connected": False, "backing": None},
        {"id": "usb_xhci:4", "type": "usb", "connected": None, "backing": "hid"},
    ]}
    out = render.peripheral_ls(data)
    assert out == (
        "ID           TYPE    CONNECTED   BACKING\n"
        r"sata0:1      cdrom   yes         C:\iso\foo.iso" + "\n"
        "nvme0:0      disk    no          -\n"
        "usb_xhci:4   usb     -           hid"
    )


def test_peripheral_ls_empty_header_only():
    assert render.peripheral_ls({"devices": []}) == "ID   TYPE   CONNECTED   BACKING"


# --------------------------------------------------------------------------- #
# shares ls                                                                   #
# --------------------------------------------------------------------------- #


def test_shares_ls_table_maps_truefalse_strings():
    data = {"folders": [
        {"label": "sharedFolder0", "hostPath": r"C:\host",
         "guestName": "share0", "writeAccess": "TRUE", "enabled": "TRUE"},
    ]}
    out = render.shares_ls(data)
    assert out == (
        "LABEL           HOST PATH   GUEST NAME   WRITABLE   ENABLED\n"
        r"sharedFolder0   C:\host     share0       yes        yes"
    )


def test_shares_ls_empty_header_only():
    assert render.shares_ls({"folders": []}) == (
        "LABEL   HOST PATH   GUEST NAME   WRITABLE   ENABLED"
    )


# --------------------------------------------------------------------------- #
# clipboard pull                                                              #
# --------------------------------------------------------------------------- #


def test_clipboard_pull_is_bare_text():
    assert render.clipboard_pull({"text": "hello world"}) == "hello world"


def test_clipboard_pull_empty():
    assert render.clipboard_pull({"text": ""}) == ""


# --------------------------------------------------------------------------- #
# inspect (curated summary)                                                   #
# --------------------------------------------------------------------------- #


def test_inspect_header_and_tables():
    data = {
        "power": {"PowerState": "on"},
        "config": {"guestOS": "windows9-64"},
        "snapshots": {"currentUID": 1, "snapshots": [
            {"displayName": "init", "uid": 1}]},
        "disks": {
            "cdroms": [{"label": "sata0:1", "backingType": "cdrom_image",
                        "backingPathName": r"C:\foo.iso",
                        "connectionStatus": "connected"}],
            "disks": [{"label": "nvme0:0", "backingType": "disk",
                       "backingPathName": "disk.vmdk"}],
            "scsis": [],
        },
        "ethernet": {"devices": [
            {"label": "ethernet0", "connectionType": "nat",
             "connectionStatus": "connected"}]},
        "tools": {"toolsRunningStatus": "running", "toolsVersion": "12345"},
    }
    out = render.inspect(data, "box")
    assert out == (
        "box\n"
        "  power:    on\n"
        "  guest OS: windows9-64\n"
        "\n"
        "snapshots\n"
        "      NAME   DESCRIPTION\n"
        "  *   init\n"
        "\n"
        "disks\n"
        "  ID        TYPE    CONNECTED   BACKING\n"
        r"  sata0:1   cdrom   yes         C:\foo.iso" + "\n"
        "  nvme0:0   disk    yes         disk.vmdk\n"
        "\n"
        "network\n"
        "  LABEL       TYPE   NETWORK   CONNECTED\n"
        "  ethernet0   nat              yes\n"
        "\n"
        "tools\n"
        "  running: running\n"
        "  version: 12345"
    )


def test_inspect_minimal_header_only():
    # No snapshots/disks/network/tools sections when those queries are empty.
    data = {"power": {"PowerState": "off"}, "config": {}}
    assert render.inspect(data, "box") == "box\n  power:    off"


def test_inspect_skips_errored_sections():
    data = {
        "power": {"PowerState": "on"},
        "config": {"guestOS": "ubuntu-64"},
        "tools": {"error": "boom"},
    }
    out = render.inspect(data, "box")
    assert "tools" not in out
    assert out == "box\n  power:    on\n  guest OS: ubuntu-64"


# --------------------------------------------------------------------------- #
# mutation confirmation lines                                                 #
# --------------------------------------------------------------------------- #


def test_confirm_lifecycle_lines():
    assert render.confirm("started", "windows-10-x64") == "started windows-10-x64"
    assert render.confirm("killed", "box") == "killed box"


def test_cloned_names_source_and_dest():
    assert render.cloned("box", r"D:\clones\box2.vmx") == r"cloned box -> D:\clones\box2.vmx"


def test_exec_launched():
    assert render.exec_launched("box") == "launched on box"


def test_copied_both_directions():
    assert render.copied("./f", r"box:C:\dir\f") == r"copied ./f -> box:C:\dir\f"
    assert render.copied(r"box:C:\f", "./out") == r"copied box:C:\f -> ./out"


def test_pushed_and_synced():
    assert render.pushed("./build", r"box:C:\app") == r"pushed ./build -> box:C:\app"
    assert render.synced("box") == "synced box"


def test_auth_set():
    assert render.auth_set("box") == "credentials set for box"


def test_snapshot_mutations():
    assert render.snapshot_committed("box", "s1") == "committed s1 on box"
    assert render.snapshot_reset("box", "s1") == "reset box to s1"
    assert render.snapshot_removed("box", "s1") == "removed s1 from box"


def test_network_mutations():
    assert render.network_connected("box", "ethernet0") == "connected ethernet0 on box"
    assert render.network_disconnected("box", "ethernet0") == "disconnected ethernet0 on box"
    assert render.network_type_set("box", "ethernet0", "nat") == "set ethernet0 type to nat on box"
    assert render.network_name_set("box", "ethernet0", "VMnet8") == "set ethernet0 network to VMnet8 on box"


def test_peripheral_mutations():
    assert render.peripheral_connected("box", "usb_xhci:4") == "connected usb_xhci:4 on box"
    assert render.peripheral_disconnected("box", "usb_xhci:4") == "disconnected usb_xhci:4 on box"
    assert render.iso_mounted("box", "sata0:1", r"C:\foo.iso") == r"mounted C:\foo.iso on sata0:1 of box"


def test_shares_mutations():
    assert render.shares_added("box", "sharedFolder0", r"C:\host") == r"added sharedFolder0 -> C:\host on box"
    assert render.shares_removed("box", "sharedFolder0") == "removed sharedFolder0 from box"
    assert render.shares_updated("box", "sharedFolder0") == "updated sharedFolder0 on box"


def test_clipboard_pushed():
    assert render.clipboard_pushed("box") == "clipboard set on box"
