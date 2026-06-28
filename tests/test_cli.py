"""Unit tests for the CLI resolution layer: optional VM name, the leading-``--``
marker, the uniform ``vm`` output key, the docker/git-flavored command surface
(ADR-0006), and the excluded/removed commands.

A fake VMCtl stands in for the real one. ``resolve`` mimics the auto-select
contract (single running VM, or the zero/multiple errors); module methods echo
their call so the injected ``vm`` key and argument binding can be asserted.
"""

import json

import click
import pytest
from click.testing import CliRunner

import vmctl.cli as cli_mod
from vmctl.cli import cli, _build_exec, _split_vm_path, _ps_rows
from vmctl.exceptions import VMCtlError


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
    def __init__(self, running, discovered=None):
        self.running = list(running)
        self.discovered = discovered or {}
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
        return {"running": [], "discovered": self.discovered}


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
    result, payload = run(["stop", "MyVM"])
    assert result.exit_code == 0
    assert payload["vm"] == "myvm"  # canonicalized
    assert payload["called"] == "stop"


def test_explicit_multi_positional(run):
    result, payload = run(["snapshot", "commit", "myvm", "s1", "-m", "msg"])
    assert payload["vm"] == "myvm"
    assert payload["args"] == ["s1"]
    assert payload["kwargs"]["description"] == "msg"


# --------------------------------------------------------------------------- #
# auto-select (name omitted)                                                  #
# --------------------------------------------------------------------------- #


def test_bare_name_only_command_auto_selects(run):
    result, payload = run(["stop"], running=("box",))
    assert result.exit_code == 0
    assert payload["vm"] == "box"


def test_auto_select_zero_running_errors(run):
    result, payload = run(["stop"], running=())
    assert result.exit_code == 1
    assert "no running VM to auto-select" in payload["error"]


def test_auto_select_multiple_running_errors(run):
    result, payload = run(["stop"], running=("a", "b"))
    assert result.exit_code == 1
    assert "multiple running VMs" in payload["error"]
    assert "a, b" in payload["error"]


# --------------------------------------------------------------------------- #
# leading -- marker (ADR-0001, preserved on flattened verbs)                  #
# --------------------------------------------------------------------------- #


def test_leading_dashdash_binds_remaining_positionals(run):
    result, payload = run(["snapshot", "commit", "--", "s1", "-m", "msg"],
                          running=("box",))
    assert result.exit_code == 0
    assert payload["vm"] == "box"  # auto-selected
    assert payload["args"] == ["s1"]  # snap_name still binds
    assert payload["kwargs"]["description"] == "msg"  # trailing flag still parses


def test_leading_dashdash_on_exec(run):
    result, payload = run(["exec", "--", "ipconfig"], running=("box",))
    assert result.exit_code == 0
    assert payload["vm"] == "box"
    assert payload["called"] == "run"
    assert payload["args"] == ["ipconfig"]


def test_dashdash_after_option_still_auto_selects(run):
    # `-i` before `--`: the marker must still drop the name and auto-select.
    result, payload = run(
        ["exec", "-i", "--", r"C:\Windows\System32\notepad.exe"],
        running=("box",),
    )
    assert result.exit_code == 0
    assert payload["vm"] == "box"  # auto-selected
    assert payload["kwargs"]["interactive"] is True


def test_dashdash_after_explicit_name_is_conventional_on_exec(run):
    result, payload = run(
        ["exec", "myvm", "-i", "--", r"C:\x.exe"],
    )
    assert result.exit_code == 0
    assert payload["vm"] == "myvm"
    assert payload["args"] == [r"C:\x.exe"]
    assert payload["kwargs"]["interactive"] is True


def test_non_leading_dashdash_is_conventional(run):
    result, payload = run(["snapshot", "commit", "myvm", "--", "s1"])
    assert result.exit_code == 0
    assert payload["vm"] == "myvm"
    assert payload["args"] == ["s1"]


# --------------------------------------------------------------------------- #
# ps (docker `ps`)                                                            #
# --------------------------------------------------------------------------- #


def test_ps_lists_running_only_by_default(monkeypatch):
    ctl = FakeCtl(running=("box",), discovered={"box": "/vms/box.vmx",
                                                "off": "/vms/off.vmx"})
    ctl.list_vms = lambda: {"running": ["/vms/box.vmx"],
                            "discovered": {"box": "/vms/box.vmx",
                                           "off": "/vms/off.vmx"}}
    monkeypatch.setattr(cli_mod, "VMCtl", lambda: ctl)
    result = CliRunner().invoke(cli, ["ps"])
    payload = json.loads(result.output)
    assert result.exit_code == 0
    assert payload["vms"] == [{"name": "box", "status": "running"}]


