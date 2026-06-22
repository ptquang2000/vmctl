from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vmctl.modules.inspect import InspectModule

FIXTURES = Path(__file__).parent / "fixtures"


def make_module(side_effect=None):
    runner = MagicMock()
    if side_effect:
        runner.run_vmcli_json.side_effect = side_effect
    else:
        runner.run_vmcli_json.return_value = {"ok": True}
    return InspectModule(
        str(FIXTURES / "test_vm.vmx"),
        runner,
    )


def test_inspect_returns_all_keys():
    mod = make_module()
    result = mod.inspect()
    expected_keys = {
        "power", "chipset", "snapshots", "disks", "ethernet",
        "serial", "mks", "shares", "tools", "config",
    }
    assert expected_keys == set(result.keys())


def test_inspect_tolerates_failures():
    from vmctl.exceptions import VMCtlError
    mod = make_module(side_effect=VMCtlError("boom"))
    result = mod.inspect()
    for v in result.values():
        assert "error" in v


def test_parse_vmx_reads_vmx_and_vmsd():
    mod = make_module()
    result = mod.parse_vmx()
    assert "vmx" in result
    assert "vmsd" in result
    assert result["vmx"]["displayName"] == "Test VM"
    assert result["vmsd"]["snapshot0.displayName"] == "init"


def test_parse_vmx_missing_vmsd(tmp_path):
    vmx = tmp_path / "solo.vmx"
    vmx.write_text('displayName = "Solo"\n')
    runner = MagicMock()
    mod = InspectModule(str(vmx), runner)
    result = mod.parse_vmx()
    assert result["vmsd"] == {}
