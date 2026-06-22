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