def test_ps_all_includes_stopped(monkeypatch):
    monkeypatch.setattr(cli_mod, "VMCtl", lambda: FakeCtl(running=()))
    runner_data = {"running": ["/vms/box.vmx"],
                   "discovered": {"box": "/vms/box.vmx", "off": "/vms/off.vmx"}}
    monkeypatch.setattr(cli_mod, "VMCtl",
                        lambda: type("C", (), {"list_vms": lambda self: runner_data})())
    result = CliRunner().invoke(cli, ["ps", "-a"])
    payload = json.loads(result.output)
    assert payload["vms"] == [
        {"name": "box", "status": "running"},
        {"name": "off", "status": "stopped"},
    ]


def test_ps_rows_pure():
    data = {"running": [r"C:\VMs\Box.vmx"],
            "discovered": {"box": r"c:\vms\box.vmx", "off": r"C:\VMs\off.vmx"}}
    # Running match is case/separator-insensitive.
    assert _ps_rows(data, show_all=False) == [{"name": "box", "status": "running"}]
    assert _ps_rows(data, show_all=True) == [
        {"name": "box", "status": "running"},
        {"name": "off", "status": "stopped"},
    ]


def test_ps_has_no_vm_key(run):
    result, payload = run(["ps"])
    assert result.exit_code == 0
    assert "vm" not in payload
    assert "vms" in payload


# --------------------------------------------------------------------------- #
# verb-rename coverage (new verb -> same library method)                      #
# --------------------------------------------------------------------------- #


def test_kill_is_hard_stop(run):
    result, payload = run(["kill", "myvm"])
    assert payload["called"] == "stop"
    assert payload["kwargs"]["hard"] is True


def test_stop_is_graceful(run):
    result, payload = run(["stop", "myvm"])
    assert payload["called"] == "stop"
    assert payload["kwargs"]["hard"] is False


def test_restart_maps_to_reset(run):
    result, payload = run(["restart", "myvm", "-H"])
    assert payload["called"] == "reset"
    assert payload["kwargs"]["hard"] is True


def test_snapshot_log_maps_to_list(run):
    result, payload = run(["snapshot", "log", "myvm"])
    assert payload["called"] == "list"


def test_snapshot_reset_maps_to_revert(run):
    result, payload = run(["snapshot", "reset", "myvm", "s1"])
    assert payload["called"] == "revert"
    assert payload["args"] == ["s1"]
    assert payload["kwargs"]["ensure_running"] is True


def test_snapshot_rm_maps_to_delete(run):
    result, payload = run(["snapshot", "rm", "myvm", "s1", "-c"])
    assert payload["called"] == "delete"
    assert payload["kwargs"]["delete_children"] is True


def test_network_ls_maps_to_list(run):
    result, payload = run(["network", "ls", "myvm"])
    assert payload["called"] == "list"


def test_peripheral_ls_maps_to_list(run):
    result, payload = run(["peripheral", "ls", "myvm"])
    assert payload["called"] == "list"


def test_shares_ls_maps_to_list(run):
    result, payload = run(["shares", "ls", "myvm"])
    assert payload["called"] == "list"


# --------------------------------------------------------------------------- #
# snapshot commit memory-default logic                                        #
# --------------------------------------------------------------------------- #


class PowerStateVM(FakeVM):
    """FakeVM whose power.state() returns a fixed PowerState, recording take()."""

    def __init__(self, name, power_state):
        super().__init__(name)
        self._power_state = power_state
        self.take_calls = []

    @property
    def power(self):
        outer = self

        class _Power:
            def state(self):
                return {"PowerState": outer._power_state}
        return _Power()

    @property
    def snapshot(self):
        outer = self

        class _Snap:
            def take(self, snap_name, memory=False, description=None):
                outer.take_calls.append((snap_name, memory, description))
                return {"taken": snap_name}
        return _Snap()


@pytest.fixture
def commit_run(monkeypatch):
    def _run(args, power_state):
        vm = PowerStateVM("box", power_state)

        class Ctl(FakeCtl):
            def resolve(self, name):
                return vm

        monkeypatch.setattr(cli_mod, "VMCtl", lambda: Ctl(("box",)))
        result = CliRunner().invoke(cli, args)
        return result, vm
    return _run


