from unittest.mock import MagicMock

import pytest

from vmctl.modules.network import NetworkModule
from vmctl.exceptions import VMCtlError


def make_module():
    runner = MagicMock()
    runner.run_vmrun.return_value = "192.168.157.161\n"
    return NetworkModule("fake.vmx", runner)


def test_ip_returns_dict():
    mod = make_module()
    assert mod.ip() == {"ip": "192.168.157.161"}


def test_ip_strips_whitespace():
    mod = make_module()
    mod._r.run_vmrun.return_value = "  10.0.0.5  \n"
    assert mod.ip() == {"ip": "10.0.0.5"}


def test_ip_empty_when_no_ip_yet():
    # Running guest with no IP assigned: getGuestIPAddress returns "" at exit 0.
    mod = make_module()
    mod._r.run_vmrun.return_value = "\n"
    assert mod.ip() == {"ip": ""}


def test_ip_vmrun_args():
    mod = make_module()
    mod.ip()
    mod._r.run_vmrun.assert_called_with("getGuestIPAddress", "fake.vmx")


def test_ip_propagates_error_when_off():
    # Powered off: vmrun exits non-zero, run_vmrun raises -- ip() must not swallow.
    mod = make_module()
    mod._r.run_vmrun.side_effect = VMCtlError("The virtual machine is not powered on")
    with pytest.raises(VMCtlError, match="not powered on"):
        mod.ip()
