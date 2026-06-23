"""Unit tests for the CLI resolution layer: optional VM name, the leading-``--``
marker, the uniform ``vm`` output key, and the excluded commands.

A fake VMCtl stands in for the real one. ``resolve`` mimics the auto-select
contract (single running VM, or the zero/multiple errors); module methods echo
their call so the injected ``vm`` key and argument binding can be asserted.
"""

import json

import pytest
from click.testing import CliRunner

import vmctl.cli as cli_mod
from vmctl.cli import cli


class FakeModule:
    """Any method call returns a record of how it was invoked."""

    def __getattr__(self, method):
        def _call(*args, **kwargs):
            return {"called": method, "args": list(args), "kwargs": kwargs}
        return _call


class FakeVM:
    def __init__(self, name):
        self.name = name

    def __getattr__(self, _module):
        return FakeModule()


class FakeCtl:
    def __init__(self, running):
        self.running = list(running)
        self.clone_calls = []
        self.cred_calls = []

    def resolve(self, name):
        if name is None:
            if not self.running:
                raise ValueError("no running VM to auto-select; pass a name")
            if len(self.running) > 1:
                cands = ", ".join(sorted(self.running))
                raise ValueError(f"multiple running VMs ({cands}); pass a name")
            return FakeVM(self.running[0])
        return FakeVM(name.lower())  # canonical = lowercased

    def clone(self, name, dest, linked):
        self.clone_calls.append((name, dest, linked))
        return {"success": True}

    def set_credentials(self, name, user, password):
        self.cred_calls.append((name, user, password))

    def list_vms(self):
        return {"running": [], "discovered": {}}


@pytest.fixture
def run(monkeypatch):
    def _run(args, running=("box",)):
        monkeypatch.setattr(cli_mod, "VMCtl", lambda: FakeCtl(running))
        result = CliRunner().invoke(cli, args)
        try:
            payload = json.loads(result.output)
        except (json.JSONDecodeError, ValueError):
            payload = None
        return result, payload
    return _run


# --------------------------------------------------------------------------- #
# explicit name                                                               #
# --------------------------------------------------------------------------- #


def test_explicit_name_adds_vm_key(run):
    result, payload = run(["power", "state", "MyVM"])
    assert result.exit_code == 0
    assert payload["vm"] == "myvm"  # canonicalized
    assert payload["called"] == "state"


def test_explicit_multi_positional(run):
    result, payload = run(["snapshot", "take", "myvm", "s1", "--memory"])
    assert payload["vm"] == "myvm"
    assert payload["args"] == ["s1"]
    assert payload["kwargs"]["memory"] is True


# --------------------------------------------------------------------------- #
# auto-select (name omitted)                                                  #
# --------------------------------------------------------------------------- #


def test_bare_name_only_command_auto_selects(run):
    result, payload = run(["power", "state"], running=("box",))
    assert result.exit_code == 0
    assert payload["vm"] == "box"


def test_auto_select_zero_running_errors(run):
    result, payload = run(["power", "state"], running=())
    assert result.exit_code == 1
    assert "no running VM to auto-select" in payload["error"]


def test_auto_select_multiple_running_errors(run):
    result, payload = run(["power", "state"], running=("a", "b"))
    assert result.exit_code == 1
    assert "multiple running VMs" in payload["error"]
    assert "a, b" in payload["error"]


# --------------------------------------------------------------------------- #
# leading -- marker                                                           #
# --------------------------------------------------------------------------- #


def test_leading_dashdash_binds_remaining_positionals(run):
    result, payload = run(["snapshot", "take", "--", "s1", "--memory"], running=("box",))
    assert result.exit_code == 0
    assert payload["vm"] == "box"  # auto-selected
    assert payload["args"] == ["s1"]  # snap_name still binds
    assert payload["kwargs"]["memory"] is True  # trailing flag still parses


def test_leading_dashdash_on_guest_run(run):
    result, payload = run(["guest", "run", "--", "cmd.exe", "/c", "echo", "hi"], running=("box",))
    assert result.exit_code == 0
    assert payload["vm"] == "box"
    assert payload["called"] == "run"
    assert payload["args"] == ["cmd.exe", "/c", "echo", "hi"]


def test_non_leading_dashdash_is_conventional(run):
    # `--` after the name keeps Click's end-of-options meaning; s1 still binds.
    result, payload = run(["snapshot", "take", "myvm", "--", "s1"])
    assert result.exit_code == 0
    assert payload["vm"] == "myvm"
    assert payload["args"] == ["s1"]


# --------------------------------------------------------------------------- #
# excluded commands                                                           #
# --------------------------------------------------------------------------- #


def test_vm_list_has_no_vm_key(run):
    result, payload = run(["vm", "list"])
    assert result.exit_code == 0
    assert "vm" not in payload
    assert "running" in payload


def test_auth_set_requires_name_and_has_no_vm_key(run):
    result, payload = run(["auth", "set", "myvm", "--user", "u", "--password", "p"])
    assert result.exit_code == 0
    assert payload == {"success": True}
    assert "vm" not in payload


def test_auth_set_without_name_is_usage_error(run):
    # auth set is excluded from auto-select: a missing name is a Click usage error.
    result, _ = run(["auth", "set", "--user", "u", "--password", "p"])
    assert result.exit_code != 0


# --------------------------------------------------------------------------- #
# clone (in scope)                                                            #
# --------------------------------------------------------------------------- #


def test_clone_adds_vm_key_and_uses_canonical_name(run, monkeypatch):
    captured = {}

    def make_ctl():
        ctl = FakeCtl(running=("box",))
        captured["ctl"] = ctl
        return ctl

    monkeypatch.setattr(cli_mod, "VMCtl", make_ctl)
    result = CliRunner().invoke(cli, ["vm", "clone", "SRC", "dest"])
    payload = json.loads(result.output)
    assert result.exit_code == 0
    assert payload["vm"] == "src"
    assert captured["ctl"].clone_calls == [("src", "dest", False)]