def test_commit_captures_memory_when_running(commit_run):
    result, vm = commit_run(["snapshot", "commit", "myvm", "s1"], power_state="on")
    assert result.exit_code == 0
    assert vm.take_calls == [("s1", True, None)]


def test_commit_disk_only_when_off(commit_run):
    result, vm = commit_run(["snapshot", "commit", "myvm", "s1"], power_state="off")
    assert result.exit_code == 0
    assert vm.take_calls == [("s1", False, None)]


def test_commit_disk_only_flag_forces_no_memory_while_running(commit_run):
    result, vm = commit_run(
        ["snapshot", "commit", "myvm", "s1", "--disk-only"], power_state="on")
    assert result.exit_code == 0
    assert vm.take_calls == [("s1", False, None)]


def test_commit_message_is_description(commit_run):
    result, vm = commit_run(
        ["snapshot", "commit", "myvm", "s1", "-m", "nightly"], power_state="off")
    assert vm.take_calls == [("s1", False, "nightly")]


# --------------------------------------------------------------------------- #
# exec flag matrix (FakeRunner asserts emitted guest.run args)                #
# --------------------------------------------------------------------------- #


class GuestRecorder:
    def __init__(self):
        self.calls = []

    def run(self, program, *args, no_wait=True, interactive=False):
        self.calls.append({"program": program, "args": list(args),
                           "no_wait": no_wait, "interactive": interactive})
        return {"ran": program}


class ExecVM(FakeVM):
    def __init__(self, name, rec, guest_os="windows9-64"):
        super().__init__(name)
        self._rec = rec
        self.__dict__["_guest_os"] = guest_os

    @property
    def guest(self):
        return self._rec


@pytest.fixture
def exec_run(monkeypatch):
    def _run(args, guest_os="windows9-64", running=("box",)):
        rec = GuestRecorder()

        class Ctl(FakeCtl):
            def resolve(self, name):
                vm = super().resolve(name)
                return ExecVM(vm.name, rec, guest_os)

        monkeypatch.setattr(cli_mod, "VMCtl", lambda: Ctl(running))
        result = CliRunner().invoke(cli, args)
        return result, rec
    return _run


def test_exec_bare_headless_runs_program_directly(exec_run):
    result, rec = exec_run(["exec", "myvm", "ipconfig"])
    assert result.exit_code == 0
    assert rec.calls == [{"program": "ipconfig", "args": [],
                          "no_wait": False, "interactive": False}]


def test_exec_bare_one_arg_ok(exec_run):
    result, rec = exec_run(["exec", "myvm", "ipconfig", "/all"])
    assert result.exit_code == 0
    assert rec.calls[0]["program"] == "ipconfig"
    assert rec.calls[0]["args"] == ["/all"]


