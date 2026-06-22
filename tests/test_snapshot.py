import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vmctl.modules.snapshot import SnapshotModule

SNAPSHOT_DATA = {
    "currentUID": 1,
    "helperUID": 0,
    "snapshots": [
        {"displayName": "init", "parentUID": 0, "uid": 1},
        {"displayName": "with-tools", "parentUID": 1, "uid": 2},
    ],
}


def make_module(mock_data=SNAPSHOT_DATA):
    runner = MagicMock()
    runner.run_vmcli_json.return_value = mock_data
    runner.run_vmcli_action.return_value = {"success": True}
    return SnapshotModule("fake.vmx", runner)


def test_list_returns_data():
    mod = make_module()
    result = mod.list()
    assert result == SNAPSHOT_DATA


def test_resolve_uid_found():
    mod = make_module()
    uid = mod._resolve_uid("init")
    assert uid == 1


def test_resolve_uid_case_insensitive():
    mod = make_module()
    uid = mod._resolve_uid("WITH-TOOLS")
    assert uid == 2


def test_resolve_uid_not_found():
    mod = make_module()
    with pytest.raises(ValueError, match="not found"):
        mod._resolve_uid("nonexistent")


def test_take_no_options():
    mod = make_module()
    mod.take("mysnap")
    mod._r.run_vmcli_action.assert_called_with("fake.vmx", "Snapshot", "Take", "mysnap")


def test_take_with_memory():
    mod = make_module()
    mod.take("mysnap", memory=True)
    args = mod._r.run_vmcli_action.call_args[0]
    assert "--memory" in args


def test_take_with_description():
    mod = make_module()
    mod.take("mysnap", description="my desc")
    args = mod._r.run_vmcli_action.call_args[0]
    assert "--description" in args
    assert "my desc" in args


def test_revert_resolves_name_to_uid():
    mod = make_module()
    mod.revert("init")
    mod._r.run_vmcli_action.assert_called_with("fake.vmx", "Snapshot", "Revert", "1")


def test_delete_resolves_name_to_uid():
    mod = make_module()
    mod.delete("with-tools")
    mod._r.run_vmcli_action.assert_called_with("fake.vmx", "Snapshot", "Delete", "2")


def test_delete_with_children():
    mod = make_module()
    mod.delete("init", delete_children=True)
    args = mod._r.run_vmcli_action.call_args[0]
    assert "--deleteChildren" in args
