"""Unit tests for VMCtl's VM-name resolution and running-VM auto-selection.

A real ``Runner``/config is bypassed: VMCtl is built via ``__new__`` with a
real ``VMRegistry`` over a tmp tree and a mocked runner whose ``vmrun list``
output is scripted, so auto-select can be exercised without a live VM.
"""

from unittest.mock import MagicMock

import pytest

from vmctl import VMCtl
from vmctl.registry import VMRegistry


def make_vmx_tree(tmp_path, names):
    paths = {}
    for name in names:
        vmx = tmp_path / f"{name}.vmx"
        vmx.write_text('displayName = "test"')
        paths[name] = str(vmx)
    return paths


def make_ctl(tmp_path, names, running_paths):
    reg = VMRegistry([str(tmp_path)])
    runner = MagicMock()
    listing = f"Total running VMs: {len(running_paths)}\n" + "\n".join(running_paths)
    runner.run_vmrun.return_value = listing
    ctl = VMCtl.__new__(VMCtl)
    ctl._config = {"credentials": {}}
    ctl._registry = reg
    ctl._runner = runner
    return ctl


def test_resolve_explicit_name_canonicalizes(tmp_path):
    make_vmx_tree(tmp_path, ["Windows-10-x64"])
    ctl = make_ctl(tmp_path, ["Windows-10-x64"], running_paths=[])
    vm = ctl.resolve("WINDOWS-10")  # partial + wrong case
    assert vm.name == "windows-10-x64"


def test_auto_select_single_running(tmp_path):
    paths = make_vmx_tree(tmp_path, ["box-a", "box-b"])
    ctl = make_ctl(tmp_path, list(paths), running_paths=[paths["box-a"]])
    vm = ctl.resolve(None)
    assert vm.name == "box-a"


def test_auto_select_zero_running(tmp_path):
    make_vmx_tree(tmp_path, ["box-a"])
    ctl = make_ctl(tmp_path, ["box-a"], running_paths=[])
    with pytest.raises(ValueError, match="no running VM to auto-select"):
        ctl.resolve(None)


def test_auto_select_multiple_running(tmp_path):
    paths = make_vmx_tree(tmp_path, ["box-a", "box-b"])
    ctl = make_ctl(tmp_path, list(paths), running_paths=[paths["box-a"], paths["box-b"]])
    with pytest.raises(ValueError, match="multiple running VMs"):
        ctl.resolve(None)


def test_auto_select_ignores_out_of_scope_running(tmp_path):
    """A running VM outside the registry must not count toward the running tally
    nor be selectable -- it has no registry name or credentials."""
    paths = make_vmx_tree(tmp_path, ["box-a"])
    ctl = make_ctl(
        tmp_path,
        ["box-a"],
        running_paths=[paths["box-a"], r"D:\elsewhere\stranger.vmx"],
    )
    # Two VMs are running, but only one is in scope -> unambiguous auto-select.
    vm = ctl.resolve(None)
    assert vm.name == "box-a"


def test_auto_select_case_insensitive_reverse_map(tmp_path):
    paths = make_vmx_tree(tmp_path, ["Mixed-Case-VM"])
    # vmrun reports an upper-cased path; reverse-map must still match.
    ctl = make_ctl(tmp_path, ["Mixed-Case-VM"], running_paths=[paths["Mixed-Case-VM"].upper()])
    vm = ctl.resolve(None)
    assert vm.name == "mixed-case-vm"