def test_exec_bare_multi_arg_errors_and_never_calls_vmcli(exec_run):
    result, rec = exec_run(["exec", "myvm", "echo", "a", "b"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert "use: vmctl exec -t" in payload["error"]
    assert rec.calls == []


def test_exec_tty_windows_wraps_in_cmd(exec_run):
    result, rec = exec_run(["exec", "-t", "myvm", "notepad", "foo.txt"])
    assert result.exit_code == 0
    assert rec.calls == [{
        "program": r"C:\Windows\System32\cmd.exe",
        "args": ['/c start "" notepad foo.txt'],
        "no_wait": False, "interactive": False,
    }]


def test_exec_tty_linux_wraps_in_sh(exec_run):
    result, rec = exec_run(["exec", "-t", "myvm", "ls", "-la"], guest_os="ubuntu-64")
    # -la binds as a program arg (ignore_unknown_options), shell-joined.
    assert result.exit_code == 0
    assert rec.calls == [{
        "program": "/bin/sh",
        "args": ["-c", "ls -la &"],
        "no_wait": False, "interactive": False,
    }]


def test_exec_interactive_adds_interactive_and_nowait(exec_run):
    result, rec = exec_run(["exec", "-i", "myvm", r"C:\Windows\System32\notepad.exe"])
    assert result.exit_code == 0
    assert rec.calls == [{
        "program": r"C:\Windows\System32\notepad.exe", "args": [],
        "no_wait": True, "interactive": True,
    }]


def test_exec_it_combines_shell_and_desktop(exec_run):
    result, rec = exec_run(["exec", "-it", "myvm", "notepad"])
    assert result.exit_code == 0
    assert rec.calls == [{
        "program": r"C:\Windows\System32\cmd.exe",
        "args": ['/c start "" notepad'],
        "no_wait": True, "interactive": True,
    }]


def test_exec_it_parses_same_as_i_t(exec_run):
    combined, rec1 = exec_run(["exec", "-it", "myvm", "notepad"])
    split, rec2 = exec_run(["exec", "-i", "-t", "myvm", "notepad"])
    assert combined.exit_code == 0 and split.exit_code == 0
    assert rec1.calls == rec2.calls


def test_exec_no_program_errors(exec_run):
    result, rec = exec_run(["exec", "myvm"])
    assert result.exit_code == 1
    assert rec.calls == []


# --- _build_exec pure unit tests ---


def test_build_exec_bare():
    assert _build_exec(["ipconfig"], "", tty=False) == ("ipconfig", [])
    assert _build_exec(["ping", "host"], "", tty=False) == ("ping", ["host"])


def test_build_exec_bare_multi_arg_raises():
    with pytest.raises(VMCtlError, match="exec -t"):
        _build_exec(["echo", "a", "b"], "", tty=False)


def test_build_exec_tty_windows():
    assert _build_exec(["notepad", "x"], "windows9-64", tty=True) == (
        r"C:\Windows\System32\cmd.exe", ['/c start "" notepad x'])


def test_build_exec_tty_non_windows():
    assert _build_exec(["ls", "-la"], "ubuntu-64", tty=True) == (
        "/bin/sh", ["-c", "ls -la &"])


# --------------------------------------------------------------------------- #
# cp (docker vm:path syntax)                                                  #
# --------------------------------------------------------------------------- #


class CpVM(FakeVM):
    def __init__(self, name, rec):
        super().__init__(name)
        self._rec = rec

    @property
    def guest(self):
        return self._rec


class CpRecorder:
    def __init__(self):
        self.calls = []

    def copy_to(self, host, guest, overwrite=False):
        self.calls.append(("copy_to", host, guest, overwrite))
        return {"copied": True}

    def copy_from(self, guest, host, overwrite=False):
        self.calls.append(("copy_from", guest, host, overwrite))
        return {"copied": True}


@pytest.fixture
def cp_run(monkeypatch):
    def _run(args, running=("box",)):
        rec = CpRecorder()

        class Ctl(FakeCtl):
            def resolve(self, name):
                vm = super().resolve(name)
                return CpVM(vm.name, rec)

        monkeypatch.setattr(cli_mod, "VMCtl", lambda: Ctl(running))
        result = CliRunner().invoke(cli, args)
        try:
            payload = json.loads(result.output)
        except (json.JSONDecodeError, ValueError):
            payload = None
        return result, payload, rec
    return _run


def test_cp_host_to_guest(cp_run):
    result, payload, rec = cp_run(["cp", "./f", r"myvm:C:\dir\f.txt"])
    assert result.exit_code == 0
    assert payload["vm"] == "myvm"
    assert rec.calls == [("copy_to", "./f", r"C:\dir\f.txt", False)]


def test_cp_guest_to_host(cp_run):
    result, payload, rec = cp_run(["cp", r"myvm:C:\f.txt", "./out"])
    assert result.exit_code == 0
    assert payload["vm"] == "myvm"
    assert rec.calls == [("copy_from", r"C:\f.txt", "./out", False)]


def test_cp_leading_colon_auto_selects(cp_run):
    result, payload, rec = cp_run(["cp", "./f", r":C:\dir\f.txt"], running=("box",))
    assert result.exit_code == 0
    assert payload["vm"] == "box"  # auto-selected
    assert rec.calls == [("copy_to", "./f", r"C:\dir\f.txt", False)]


def test_cp_overwrite_flag(cp_run):
    result, payload, rec = cp_run(["cp", "-o", "./f", "myvm:/tmp/f"])
    assert rec.calls == [("copy_to", "./f", "/tmp/f", True)]


def test_cp_drive_letter_is_host_path_not_vm(cp_run):
    # Both sides are host paths (C:\x is a drive path, ./out has no colon).
    result, payload, rec = cp_run(["cp", r"C:\x", "./out"])
    assert result.exit_code == 1
    assert "exactly one" in payload["error"]
    assert rec.calls == []


def test_cp_no_guest_side_errors(cp_run):
    result, payload, rec = cp_run(["cp", "./a", "./b"])
    assert result.exit_code == 1
    assert "exactly one" in payload["error"]


# --- _split_vm_path pure unit tests ---


@pytest.mark.parametrize("token,expected", [
    (r"myvm:C:\dir", ("myvm", r"C:\dir")),
    ("myvm:/tmp/f", ("myvm", "/tmp/f")),
    (r":C:\dir", ("", r"C:\dir")),         # leading colon -> auto-select
    (r"C:\x", (None, r"C:\x")),            # drive path -> host
    ("C:/x", (None, "C:/x")),              # forward-slash drive path -> host
    ("./relative", (None, "./relative")),  # no colon -> host
    ("/abs/path", (None, "/abs/path")),    # no colon -> host
])
def test_split_vm_path(token, expected):
    assert _split_vm_path(token) == expected


# --------------------------------------------------------------------------- #
# aliases (ADR-0006)                                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("alias,canonical", [
    ("ss", "snapshot"),
    ("net", "network"),
    ("dev", "peripheral"),
    ("in", "inspect"),
    ("re", "restart"),
    ("ex", "exec"),
])
def test_alias_resolves_to_canonical_command(alias, canonical):
    ctx = click.Context(cli)
    assert cli.get_command(ctx, alias) is cli.get_command(ctx, canonical)


