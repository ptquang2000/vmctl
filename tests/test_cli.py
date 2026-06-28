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


# --------------------------------------------------------------------------- #
# sync / push (in scope; leading -- auto-select)                              #
# --------------------------------------------------------------------------- #


class SyncRecorder:
    """Records run/push calls but drops the non-serializable ``log`` callback."""

    def __init__(self):
        self.calls = []

    def run(self, sync_optional=False, project_dir=None, log=None,
            user=None, password=None):
        self.calls.append(("run", sync_optional, project_dir, user, password))
        return {"synced": True}

    def push(self, source, dest, project_dir=None, log=None,
             user=None, password=None):
        self.calls.append(("push", source, dest, user, password))
        return {"pushed": True}


class SyncVM(FakeVM):
    def __init__(self, name, recorder):
        super().__init__(name)
        self._rec = recorder

    @property
    def sync(self):
        return self._rec


@pytest.fixture
def sync_run(monkeypatch):
    rec = SyncRecorder()

    def _run(args, running=("box",)):
        class Ctl(FakeCtl):
            def resolve(self, name):
                vm = super().resolve(name)
                return SyncVM(vm.name, rec)

        monkeypatch.setattr(cli_mod, "VMCtl", lambda: Ctl(running))
        result = CliRunner().invoke(cli, args)
        try:
            payload = json.loads(result.output)
        except (json.JSONDecodeError, ValueError):
            payload = None
        return result, payload, rec
    return _run


def test_sync_explicit_name(sync_run):
    result, payload, rec = sync_run(["sync", "myvm", "--optional"])
    assert result.exit_code == 0
    assert payload["vm"] == "myvm"
    assert payload["synced"] is True
    assert rec.calls == [("run", True, None, None, None)]


def test_sync_bare_auto_selects(sync_run):
    result, payload, rec = sync_run(["sync"], running=("box",))
    assert result.exit_code == 0
    assert payload["vm"] == "box"
    assert rec.calls == [("run", False, None, None, None)]


def test_push_explicit_name_binds_positionals(sync_run):
    result, payload, rec = sync_run(["push", "myvm", "./build", r"C:\app"])
    assert result.exit_code == 0
    assert payload["vm"] == "myvm"
    assert payload["pushed"] is True
    assert rec.calls == [("push", "./build", r"C:\app", None, None)]


def test_sync_passes_credential_override(sync_run):
    result, _, rec = sync_run(
        ["sync", "myvm", "--user", "cli", "--password", "new"])
    assert result.exit_code == 0
    assert rec.calls == [("run", False, None, "cli", "new")]


def test_push_passes_credential_override(sync_run):
    result, _, rec = sync_run(
        ["push", "myvm", "./build", r"C:\app", "-u", "cli", "-p", "new"])
    assert result.exit_code == 0
    assert rec.calls == [("push", "./build", r"C:\app", "cli", "new")]


def test_push_leading_dashdash_auto_selects(sync_run):
    result, payload, rec = sync_run(["push", "--", "./build", r"C:\app"], running=("box",))
    assert result.exit_code == 0
    assert payload["vm"] == "box"
    assert rec.calls == [("push", "./build", r"C:\app", None, None)]


# --------------------------------------------------------------------------- #
# peripheral (unified connect/disconnect; removed verbs absent)               #
# --------------------------------------------------------------------------- #


def test_peripheral_connect_binds_id_and_injects_vm(run):
    result, payload = run(["peripheral", "connect", "myvm", "sata0:1"])
    assert result.exit_code == 0
    assert payload["vm"] == "myvm"
    assert payload["called"] == "connect"
    assert payload["args"] == ["sata0:1"]


def test_peripheral_disconnect_auto_selects(run):
    result, payload = run(["peripheral", "disconnect", "--", "usb_xhci:4"], running=("box",))
    assert result.exit_code == 0
    assert payload["vm"] == "box"
    assert payload["called"] == "disconnect"
    assert payload["args"] == ["usb_xhci:4"]


def test_peripheral_list_and_mount_iso_survive(run):
    result, payload = run(["peripheral", "list", "myvm"])
    assert result.exit_code == 0
    assert payload["called"] == "list"

    result, payload = run(["peripheral", "mount-iso", "myvm", "sata0:1", r"C:\foo.iso"])
    assert result.exit_code == 0
    assert payload["called"] == "mount_iso"
    assert payload["args"] == ["sata0:1", r"C:\foo.iso"]


@pytest.mark.parametrize(
    "removed",
    ["eject", "connect-disk", "disconnect-disk", "connect-usb",
     "disconnect-usb", "connect-serial", "disconnect-serial"],
)
def test_removed_peripheral_commands_are_gone(run, removed):
    result, _ = run(["peripheral", removed, "myvm", "x"])
    assert result.exit_code != 0  # no such command


