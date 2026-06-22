from unittest.mock import MagicMock

import pytest

from vmctl.modules.guest import (
    GuestModule,
    _basename,
    _resolve_dest,
    _COPY_TO_MAX_BYTES,
)
from vmctl.exceptions import VMCtlError


def make_module():
    runner = MagicMock()
    runner.run_vmcli_action.return_value = {"success": True}
    return GuestModule("fake.vmx", runner, {"user": "test", "password": "test"})


def _to_path(mod):
    # The guest dest is the last positional in the copyTo arg list.
    return mod._r.run_vmcli_action.call_args.args[-1]


def _from_path_host_dest(mod):
    # The host dest is the last positional in the copyFrom arg list.
    return mod._r.run_vmcli_action.call_args.args[-1]


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


def test_copy_to_overwrite_flag_and_order():
    mod = make_module()
    mod.copy_to("D:\\host\\OpenSSH.msi", "C:\\dst.msi", overwrite=True)
    args = mod._r.run_vmcli_action.call_args.args
    assert args[0] == "fake.vmx"
    assert "--overwrite" in args
    # source precedes dest
    assert args.index("D:\\host\\OpenSSH.msi") < args.index("C:\\dst.msi")


def test_copy_to_translates_not_a_file():
    mod = make_module()
    mod._r.run_vmcli_action.side_effect = VMCtlError(
        "vmcli.exe: The object is not a file"
    )
    with pytest.raises(VMCtlError, match="guest destination 'C:\\\\Users' is a directory"):
        mod.copy_to("D:\\host\\OpenSSH.msi", "C:\\Users")


def test_copy_to_other_errors_propagate():
    mod = make_module()
    mod._r.run_vmcli_action.side_effect = VMCtlError("Unknown error")
    with pytest.raises(VMCtlError, match="Unknown error"):
        mod.copy_to("D:\\host\\OpenSSH.msi", "C:\\Users\\test\\x.msi")


def test_copy_to_rejects_large_file(tmp_path):
    mod = make_module()
    big = tmp_path / "big.msi"
    big.write_bytes(b"\0" * (_COPY_TO_MAX_BYTES + 1))
    with pytest.raises(VMCtlError, match="too large for 'guest copy-to'"):
        mod.copy_to(str(big), "C:\\big.msi")
    # Refused up front -- vmcli must not have been invoked.
    mod._r.run_vmcli_action.assert_not_called()


def test_copy_to_allows_at_limit_file(tmp_path):
    mod = make_module()
    ok = tmp_path / "ok.txt"
    ok.write_bytes(b"\0" * _COPY_TO_MAX_BYTES)
    mod.copy_to(str(ok), "C:\\ok.txt")
    mod._r.run_vmcli_action.assert_called_once()


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


def test_copy_from_translates_not_a_file_as_source():
    mod = make_module()
    mod._r.run_vmcli_action.side_effect = VMCtlError(
        "vmcli.exe: The object is not a file"
    )
    with pytest.raises(VMCtlError, match="guest source 'C:\\\\Users\\\\test' is a directory"):
        mod.copy_from("C:\\Users\\test", "D:\\host\\out.txt")