def test_alias_ss_log_runs(run):
    result, payload = run(["ss", "log", "myvm"])
    assert result.exit_code == 0
    assert payload["called"] == "list"


def test_alias_re_restarts(run):
    result, payload = run(["re", "myvm"])
    assert result.exit_code == 0
    assert payload["called"] == "reset"


def test_aliases_not_listed_in_help(run):
    result, _ = run(["--help"])
    # Canonical names appear; aliases stay hidden from the command list.
    assert "snapshot" in result.output
    assert "\n  ss " not in result.output


# --------------------------------------------------------------------------- #
# inspect widening (absorbs power state + parse-vmx)                          #
# --------------------------------------------------------------------------- #


class InspectVM(FakeVM):
    @property
    def inspect(self):
        class _Inspect:
            def inspect(self):
                return {"power": {"PowerState": "on"}, "config": {}}

            def parse_vmx(self):
                return {"vmx": {"displayName": "box"}, "vmsd": {}}
        return _Inspect()


def test_inspect_merges_state_and_vmx(monkeypatch):
    class Ctl(FakeCtl):
        def resolve(self, name):
            return InspectVM("box")

    monkeypatch.setattr(cli_mod, "VMCtl", lambda: Ctl(("box",)))
    result = CliRunner().invoke(cli, ["inspect", "myvm"])
    payload = json.loads(result.output)
    assert result.exit_code == 0
    assert payload["vm"] == "box"
    assert payload["power"] == {"PowerState": "on"}  # absorbs `power state`
    assert payload["vmx"] == {"displayName": "box"}  # absorbs `parse-vmx`


# --------------------------------------------------------------------------- #
# excluded commands (no vm key)                                               #
# --------------------------------------------------------------------------- #


def test_auth_set_requires_name_and_has_no_vm_key(run):
    result, payload = run(["auth", "set", "myvm", "--user", "u", "--password", "p"])
    assert result.exit_code == 0
    assert payload == {"success": True}
    assert "vm" not in payload


def test_auth_set_without_name_is_usage_error(run):
    result, _ = run(["auth", "set", "--user", "u", "--password", "p"])
    assert result.exit_code != 0


# --------------------------------------------------------------------------- #
# clone (top-level; in scope)                                                 #
# --------------------------------------------------------------------------- #


def test_clone_adds_vm_key_and_uses_canonical_name(monkeypatch):
    captured = {}

    def make_ctl():
        ctl = FakeCtl(running=("box",))
        captured["ctl"] = ctl
        return ctl

    monkeypatch.setattr(cli_mod, "VMCtl", make_ctl)
    result = CliRunner().invoke(cli, ["clone", "SRC", "dest"])
    payload = json.loads(result.output)
    assert result.exit_code == 0
    assert payload["vm"] == "src"
    assert captured["ctl"].clone_calls == [("src", "dest", False)]


