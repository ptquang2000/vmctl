import pytest

from vmctl.runner import Runner
from vmctl.exceptions import VMCtlError


def make_runner():
    return Runner("C:\\VMware")


def test_run_vmrun_test_true_on_exists(monkeypatch):
    # Existence verb: exit 0, stdout "The directory exists." -> True.
    r = make_runner()
    monkeypatch.setattr(r, "_exec", lambda cmd: "The directory exists.\n")
    assert r.run_vmrun_test("directoryExistsInGuest", "fake.vmx", "C:\\dir") is True


def test_run_vmrun_test_false_on_absent(monkeypatch):
    # Absent: _exec raises (exit 127) with the "does not exist" message -> False.
    r = make_runner()

    def boom(cmd):
        raise VMCtlError("The directory does not exist.", returncode=127, stderr="")

    monkeypatch.setattr(r, "_exec", boom)
    assert r.run_vmrun_test("directoryExistsInGuest", "fake.vmx", "C:\\nope") is False


def test_run_vmrun_test_raises_on_real_failure(monkeypatch):
    # Any other nonzero result (auth failure, VM off) is a real error -> raise.
    r = make_runner()

    def boom(cmd):
        raise VMCtlError(
            "Error: Invalid user name or password for the guest OS",
            returncode=127, stderr="Error: Invalid user name or password for the guest OS",
        )

    monkeypatch.setattr(r, "_exec", boom)
    with pytest.raises(VMCtlError, match="Invalid user name"):
        r.run_vmrun_test("directoryExistsInGuest", "fake.vmx", "C:\\dir")