# --------------------------------------------------------------------------- #
# short option flags                                                          #
# --------------------------------------------------------------------------- #


def test_short_flag_is_flag_equivalent_to_long(run):
    # -m is the short form of --memory on `snapshot take`.
    result, payload = run(["snapshot", "take", "myvm", "s1", "-m"])
    assert result.exit_code == 0
    assert payload["kwargs"]["memory"] is True


def test_short_flag_value_option(run):
    # -d carries --description's value; -n is --max on a different command.
    _, payload = run(["snapshot", "take", "myvm", "s1", "-d", "nightly"])
    assert payload["kwargs"]["description"] == "nightly"
    _, payload = run(["fs", "ls", "myvm", r"C:\\", "-n", "5"])
    assert payload["kwargs"]["max"] == 5


def test_mkdir_dash_p_is_parents_unix_convention(run):
    # -p means --parents here (Unix `mkdir -p`), not password.
    _, payload = run(["fs", "mkdir", "myvm", r"C:\\new", "-p"])
    assert payload["kwargs"]["parents"] is True


# --------------------------------------------------------------------------- #
# command resolution                                                          #
# --------------------------------------------------------------------------- #


def test_unknown_command_still_errors(run):
    result, _ = run(["po", "zzz", "myvm"])
    assert result.exit_code != 0


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


# --------------------------------------------------------------------------- #
# clipboard push: stdin / empty-text handling (commit 7796782)                #
# --------------------------------------------------------------------------- #


def test_clipboard_push_explicit_text(run):
    result, payload = run(["clipboard", "push", "myvm", "hello world"])
    assert result.exit_code == 0
    assert payload["vm"] == "myvm"
    assert payload["called"] == "push_text"
    assert payload["args"] == ["hello world"]


def test_clipboard_pull_auto_selects(run):
    result, payload = run(["clipboard", "pull"], running=("box",))
    assert result.exit_code == 0
    assert payload["vm"] == "box"
    assert payload["called"] == "pull_text"


def test_clipboard_push_reads_piped_stdin(monkeypatch):
    # Text positional omitted + piped (non-tty) stdin => stdin is the text.
    monkeypatch.setattr(cli_mod, "VMCtl", lambda: FakeCtl(("box",)))
    result = CliRunner().invoke(cli, ["clipboard", "push"], input="piped text")
    payload = json.loads(result.output)
    assert result.exit_code == 0
    assert payload["vm"] == "box"  # name omitted => auto-selected
    assert payload["args"] == ["piped text"]


def test_clipboard_push_empty_stdin_errors(monkeypatch):
    # No name, no text, empty stdin => plain empty-text error pointing at the fix.
    monkeypatch.setattr(cli_mod, "VMCtl", lambda: FakeCtl(("box",)))
    result = CliRunner().invoke(cli, ["clipboard", "push"])  # no input
    payload = json.loads(result.output)
    assert result.exit_code == 1
    assert "clipboard text is empty" in payload["error"]
    assert "push -- TEXT" in payload["error"]  # points to the canonical form


def test_clipboard_push_lone_arg_gives_actionable_footgun_error(monkeypatch):
    # FOOTGUN fix: a single token binds to NAME (not text). We do NOT silently
    # reinterpret it (per the "no silent count-based fill" rule); instead we name
    # what happened and point to `push -- hello` / pipe / explicit-name forms.
    monkeypatch.setattr(cli_mod, "VMCtl", lambda: FakeCtl(("box",)))
    result = CliRunner().invoke(cli, ["clipboard", "push", "hello"])  # no pipe
    payload = json.loads(result.output)
    assert result.exit_code == 1
    err = payload["error"]
    assert "'hello' was read as the VM name" in err
    assert "clipboard push -- hello" in err  # the documented auto-select form


def test_clipboard_push_dashdash_makes_lone_arg_text(run):
    # The documented way to push literal text under auto-select: leading `--`.
    result, payload = run(["clipboard", "push", "--", "hello"], running=("box",))
    assert result.exit_code == 0
    assert payload["vm"] == "box"
    assert payload["args"] == ["hello"]


def test_clipboard_push_explicit_text_ignores_stdin(monkeypatch):
    # An explicit text arg wins; stdin is not consulted (text is not None).
    monkeypatch.setattr(cli_mod, "VMCtl", lambda: FakeCtl(("box",)))
    result = CliRunner().invoke(
        cli, ["clipboard", "push", "myvm", "typed"], input="ignored")
    payload = json.loads(result.output)
    assert result.exit_code == 0
    assert payload["vm"] == "myvm"
    assert payload["args"] == ["typed"]