def test_clone_leading_dashdash_auto_selects(monkeypatch):
    captured = {}

    def make_ctl():
        ctl = FakeCtl(running=("box",))
        captured["ctl"] = ctl
        return ctl

    monkeypatch.setattr(cli_mod, "VMCtl", make_ctl)
    result = CliRunner().invoke(cli, ["clone", "--", "dest"])
    payload = json.loads(result.output)
    assert result.exit_code == 0
    assert payload["vm"] == "box"
    assert captured["ctl"].clone_calls == [("box", "dest", False)]


# --------------------------------------------------------------------------- #
# removed commands / groups (negative tests guard re-introduction)            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("argv", [
    ["power", "start", "myvm"],
    ["power", "state", "myvm"],
    ["guest", "run", "myvm", "cmd.exe"],
    ["guest", "ps", "myvm"],
    ["guest", "kill", "myvm", "1"],
    ["guest", "copy-to", "myvm", "a", "b"],
    ["fs", "ls", "myvm", "C:\\"],
    ["tools", "query", "myvm"],
    ["vars", "read", "myvm", "guestVar", "k"],
    ["mks", "screenshot", "myvm", "out.png"],
    ["vm", "list"],
    ["vm", "clone", "src", "dst"],
    ["parse-vmx", "myvm"],
    ["snapshot", "take", "myvm", "s1"],
    ["snapshot", "list", "myvm"],
    ["snapshot", "revert", "myvm", "s1"],
    ["snapshot", "delete", "myvm", "s1"],
    ["network", "list", "myvm"],
    ["peripheral", "list", "myvm"],
    ["shares", "list", "myvm"],
])
def test_removed_commands_are_gone(run, argv):
    result, _ = run(argv)
    assert result.exit_code != 0


# --------------------------------------------------------------------------- #
# clipboard push: stdin / empty-text handling                                 #
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
    monkeypatch.setattr(cli_mod, "VMCtl", lambda: FakeCtl(("box",)))
    result = CliRunner().invoke(cli, ["clipboard", "push"], input="piped text")
    payload = json.loads(result.output)
    assert result.exit_code == 0
    assert payload["vm"] == "box"
    assert payload["args"] == ["piped text"]


def test_clipboard_push_empty_stdin_errors(monkeypatch):
    monkeypatch.setattr(cli_mod, "VMCtl", lambda: FakeCtl(("box",)))
    result = CliRunner().invoke(cli, ["clipboard", "push"])
    payload = json.loads(result.output)
    assert result.exit_code == 1
    assert "clipboard text is empty" in payload["error"]
    assert "push -- TEXT" in payload["error"]


def test_clipboard_push_lone_arg_gives_actionable_footgun_error(monkeypatch):
    monkeypatch.setattr(cli_mod, "VMCtl", lambda: FakeCtl(("box",)))
    result = CliRunner().invoke(cli, ["clipboard", "push", "hello"])
    payload = json.loads(result.output)
    assert result.exit_code == 1
    err = payload["error"]
    assert "'hello' was read as the VM name" in err
    assert "clipboard push -- hello" in err


def test_clipboard_push_dashdash_makes_lone_arg_text(run):
    result, payload = run(["clipboard", "push", "--", "hello"], running=("box",))
    assert result.exit_code == 0
    assert payload["vm"] == "box"
    assert payload["args"] == ["hello"]


# --------------------------------------------------------------------------- #
# sync / push (in scope; leading -- auto-select)                              #
# --------------------------------------------------------------------------- #


class SyncRecorder:
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
    assert rec.calls == [("push", "./build", r"C:\app", None, None)]


def test_push_leading_dashdash_auto_selects(sync_run):
    result, payload, rec = sync_run(["push", "--", "./build", r"C:\app"],
                                    running=("box",))
    assert result.exit_code == 0
    assert payload["vm"] == "box"
    assert rec.calls == [("push", "./build", r"C:\app", None, None)]


def test_push_passes_credential_override(sync_run):
    result, _, rec = sync_run(
        ["push", "myvm", "./build", r"C:\app", "-u", "cli", "-p", "new"])
    assert result.exit_code == 0
    assert rec.calls == [("push", "./build", r"C:\app", "cli", "new")]


# --------------------------------------------------------------------------- #
# command resolution                                                          #
# --------------------------------------------------------------------------- #


def test_unknown_command_still_errors(run):
    result, _ = run(["zzz", "myvm"])
    assert result.exit_code != 0
