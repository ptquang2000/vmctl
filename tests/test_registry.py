import os
import tempfile
from pathlib import Path

import pytest

from vmctl.registry import VMRegistry


def make_vmx_tree(tmp_path: Path, names: list) -> Path:
    for name in names:
        vmx = tmp_path / f"{name}.vmx"
        vmx.write_text("displayName = \"test\"")
    return tmp_path


def test_find_exact(tmp_path):
    make_vmx_tree(tmp_path, ["Windows-10-x64", "Ubuntu-20"])
    reg = VMRegistry([str(tmp_path)])
    assert reg.find("windows-10-x64").endswith("Windows-10-x64.vmx")


def test_find_case_insensitive(tmp_path):
    make_vmx_tree(tmp_path, ["Windows-10-x64"])
    reg = VMRegistry([str(tmp_path)])
    assert reg.find("WINDOWS-10-X64").endswith("Windows-10-x64.vmx")


def test_find_partial_match(tmp_path):
    make_vmx_tree(tmp_path, ["Windows-10-x64"])
    reg = VMRegistry([str(tmp_path)])
    assert reg.find("windows-10").endswith("Windows-10-x64.vmx")


def test_find_partial_ambiguous(tmp_path):
    make_vmx_tree(tmp_path, ["Windows-10-x64", "Windows-10-arm"])
    reg = VMRegistry([str(tmp_path)])
    with pytest.raises(ValueError, match="Ambiguous"):
        reg.find("windows-10")


def test_find_not_found(tmp_path):
    make_vmx_tree(tmp_path, ["Windows-10-x64"])
    reg = VMRegistry([str(tmp_path)])
    with pytest.raises(ValueError, match="not found"):
        reg.find("ubuntu")


def test_list_all(tmp_path):
    make_vmx_tree(tmp_path, ["Windows-10-x64", "Ubuntu-20"])
    reg = VMRegistry([str(tmp_path)])
    names = reg.list_all()
    assert "windows-10-x64" in names
    assert "ubuntu-20" in names


def test_missing_scan_root():
    reg = VMRegistry(["/nonexistent/path"])
    assert reg.list_all() == {}


def test_nested_vmx(tmp_path):
    sub = tmp_path / "nested" / "dir"
    sub.mkdir(parents=True)
    (sub / "DeepVM.vmx").write_text("x = 1")
    reg = VMRegistry([str(tmp_path)])
    assert reg.find("deepvm").endswith("DeepVM.vmx")


def test_name_for_path_round_trips(tmp_path):
    make_vmx_tree(tmp_path, ["Windows-10-x64"])
    reg = VMRegistry([str(tmp_path)])
    path = str(tmp_path / "Windows-10-x64.vmx")
    assert reg.name_for_path(path) == "windows-10-x64"


def test_name_for_path_case_and_separator_insensitive(tmp_path):
    make_vmx_tree(tmp_path, ["Windows-10-x64"])
    reg = VMRegistry([str(tmp_path)])
    path = str(tmp_path / "Windows-10-x64.vmx")
    # vmrun list can report a different casing / separator than rglob stored.
    assert reg.name_for_path(path.upper()) == "windows-10-x64"
    assert reg.name_for_path(path.replace("\\", "/")) == "windows-10-x64"


def test_name_for_path_out_of_scope(tmp_path):
    make_vmx_tree(tmp_path, ["Windows-10-x64"])
    reg = VMRegistry([str(tmp_path)])
    assert reg.name_for_path(r"C:\elsewhere\Other.vmx") is None


# --- Aliases ---------------------------------------------------------------


def test_alias_to_stem(tmp_path):
    make_vmx_tree(tmp_path, ["Windows-10-x64"])
    reg = VMRegistry([str(tmp_path)], {"dev": "windows-10-x64"})
    assert reg.find("dev").endswith("Windows-10-x64.vmx")


def test_alias_to_in_scope_path(tmp_path):
    paths = make_vmx_tree(tmp_path, ["Windows-10-x64"])
    target = str(tmp_path / "Windows-10-x64.vmx")
    reg = VMRegistry([str(tmp_path)], {"dev": target})
    assert reg.find("dev") == target


def test_alias_to_out_of_scope_path(tmp_path):
    # An alias may point at a .vmx that discovery never scanned.
    other = tmp_path / "out"
    other.mkdir()
    vmx = other / "db.vmx"
    vmx.write_text('displayName = "test"')
    reg = VMRegistry([], {"db": str(vmx)})
    assert reg.find("db") == str(vmx)


def test_alias_beats_substring(tmp_path):
    make_vmx_tree(tmp_path, ["windows-10-x64", "build-server"])
    # "build" would substring-match build-server, but the alias wins.
    reg = VMRegistry([str(tmp_path)], {"build": "windows-10-x64"})
    assert reg.find("build").endswith("windows-10-x64.vmx")


def test_alias_beats_same_named_stem(tmp_path):
    make_vmx_tree(tmp_path, ["dev", "windows-10-x64"])
    # A stem named "dev" exists, but the alias "dev" redirects elsewhere.
    reg = VMRegistry([str(tmp_path)], {"dev": "windows-10-x64"})
    assert reg.find("dev").endswith("windows-10-x64.vmx")


def test_alias_key_case_insensitive(tmp_path):
    make_vmx_tree(tmp_path, ["Windows-10-x64"])
    reg = VMRegistry([str(tmp_path)], {"Dev": "windows-10-x64"})
    assert reg.find("DEV").endswith("Windows-10-x64.vmx")


def test_alias_missing_path(tmp_path):
    reg = VMRegistry([str(tmp_path)], {"db": r"D:\nope\db.vmx"})
    with pytest.raises(ValueError, match="alias 'db' points to missing .vmx"):
        reg.find("db")


def test_alias_unresolvable_name(tmp_path):
    make_vmx_tree(tmp_path, ["Windows-10-x64"])
    reg = VMRegistry([str(tmp_path)], {"dev": "ghost"})
    with pytest.raises(ValueError, match="alias 'dev' -> 'ghost': VM not found"):
        reg.find("dev")


def test_alias_no_recursion(tmp_path):
    make_vmx_tree(tmp_path, ["Windows-10-x64"])
    # "dev" -> "build" must NOT follow the "build" alias; it's treated as a stem.
    reg = VMRegistry(
        [str(tmp_path)], {"dev": "build", "build": "windows-10-x64"}
    )
    with pytest.raises(ValueError, match="alias 'dev' -> 'build': VM not found"):
        reg.find("dev")
