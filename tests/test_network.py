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


def test_ip_falls_back_to_guestinfo_when_vix_says_tools_not_running():
    # After a memory-snapshot resume the VIX channel reports "Tools not running"
    # though Tools are up; ip() falls back to the host-side guestinfo.ip cache.
    mod = make_module()

    def fake(*args):
        if args[0] == "getGuestIPAddress":
            raise VMCtlError("Error: The VMware Tools are not running in the virtual machine")
        if args[0] == "readVariable":  # readVariable <vmx> guestVar ip
            assert args[1:] == ("fake.vmx", "guestVar", "ip")
            return "192.168.157.161\n"
        raise AssertionError(f"unexpected vmrun {args}")

    mod._r.run_vmrun.side_effect = fake
    assert mod.ip() == {"ip": "192.168.157.161"}


def test_ip_reraises_when_fallback_also_empty():
    # Tools-not-running AND no cached guestinfo.ip -> surface the original error.
    mod = make_module()

    def fake(*args):
        if args[0] == "getGuestIPAddress":
            raise VMCtlError("Error: The VMware Tools are not running in the virtual machine")
        return "\n"  # readVariable: empty guestinfo.ip

    mod._r.run_vmrun.side_effect = fake
    with pytest.raises(VMCtlError, match="not running"):
        mod.ip()


def test_ip_does_not_fall_back_on_non_tools_error():
    # A non-"tools not running" failure (e.g. powered off) must NOT trigger the
    # guestinfo fallback -- readVariable is never called.
    mod = make_module()
    mod._r.run_vmrun.side_effect = VMCtlError("Error: ...not powered on")
    with pytest.raises(VMCtlError, match="not powered on"):
        mod.ip()
    # only the getGuestIPAddress attempt, no readVariable fallback
    assert mod._r.run_vmrun.call_count == 1
