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


def make_module(mock_data=SNAPSHOT_DATA, power_state="off"):
    runner = MagicMock()
    runner.run_vmcli_json.return_value = mock_data
    runner.run_vmcli_action.return_value = {"success": True}
    power = MagicMock()
    power.state.return_value = {"PowerState": power_state}
    return SnapshotModule("fake.vmx", runner, power)


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


def _revert_call_order(mod):
    """Ordered list of the lifecycle calls revert() makes (stop/revert/start)."""
    manager = MagicMock()
    manager.attach_mock(mod._power.stop, "stop")
    manager.attach_mock(mod._power.start, "start")
    manager.attach_mock(mod._r.run_vmcli_action, "revert")
    mod._manager = manager
    return manager


def test_revert_online_stops_reverts_starts():
    mod = make_module(power_state="on")
    manager = _revert_call_order(mod)
    mod.revert("init")
    assert [c[0] for c in manager.mock_calls] == ["stop", "revert", "start"]
    mod._power.stop.assert_called_once_with(hard=True)
    mod._power.start.assert_called_once_with()
    mod._r.run_vmcli_action.assert_called_once_with(
        "fake.vmx", "Snapshot", "Revert", "1"
    )


def test_revert_off_reverts_only():
    mod = make_module(power_state="off")
    mod.revert("init")
    mod._power.stop.assert_not_called()
    mod._power.start.assert_not_called()
    mod._r.run_vmcli_action.assert_called_once_with(
        "fake.vmx", "Snapshot", "Revert", "1"
    )


def test_revert_suspended_reverts_only():
    mod = make_module(power_state="suspended")
    mod.revert("init")
    mod._power.stop.assert_not_called()
    mod._power.start.assert_not_called()


def test_revert_ensure_running_starts_off_vm_without_stop():
    mod = make_module(power_state="off")
    mod.revert("init", ensure_running=True)
    mod._power.stop.assert_not_called()
    mod._power.start.assert_called_once_with()


def test_revert_ensure_running_starts_suspended_vm_without_stop():
    mod = make_module(power_state="suspended")
    mod.revert("init", ensure_running=True)
    mod._power.stop.assert_not_called()
    mod._power.start.assert_called_once_with()


def test_revert_validates_name_before_powering_off():
    mod = make_module(power_state="on")
    with pytest.raises(ValueError, match="not found"):
        mod.revert("nonexistent", ensure_running=True)
    # A typo must never stop the VM or attempt a revert.
    mod._power.stop.assert_not_called()
    mod._power.start.assert_not_called()
    mod._r.run_vmcli_action.assert_not_called()


def test_delete_resolves_name_to_uid():
    mod = make_module()
    mod.delete("with-tools")
    mod._r.run_vmcli_action.assert_called_with("fake.vmx", "Snapshot", "Delete", "2")


def test_delete_with_children():
    mod = make_module()
    mod.delete("init", delete_children=True)
    args = mod._r.run_vmcli_action.call_args[0]
    assert "--deleteChildren" in args
