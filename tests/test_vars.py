from unittest.mock import MagicMock

import pytest

from vmctl.modules.vars import VarsModule


def make_module():
    runner = MagicMock()
    runner.run_vmrun.return_value = "somevalue\n"
    return VarsModule("fake.vmx", runner)


def test_read_valid_namespace():
    mod = make_module()
    result = mod.read("guestVar", "mykey")
    assert result == {"value": "somevalue"}


def test_read_strips_whitespace():
    mod = make_module()
    mod._r.run_vmrun.return_value = "  value with spaces  \n"
    result = mod.read("guestVar", "mykey")
    assert result == {"value": "value with spaces"}


def test_write_valid_namespace():
    mod = make_module()
    result = mod.write("guestEnv", "MY_VAR", "hello")
    assert result == {"success": True}
    mod._r.run_vmrun.assert_called_with("writeVariable", "fake.vmx", "guestEnv", "MY_VAR", "hello")


def test_read_invalid_namespace():
    mod = make_module()
    with pytest.raises(ValueError, match="Invalid namespace"):
        mod.read("invalid", "key")


def test_write_invalid_namespace():
    mod = make_module()
    with pytest.raises(ValueError, match="Invalid namespace"):
        mod.write("badspace", "key", "val")


def test_all_valid_namespaces():
    mod = make_module()
    for ns in ("guestVar", "guestEnv", "runtimeConfig"):
        mod.read(ns, "k")
        mod.write(ns, "k", "v")


def test_vmrun_args_order_read():
    mod = make_module()
    mod.read("runtimeConfig", "checkpoint.vmState")
    mod._r.run_vmrun.assert_called_with(
        "readVariable", "fake.vmx", "runtimeConfig", "checkpoint.vmState"
    )
