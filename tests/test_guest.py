from unittest.mock import MagicMock

import pytest

from vmctl.modules.guest import (
    GuestModule,
    _basename,
    _resolve_dest,
)
from vmctl.exceptions import VMCtlError


def make_module():
    runner = MagicMock()
    runner.run_vmcli_action.return_value = {"success": True}
    runner.run_vmrun.return_value = ""
    # Default: nothing pre-exists (dir-source guard False, dest-exists guard
    # False). Individual tests override.
    runner.run_vmrun_test.return_value = False
    return GuestModule("fake.vmx", runner, {"user": "test", "password": "test"})


def _to_path(mod):
    # The guest dest is the last positional in the CopyFileFromHostToGuest argv.
    return mod._r.run_vmrun.call_args.args[-1]


def _from_path_host_dest(mod):
    # The host dest is the last positional in the CopyFileFromGuestToHost argv.
    return mod._r.run_vmrun.call_args.args[-1]


# --- run() arg-ordering tests ---

def test_run_places_flags_before_program():
    # vmcli Guest run treats everything after the program path as a program-arg
    # token, so --noWait/--interactive must precede the program.
    mod = make_module()
    mod.run("cmd.exe", "/c start explorer.exe", interactive=True)
    args = list(mod._r.run_vmcli_action.call_args.args)
    prog_idx = args.index("cmd.exe")
    assert args.index("--noWait") < prog_idx
    assert args.index("--interactive") < prog_idx
    # Program args stay after the program, in order.
    assert args[prog_idx:] == ["cmd.exe", "/c start explorer.exe"]


def test_run_omits_interactive_by_default():
    mod = make_module()
    mod.run("cmd.exe", "/c echo hi")
    args = list(mod._r.run_vmcli_action.call_args.args)
    assert "--interactive" not in args
    assert "--noWait" in args


def test_run_no_wait_false_omits_flag():
    mod = make_module()
    mod.run("cmd.exe", "/c echo hi", no_wait=False)
    args = list(mod._r.run_vmcli_action.call_args.args)
    assert "--noWait" not in args


def test_run_interactive_relative_path_hint():
    # vmcli's interactive launch does not search the guest PATH, so a bare name
    # fails "not found"; surface the absolute-path requirement.
    mod = make_module()
    mod._r.run_vmcli_action.side_effect = VMCtlError(
        "vmcli.exe: A file was not found"
    )
    with pytest.raises(VMCtlError) as exc:
        mod.run("cmd.exe", "/c start .", interactive=True)
    assert "absolute path" in str(exc.value)


def test_run_interactive_absolute_path_passes_error_through():
    # An absolute path that still errors must not get the misleading hint.
    mod = make_module()
    mod._r.run_vmcli_action.side_effect = VMCtlError(
        "vmcli.exe: A file was not found"
    )
    with pytest.raises(VMCtlError) as exc:
        mod.run(r"C:\nope\cmd.exe", "/c x", interactive=True)
    assert "absolute path" not in str(exc.value)


def test_run_non_interactive_not_found_passes_through():
    mod = make_module()
    mod._r.run_vmcli_action.side_effect = VMCtlError("A file was not found")
    with pytest.raises(VMCtlError) as exc:
        mod.run("cmd.exe", "/c x")
    assert "absolute path" not in str(exc.value)


# --- _basename / _resolve_dest unit tests ---

def test_basename_both_separators():
    assert _basename("C:\\a\\b\\file.msi") == "file.msi"
    assert _basename("/tmp/foo/file.msi") == "file.msi"
    assert _basename("C:\\a\\dir\\") == "dir"


@pytest.mark.parametrize("dest,expected", [
    ("C:\\", "C:\\src.msi"),
    ("C:\\tmp\\", "C:\\tmp\\src.msi"),
    ("/tmp/", "/tmp/src.msi"),
    ("C:", "C:\\src.msi"),
    ("C:\\x.msi", "C:\\x.msi"),
    ("C:\\Users", "C:\\Users"),  # no trailing sep -> passthrough (ambiguous)
])
def test_resolve_dest(dest, expected):
    assert _resolve_dest(dest, "D:\\host\\src.msi") == expected


# --- copy_to dest resolution ---

@pytest.mark.parametrize("dest,expected", [
    ("C:\\", "C:\\OpenSSH.msi"),
    ("C:\\tmp\\", "C:\\tmp\\OpenSSH.msi"),
    ("C:", "C:\\OpenSSH.msi"),
    ("C:\\OpenSSH.msi", "C:\\OpenSSH.msi"),
])
def test_copy_to_resolves_dest(dest, expected):
    mod = make_module()
    mod.copy_to("D:\\host\\OpenSSH.msi", dest)
    assert _to_path(mod) == expected


