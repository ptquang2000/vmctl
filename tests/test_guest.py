import base64
import os
from unittest.mock import MagicMock

import pytest

from vmctl.modules.guest import (
    GuestModule,
    _POWERSHELL,
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


# --- run_captured (exec -t / -it output capture, ADR-0009) ---

_GUEST_TMP = r"C:\Users\test\AppData\Local\Temp\vmware123"


def make_captured_module(captured=b"", exit_code=0, copy_fails=False):
    """A GuestModule whose runner fakes the capture round-trip.

    ``run_vmrun`` mints the guest temp file, writes ``captured`` bytes to the
    host destination on copy-back (so decode is exercised on real bytes), and
    no-ops the delete. ``run_vmrun_capture`` returns ``(exit_code, "")``. Every
    vmrun verb is appended to ``order`` so orchestration order can be asserted.
    """
    runner = MagicMock()
    order = []
    info = {"host_dest": None}

    def run_vmrun(*args):
        args = list(args)
        if "CreateTempfileInGuest" in args:
            order.append("CreateTempfileInGuest")
            return _GUEST_TMP + "\r\n"
        if "CopyFileFromGuestToHost" in args:
            order.append("CopyFileFromGuestToHost")
            info["host_dest"] = args[-1]
            if copy_fails:
                raise VMCtlError("copy-back failed")
            with open(args[-1], "wb") as f:
                f.write(captured)
            return ""
        if "deleteFileInGuest" in args:
            order.append("deleteFileInGuest")
            return ""
        return ""

    def run_capture(*args):
        order.append("runProgramInGuest")
        return (exit_code, "")

    runner.run_vmrun.side_effect = run_vmrun
    runner.run_vmrun_capture.side_effect = run_capture
    mod = GuestModule("fake.vmx", runner, {"user": "test", "password": "test"})
    return mod, order, info


def _captured_wrapper(mod):
    """Decode the wrapper handed to run_vmrun_capture. Windows -> the decoded
    -EncodedCommand string; Linux -> the /bin/sh -c body."""
    args = list(mod._r.run_vmrun_capture.call_args.args)
    if _POWERSHELL in args:
        return base64.b64decode(args[-1]).decode("utf-16-le")
    return args[-1]


def test_run_captured_windows_builds_powershell_wrapper():
    mod, _, _ = make_captured_module()
    mod.run_captured("notepad foo.txt", "windows9-64")
    args = list(mod._r.run_vmrun_capture.call_args.args)
    assert "runProgramInGuest" in args
    assert _POWERSHELL in args
    assert "-NoProfile" in args
    wrapper = _captured_wrapper(mod)
    # The wrapper merges all streams (*>&1), writes UTF-8 to the minted temp
    # path, and propagates the guest exit code.
    assert "& { notepad foo.txt } *>&1" in wrapper
    assert f"Out-File -FilePath '{_GUEST_TMP}' -Encoding utf8" in wrapper
    assert "exit $LASTEXITCODE" in wrapper


def test_run_captured_linux_builds_sh_wrapper():
    mod, _, _ = make_captured_module()
    mod.run_captured("ls -la", "ubuntu-64")
    args = list(mod._r.run_vmrun_capture.call_args.args)
    assert "/bin/sh" in args
    assert args[-2] == "-c"
    assert args[-1] == f"{{ ls -la; }} > {_GUEST_TMP} 2>&1; exit $?"


def test_run_captured_interactive_adds_flag():
    mod, _, _ = make_captured_module()
    mod.run_captured("notepad", "windows9-64", interactive=True)
    assert "-interactive" in list(mod._r.run_vmrun_capture.call_args.args)


def test_run_captured_non_interactive_omits_flag():
    mod, _, _ = make_captured_module()
    mod.run_captured("notepad", "windows9-64", interactive=False)
    assert "-interactive" not in list(mod._r.run_vmrun_capture.call_args.args)


def test_run_captured_orchestration_order():
    mod, order, _ = make_captured_module()
    mod.run_captured("echo hi", "windows9-64")
    assert order == [
        "CreateTempfileInGuest",
        "runProgramInGuest",
        "CopyFileFromGuestToHost",
        "deleteFileInGuest",
    ]


def test_run_captured_returns_output_and_exit_code():
    mod, _, _ = make_captured_module(captured=b"hello\n", exit_code=0)
    assert mod.run_captured("echo hello", "ubuntu-64") == {
        "output": "hello\n", "exit_code": 0}


def test_run_captured_nonzero_exit_is_data_not_raised():
    mod, _, _ = make_captured_module(captured=b"boom\n", exit_code=42)
    result = mod.run_captured("false", "ubuntu-64")
    assert result == {"output": "boom\n", "exit_code": 42}


def test_run_captured_strips_windows_bom():
    # PS 5.1 Out-File -Encoding utf8 prepends a UTF-8 BOM; it must be stripped.
    mod, _, _ = make_captured_module(captured=b"\xef\xbb\xbfoutput\r\n")
    assert mod.run_captured("x", "windows9-64")["output"] == "output\r\n"


def test_run_captured_decodes_utf8_non_ascii():
    mod, _, _ = make_captured_module(captured="café ☕\n".encode("utf-8"))
    assert mod.run_captured("x", "ubuntu-64")["output"] == "café ☕\n"


def test_run_captured_cleans_host_temp_on_copy_failure():
    mod, order, info = make_captured_module(copy_fails=True)
    with pytest.raises(VMCtlError, match="copy-back failed"):
        mod.run_captured("x", "windows9-64")
    # Host temp file was removed even though copy-back failed...
    assert info["host_dest"] is not None
    assert not os.path.exists(info["host_dest"])
    # ...and the guest temp file delete was still attempted.
    assert "deleteFileInGuest" in order


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
