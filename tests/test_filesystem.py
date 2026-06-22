from unittest.mock import MagicMock

import pytest

from vmctl.modules.filesystem import FilesystemModule, _parse_ls, _parse_env


def make_module():
    runner = MagicMock()
    runner.run_vmcli.return_value = ""
    runner.run_vmcli_action.return_value = {"success": True}
    return FilesystemModule("fake.vmx", runner, {"user": "u", "password": "p"})


# --- parser unit tests ---

# vmcli Guest ls emits a fixed columnar table (header + per-entry rows, with
# leading "."/".." self entries). Samples below mirror live-captured output.
_LS_HEADER = (
    "Perms      Fl Owner Group File size      Mod time   "
    "Create Time  Access Time          Filename          Symlink"
)
_LS_DOT = "0           1     0     0         0  Jun 22 08:52  Jun 22 08:52  Jun 22 08:52                .                 "
_LS_DOTDOT = "0           5     0     0         0  Jun 22 08:52  Dec 07 16:03  Jun 22 08:52               ..                 "


def _ls_row(name):
    return f"777         1     0     0       123  Jun 22 08:52  Jun 22 08:52  Jun 22 08:52         {name}"


def test_parse_ls_basic():
    text = "\n".join([_LS_HEADER, _LS_DOT, _LS_DOTDOT,
                       _ls_row("file1.txt"), _ls_row("file2.txt"), _ls_row("subdir")]) + "\n"
    result = _parse_ls(text)
    assert result == {"entries": ["file1.txt", "file2.txt", "subdir"]}


def test_parse_ls_empty():
    result = _parse_ls("")
    assert result == {"entries": []}


def test_parse_ls_empty_dir_drops_self_entries():
    # An empty guest directory still reports the header and "."/".." rows;
    # those must not become phantom entries (live B#2 defect).
    text = "\n".join([_LS_HEADER, _LS_DOT, _LS_DOTDOT]) + "\n"
    assert _parse_ls(text) == {"entries": []}


def test_parse_env_basic():
    text = "PATH=C:\\Windows\\System32\nUSER=admin\n"
    result = _parse_env(text)
    assert result["env"]["PATH"] == "C:\\Windows\\System32"
    assert result["env"]["USER"] == "admin"


def test_parse_env_empty():
    result = _parse_env("")
    assert result == {"env": {}}


def test_parse_env_value_with_equals():
    result = _parse_env("KEY=val=ue\n")
    assert result["env"]["KEY"] == "val=ue"


# --- passthrough arg tests ---

def test_ls_passes_path():
    mod = make_module()
    mod.ls(r"C:\Users")
    args = mod._r.run_vmcli.call_args[0]
    assert r"C:\Users" in args


def test_ls_with_regexp():
    mod = make_module()
    mod.ls(r"C:\Users", regexp="*.txt")
    args = mod._r.run_vmcli.call_args[0]
    assert "--regexp" in args
    assert "*.txt" in args


def test_ls_with_pagination():
    mod = make_module()
    mod.ls(r"C:\Users", index=10, max=50)
    args = mod._r.run_vmcli.call_args[0]
    assert "--index" in args
    assert "10" in args
    assert "--max" in args
    assert "50" in args


def test_mkdir_without_parents():
    mod = make_module()
    mod.mkdir(r"C:\test")
    args = mod._r.run_vmcli_action.call_args[0]
    assert "--parent" not in args
    assert r"C:\test" in args


def test_mkdir_with_parents():
    mod = make_module()
    mod.mkdir(r"C:\test\deep", parents=True)
    args = mod._r.run_vmcli_action.call_args[0]
    assert "--parent" in args


def test_rmdir_default_not_recursive():
    mod = make_module()
    mod.rmdir(r"C:\test")
    args = mod._r.run_vmcli_action.call_args[0]
    assert "--recursive" not in args


def test_rmdir_recursive():
    mod = make_module()
    mod.rmdir(r"C:\test", recursive=True)
    args = mod._r.run_vmcli_action.call_args[0]
    assert "--recursive" in args


def test_credentials_injected_in_ls():
    mod = make_module()
    mod.ls(r"C:\Users")
    args = mod._r.run_vmcli.call_args[0]
    assert "--username" in args
    assert "u" in args
    assert "--password" in args
    assert "p" in args