def test_copy_to_emits_vmrun_verb_with_creds_and_order():
    mod = make_module()
    mod.copy_to("D:\\host\\OpenSSH.msi", "C:\\dst.msi", overwrite=True)
    args = list(mod._r.run_vmrun.call_args.args)
    verb_idx = args.index("CopyFileFromHostToGuest")
    # creds precede the verb
    assert args[:verb_idx] == ["-gu", "test", "-gp", "test"]
    # verb <vmx> <host> <guest>, source before dest
    assert args[verb_idx:] == [
        "CopyFileFromHostToGuest", "fake.vmx",
        "D:\\host\\OpenSSH.msi", "C:\\dst.msi",
    ]


def test_copy_to_refuses_directory_source(monkeypatch):
    mod = make_module()
    monkeypatch.setattr("os.path.isdir", lambda p: True)
    with pytest.raises(VMCtlError, match="vmctl push"):
        mod.copy_to("D:\\host\\dir", "C:\\dst\\")
    # Refused up front -- no copy attempted.
    mod._r.run_vmrun.assert_not_called()


def test_copy_to_refuses_existing_dest_without_overwrite():
    mod = make_module()
    mod._r.run_vmrun_test.return_value = True  # dest exists
    with pytest.raises(VMCtlError, match="already exists"):
        mod.copy_to("D:\\host\\OpenSSH.msi", "C:\\dst.msi")
    mod._r.run_vmrun.assert_not_called()
    # The existence pre-flight used fileExistsInGuest against the resolved dest.
    test_args = mod._r.run_vmrun_test.call_args.args
    assert "fileExistsInGuest" in test_args
    assert test_args[-1] == "C:\\dst.msi"


def test_copy_to_overwrite_skips_existence_check():
    mod = make_module()
    mod._r.run_vmrun_test.return_value = True
    mod.copy_to("D:\\host\\OpenSSH.msi", "C:\\dst.msi", overwrite=True)
    mod._r.run_vmrun_test.assert_not_called()
    mod._r.run_vmrun.assert_called_once()


# --- copy_from dest (host) resolution ---

@pytest.mark.parametrize("dest,expected", [
    ("C:\\out\\", "C:\\out\\probe.txt"),
    ("/tmp/", "/tmp/probe.txt"),
    ("C:\\out\\renamed.txt", "C:\\out\\renamed.txt"),
])
def test_copy_from_resolves_host_dest(dest, expected):
    mod = make_module()
    mod.copy_from("C:\\Users\\test\\probe.txt", dest)
    assert _from_path_host_dest(mod) == expected


def test_copy_from_emits_vmrun_verb_with_creds_and_order():
    mod = make_module()
    mod.copy_from("C:\\Users\\test\\probe.txt", "D:\\host\\out.txt")
    args = list(mod._r.run_vmrun.call_args.args)
    verb_idx = args.index("CopyFileFromGuestToHost")
    assert args[:verb_idx] == ["-gu", "test", "-gp", "test"]
    # verb <vmx> <guest> <host>, source before dest
    assert args[verb_idx:] == [
        "CopyFileFromGuestToHost", "fake.vmx",
        "C:\\Users\\test\\probe.txt", "D:\\host\\out.txt",
    ]


def test_copy_from_checks_directory_first_and_refuses():
    mod = make_module()
    mod._r.run_vmrun_test.return_value = True  # guest source is a directory
    with pytest.raises(VMCtlError, match="vmctl push"):
        mod.copy_from("C:\\Users\\test", "D:\\host\\out.txt")
    # directoryExistsInGuest ran against the guest source; no copy attempted.
    test_args = mod._r.run_vmrun_test.call_args.args
    assert "directoryExistsInGuest" in test_args
    assert test_args[-1] == "C:\\Users\\test"
    mod._r.run_vmrun.assert_not_called()


def test_copy_from_proceeds_when_source_not_directory():
    mod = make_module()
    mod._r.run_vmrun_test.return_value = False
    mod.copy_from("C:\\Users\\test\\probe.txt", "D:\\host\\out.txt")
    mod._r.run_vmrun.assert_called_once()


def test_copy_from_refuses_existing_host_dest_without_overwrite(tmp_path):
    mod = make_module()
    existing = tmp_path / "out.txt"
    existing.write_text("old")
    with pytest.raises(VMCtlError, match="already exists"):
        mod.copy_from("C:\\Users\\test\\probe.txt", str(existing))
    mod._r.run_vmrun.assert_not_called()


def test_copy_from_overwrite_allows_existing_host_dest(tmp_path):
    mod = make_module()
    existing = tmp_path / "out.txt"
    existing.write_text("old")
    mod.copy_from("C:\\Users\\test\\probe.txt", str(existing), overwrite=True)
    mod._r.run_vmrun.assert_called_once()
