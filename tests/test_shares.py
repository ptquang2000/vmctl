from unittest.mock import MagicMock, call

import pytest

from vmctl.modules.shares import SharesModule


def make_module(existing_folders=None):
    runner = MagicMock()
    folders = existing_folders or []
    runner.run_vmcli.return_value = '{"folders": %s}' % str(folders).replace("'", '"')
    runner.run_vmcli_action.return_value = {"success": True}
    return SharesModule("fake.vmx", runner)


def _setentry_calls(mod):
    # Each element is a positional-args tuple:
    # ("fake.vmx", "ConfigParams", "SetEntry", key, value)
    return [c[0] for c in mod._r.run_vmcli_action.call_args_list]


def test_add_uses_next_index_zero():
    mod = make_module()
    result = mod.add(r"C:\host\path")
    assert result["label"] == "sharedFolder0"


def test_add_uses_next_index_one():
    mod = make_module(existing_folders=[{"label": "sharedFolder0"}])
    result = mod.add(r"C:\host\path")
    assert result["label"] == "sharedFolder1"


def test_add_sets_required_configparams():
    mod = make_module()
    mod.add(r"C:\host\path")
    calls = _setentry_calls(mod)
    keys_set = [c[3] for c in calls]  # index 3 = key name
    assert "sharedFolder0.present" in keys_set
    assert "sharedFolder0.hostPath" in keys_set
    assert "sharedFolder0.readAccess" in keys_set
    assert "sharedFolder0.writeAccess" in keys_set
    assert "sharedFolder0.guestName" in keys_set
    assert "sharedFolder.maxNum" in keys_set


def test_add_default_not_writable():
    mod = make_module()
    mod.add(r"C:\host\path")
    calls = _setentry_calls(mod)
    write_call = next(c for c in calls if c[3] == "sharedFolder0.writeAccess")
    assert write_call[4] == "FALSE"


def test_add_writable():
    mod = make_module()
    mod.add(r"C:\host\path", writable=True)
    calls = _setentry_calls(mod)
    write_call = next(c for c in calls if c[3] == "sharedFolder0.writeAccess")
    assert write_call[4] == "TRUE"


def test_add_guest_name_defaults_to_label():
    mod = make_module()
    mod.add(r"C:\host\path")
    calls = _setentry_calls(mod)
    gn_call = next(c for c in calls if c[3] == "sharedFolder0.guestName")
    assert gn_call[4] == "sharedFolder0"


def test_add_explicit_guest_name():
    mod = make_module()
    mod.add(r"C:\host\path", guest_name="differentname")
    calls = _setentry_calls(mod)
    gn_call = next(c for c in calls if c[3] == "sharedFolder0.guestName")
    assert gn_call[4] == "differentname"


def test_remove_sets_present_false():
    mod = make_module()
    mod.remove("sharedFolder0")
    calls = _setentry_calls(mod)
    assert any(c[3] == "sharedFolder0.present" and c[4] == "FALSE" for c in calls)


def test_remove_invalid_label():
    mod = make_module()
    with pytest.raises(ValueError, match="valid share label"):
        mod.remove("myshare")


def test_require_index_valid():
    mod = make_module()
    assert mod._require_index("sharedFolder0") == 0
    assert mod._require_index("sharedFolder12") == 12


def test_require_index_invalid():
    mod = make_module()
    with pytest.raises(ValueError):
        mod._require_index("badlabel")
