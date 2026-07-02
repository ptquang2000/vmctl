"""Unit tests for the CLI: the resolution layer (optional VM name, the
leading-``--`` marker, auto-select), the restructured command surface
(ADR-0006), and the human-text output contract (ADR-0007).

Output is now human-readable text, not JSON: the library is the structured
interface. So these tests assert two things -- (1) the *resolution/binding*
behavior, by recording how the fake modules were called, and (2) that the CLI is
*wired to render*, by asserting the rendered confirmation line (verb + resolved
VM name). The exhaustive table/alignment shapes are tested directly in
``test_render.py``; here we only check the wiring.

A fake VMCtl stands in for the real one. ``resolve`` mimics the auto-select
contract (single running VM, or the zero/multiple errors); every fake module
call is appended to the controller's ``calls`` log so argument binding and the
resolved VM name can be asserted without parsing output.
"""

import click
import pytest
from click.testing import CliRunner

import vmctl.cli as cli_mod
from vmctl import render
from vmctl.cli import cli, _build_exec, _split_vm_path, _ps_rows


class FakeModule:
    """Any method call records its invocation on the shared log and echoes it."""

    def __init__(self, module_name, log):
        self._module = module_name
        self._log = log

    def __getattr__(self, method):
        def _call(*args, **kwargs):
            record = {"module": self._module, "called": method,
                      "args": list(args), "kwargs": kwargs}
            self._log.append(record)
            return dict(record)
        return _call


class FakeVM:
    def __init__(self, name, log):
        self.name = name
        self._log = log

    def __getattr__(self, module):
        return FakeModule(module, self._log)


class FakeCtl:
    def __init__(self, running, discovered=None):
        self.running = list(running)
        self.discovered = discovered or {}
        self.clone_calls = []
        self.cred_calls = []
        self.calls = []  # every fake module method call, in order

    def resolve(self, name):
        if name is None:
            if not self.running:
                raise ValueError("no running VM to auto-select; pass a name")
            if len(self.running) > 1:
                cands = ", ".join(sorted(self.running))
                raise ValueError(f"multiple running VMs ({cands}); pass a name")
            return FakeVM(self.running[0], self.calls)
        return FakeVM(name.lower(), self.calls)  # canonical = lowercased

    def clone(self, name, dest, linked):
        self.clone_calls.append((name, dest, linked))
        return {"success": True}

    def set_credentials(self, name, user, password):
        self.cred_calls.append((name, user, password))

    def list_vms(self):
        return {"running": [], "discovered": self.discovered}


def _last(ctl, method):
    """The most recent recorded call to ``method`` (across modules)."""
    for record in reversed(ctl.calls):
        if record["called"] == method:
            return record
    raise AssertionError(f"no call to {method!r} in {ctl.calls}")


@pytest.fixture
def run(monkeypatch):
    def _run(args, running=("box",)):
        ctl = FakeCtl(running)
        monkeypatch.setattr(cli_mod, "VMCtl", lambda: ctl)
        result = CliRunner().invoke(cli, args)
        return result, ctl
    return _run


# --------------------------------------------------------------------------- #
# explicit name                                                               #
# --------------------------------------------------------------------------- #


def test_explicit_name_renders_confirmation_with_canonical_name(run):
    result, ctl = run(["stop", "MyVM"])
    assert result.exit_code == 0
    assert result.output.strip() == "stopped myvm"  # canonicalized
    assert _last(ctl, "stop")["kwargs"] == {"hard": False}


def test_explicit_multi_positional(run):
    result, ctl = run(["snapshot", "commit", "myvm", "s1", "-m", "msg"])
    assert result.exit_code == 0
    assert result.output.strip() == "committed s1 on myvm"
    take = _last(ctl, "take")
    assert take["args"] == ["s1"]
    assert take["kwargs"]["description"] == "msg"


# --------------------------------------------------------------------------- #
# auto-select (name omitted)                                                  #
# --------------------------------------------------------------------------- #


def test_bare_name_only_command_auto_selects(run):
    result, ctl = run(["stop"], running=("box",))
    assert result.exit_code == 0
    assert result.output.strip() == "stopped box"


def test_auto_select_zero_running_errors(run):
    result, ctl = run(["stop"], running=())
    assert result.exit_code == 1
    assert result.output.strip() == "error: no running VM to auto-select; pass a name"


def test_auto_select_multiple_running_errors(run):
    result, ctl = run(["stop"], running=("a", "b"))
    assert result.exit_code == 1
    assert "error:" in result.output
    assert "multiple running VMs" in result.output
    assert "a, b" in result.output


# --------------------------------------------------------------------------- #
# leading -- marker (ADR-0001, preserved on flattened verbs)                  #
# --------------------------------------------------------------------------- #


def test_leading_dashdash_binds_remaining_positionals(run):
    result, ctl = run(["snapshot", "commit", "--", "s1", "-m", "msg"],
                      running=("box",))
    assert result.exit_code == 0
    assert result.output.strip() == "committed s1 on box"  # auto-selected
    take = _last(ctl, "take")
    assert take["args"] == ["s1"]
    assert take["kwargs"]["description"] == "msg"  # trailing flag still parses


def test_leading_dashdash_on_exec(run):
    result, ctl = run(["exec", "--", "ipconfig"], running=("box",))
    assert result.exit_code == 0
    assert result.output.strip() == "launched on box"
    run_call = _last(ctl, "run")
    assert run_call["args"] == ["ipconfig"]


def test_dashdash_after_option_still_auto_selects(run):
    # `-i` before `--`: the marker must still drop the name and auto-select.
    result, ctl = run(
        ["exec", "-i", "--", r"C:\Windows\System32\notepad.exe"],
        running=("box",),
    )
    assert result.exit_code == 0
    assert result.output.strip() == "launched on box"  # auto-selected
    assert _last(ctl, "run")["kwargs"]["interactive"] is True


def test_dashdash_after_explicit_name_is_conventional_on_exec(run):
    result, ctl = run(["exec", "myvm", "-i", "--", r"C:\x.exe"])
    assert result.exit_code == 0
    assert result.output.strip() == "launched on myvm"
    run_call = _last(ctl, "run")
    assert run_call["args"] == [r"C:\x.exe"]
    assert run_call["kwargs"]["interactive"] is True


def test_non_leading_dashdash_is_conventional(run):
    result, ctl = run(["snapshot", "commit", "myvm", "--", "s1"])
    assert result.exit_code == 0
    assert result.output.strip() == "committed s1 on myvm"
    assert _last(ctl, "take")["args"] == ["s1"]


# --------------------------------------------------------------------------- #
# ps                                                                          #
# --------------------------------------------------------------------------- #


def test_ps_lists_running_only_by_default(monkeypatch):
    ctl = FakeCtl(running=("box",))
    ctl.list_vms = lambda: {"running": ["/vms/box.vmx"],
                            "discovered": {"box": "/vms/box.vmx",
                                           "off": "/vms/off.vmx"}}
    monkeypatch.setattr(cli_mod, "VMCtl", lambda: ctl)
    result = CliRunner().invoke(cli, ["ps"])
    assert result.exit_code == 0
    assert result.output.strip() == render.ps([{"name": "box", "status": "running"}])
    assert "off" not in result.output


def test_ps_all_includes_stopped(monkeypatch):
    runner_data = {"running": ["/vms/box.vmx"],
                   "discovered": {"box": "/vms/box.vmx", "off": "/vms/off.vmx"}}
    monkeypatch.setattr(cli_mod, "VMCtl",
                        lambda: type("C", (), {"list_vms": lambda self: runner_data})())
    result = CliRunner().invoke(cli, ["ps", "-a"])
    assert result.exit_code == 0
    assert result.output.strip() == render.ps([
        {"name": "box", "status": "running"},
        {"name": "off", "status": "stopped"},
    ])


def test_ps_rows_pure():
    data = {"running": [r"C:\VMs\Box.vmx"],
            "discovered": {"box": r"c:\vms\box.vmx", "off": r"C:\VMs\off.vmx"}}
    # Running match is case/separator-insensitive.
    assert _ps_rows(data, show_all=False) == [{"name": "box", "status": "running"}]
    assert _ps_rows(data, show_all=True) == [
        {"name": "box", "status": "running"},
        {"name": "off", "status": "stopped"},
    ]


def test_ps_renders_name_status_table_without_vm_prefix(run):
    result, ctl = run(["ps"])
    assert result.exit_code == 0
    # A header table, not a per-VM `vm:` field (the `vm` key left CLI output).
    assert result.output.startswith("NAME")
    assert "vm:" not in result.output


# --------------------------------------------------------------------------- #
# verb-rename coverage (new verb -> same library method)                      #
# --------------------------------------------------------------------------- #


def test_kill_is_hard_stop(run):
    result, ctl = run(["kill", "myvm"])
    assert result.output.strip() == "killed myvm"
    assert _last(ctl, "stop")["kwargs"]["hard"] is True


def test_stop_is_graceful(run):
    result, ctl = run(["stop", "myvm"])
    assert result.output.strip() == "stopped myvm"
    assert _last(ctl, "stop")["kwargs"]["hard"] is False


def test_restart_maps_to_reset(run):
    result, ctl = run(["restart", "myvm", "-H"])
    assert result.output.strip() == "restarted myvm"
    assert _last(ctl, "reset")["kwargs"]["hard"] is True


def test_snapshot_log_maps_to_list(run):
    result, ctl = run(["snapshot", "log", "myvm"])
    assert result.exit_code == 0
    assert _last(ctl, "list")["module"] == "snapshot"


def test_snapshot_reset_maps_to_revert(run):
    result, ctl = run(["snapshot", "reset", "myvm", "s1"])
    assert result.output.strip() == "reset myvm to s1"
    revert = _last(ctl, "revert")
    assert revert["args"] == ["s1"]
    assert revert["kwargs"]["ensure_running"] is True


def test_snapshot_rm_maps_to_delete(run):
    result, ctl = run(["snapshot", "rm", "myvm", "s1", "-c"])
    assert result.output.strip() == "removed s1 from myvm"
    delete = _last(ctl, "delete")
    assert delete["kwargs"]["delete_children"] is True


def test_network_ls_maps_to_list(run):
    result, ctl = run(["network", "ls", "myvm"])
    assert result.exit_code == 0
    assert _last(ctl, "list")["module"] == "network"


def test_shares_ls_maps_to_list(run):
    result, ctl = run(["shares", "ls", "myvm"])
    assert result.exit_code == 0
    assert _last(ctl, "list")["module"] == "shares"


# --------------------------------------------------------------------------- #
# snapshot commit memory-default logic                                        #
# --------------------------------------------------------------------------- #


class PowerStateVM(FakeVM):
    """FakeVM whose power.state() returns a fixed PowerState, recording take()."""

    def __init__(self, name, power_state):
        super().__init__(name, [])
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
        self.captured = []
        # What run_captured hands back (output + guest exit code). Tests that
        # care about propagation override this before invoking.
        self.capture_result = {"output": "OUT", "exit_code": 0}

    def run(self, program, *args, no_wait=True, interactive=False):
        self.calls.append({"program": program, "args": list(args),
                           "no_wait": no_wait, "interactive": interactive})
        return {"ran": program}

    def run_captured(self, command_line, guest_os, interactive=False):
        self.captured.append({"command_line": command_line, "guest_os": guest_os,
                              "interactive": interactive})
        return self.capture_result


class ExecVM(FakeVM):
    def __init__(self, name, rec, guest_os="windows9-64"):
        super().__init__(name, [])
        self._rec = rec
        self.__dict__["_guest_os"] = guest_os

    @property
    def guest(self):
        return self._rec


@pytest.fixture
def exec_run(monkeypatch):
    def _run(args, guest_os="windows9-64", running=("box",), capture_result=None):
        rec = GuestRecorder()
        if capture_result is not None:
            rec.capture_result = capture_result

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
    assert result.output.strip() == "launched on myvm"
    assert rec.calls == [{"program": "ipconfig", "args": [],
                          "no_wait": False, "interactive": False}]


def test_exec_bare_one_arg_ok(exec_run):
    result, rec = exec_run(["exec", "myvm", "ipconfig", "/all"])
    assert result.exit_code == 0
    assert rec.calls[0]["program"] == "ipconfig"
    assert rec.calls[0]["args"] == ["/all"]


def test_exec_bare_multi_arg_succeeds_as_single_token(exec_run):
    # Mode B: multiple args reconstruct into one re-quoted programArgs token
    # (the old "multiple arguments need a shell" error is gone).
    result, rec = exec_run(["exec", "myvm", "echo", "a", "b"])
    assert result.exit_code == 0
    assert rec.calls == [{"program": "echo", "args": ["a b"],
                          "no_wait": False, "interactive": False}]


def test_exec_tty_routes_to_capture_and_prints_output(exec_run):
    # -t: the joined command line goes to run_captured (not the fire-and-forget
    # run path), and its captured output is printed verbatim, no "launched" line.
    result, rec = exec_run(["exec", "-t", "myvm", "notepad", "foo.txt"],
                           capture_result={"output": "hi there\n", "exit_code": 0})
    assert result.exit_code == 0
    assert rec.calls == []  # not the fire-and-forget path
    assert rec.captured == [{"command_line": "notepad foo.txt",
                             "guest_os": "windows9-64", "interactive": False}]
    assert result.output == "hi there\n"  # verbatim, no decoration


def test_exec_tty_pipeline_passes_full_command_line(exec_run):
    pipeline = ('get-content C:\\log.txt | select-string -simplematch '
                '"server config: <" | select-object -last 1 | set-clipboard')
    result, rec = exec_run(["exec", "-t", "myvm", pipeline])
    assert result.exit_code == 0
    assert rec.captured[0]["command_line"] == pipeline


def test_exec_tty_passes_guest_os_through(exec_run):
    # The CLI hands the guest OS to run_captured (which picks /bin/sh vs
    # PowerShell); it does not build the wrapper itself.
    result, rec = exec_run(["exec", "-t", "myvm", "ls", "-la"], guest_os="ubuntu-64")
    assert result.exit_code == 0
    assert rec.captured == [{"command_line": "ls -la",
                             "guest_os": "ubuntu-64", "interactive": False}]


def test_exec_tty_propagates_guest_exit_code(exec_run):
    # A non-zero guest exit becomes vmctl's exit code, and the output still prints.
    result, rec = exec_run(["exec", "-t", "myvm", "false"],
                           capture_result={"output": "boom\n", "exit_code": 42})
    assert result.exit_code == 42
    assert result.output == "boom\n"


def test_exec_interactive_adds_interactive_and_nowait(exec_run):
    result, rec = exec_run(["exec", "-i", "myvm", r"C:\Windows\System32\notepad.exe"])
    assert result.exit_code == 0
    assert rec.calls == [{
        "program": r"C:\Windows\System32\notepad.exe", "args": [],
        "no_wait": True, "interactive": True,
    }]


def test_exec_it_captures_on_interactive_desktop(exec_run):
    # -it: capture path with interactive=True (run on the interactive desktop).
    result, rec = exec_run(["exec", "-it", "myvm", "notepad"])
    assert result.exit_code == 0
    assert rec.calls == []
    assert rec.captured == [{"command_line": "notepad",
                             "guest_os": "windows9-64", "interactive": True}]


def test_exec_it_parses_same_as_i_t(exec_run):
    combined, rec1 = exec_run(["exec", "-it", "myvm", "notepad"])
    split, rec2 = exec_run(["exec", "-i", "-t", "myvm", "notepad"])
    assert combined.exit_code == 0 and split.exit_code == 0
    assert rec1.captured == rec2.captured


def test_exec_no_program_errors(exec_run):
    result, rec = exec_run(["exec", "myvm"])
    assert result.exit_code == 1
    assert rec.calls == []


# --- _build_exec pure unit tests ---


def test_build_exec_bare():
    assert _build_exec(["ipconfig"]) == ("ipconfig", [])
    assert _build_exec(["ping", "host"]) == ("ping", ["host"])


def test_build_exec_bare_multi_arg_collapses_to_one_token():
    # Mode B: more than one arg now succeeds, collapsed into a single token.
    assert _build_exec(["echo", "a", "b"]) == ("echo", ["a b"])
    assert _build_exec(["ipconfig", "/all", "/more"]) == (
        "ipconfig", ["/all /more"])


def test_build_exec_bare_requotes_arg_with_spaces():
    # A token containing whitespace stays grouped by re-quoting.
    assert _build_exec(
        ["app.exe", r"C:\Program Files\x", "/q"]
    ) == ("app.exe", [r'"C:\Program Files\x" /q'])


def test_build_exec_bare_explicit_powershell_forwards():
    # The explicit-program escape hatch (mode B): powershell.exe written in full
    # forwards as program + single token, no shell wrap.
    # The pipeline token carries whitespace, so mode-B re-quoting wraps it,
    # keeping it one programArgs argument for the guest powershell.exe to reparse.
    assert _build_exec(
        ["powershell.exe", "-command", "get-content x | select-string y"],
    ) == ("powershell.exe", ['-command "get-content x | select-string y"'])


# --------------------------------------------------------------------------- #
# cp (vm:path syntax)                                                         #
# --------------------------------------------------------------------------- #


class CpVM(FakeVM):
    def __init__(self, name, rec):
        super().__init__(name, [])
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
        return result, rec
    return _run


def test_cp_host_to_guest(cp_run):
    result, rec = cp_run(["cp", "./f", r"myvm:C:\dir\f.txt"])
    assert result.exit_code == 0
    assert result.output.strip() == r"copied ./f -> myvm:C:\dir\f.txt"
    assert rec.calls == [("copy_to", "./f", r"C:\dir\f.txt", False)]


def test_cp_guest_to_host(cp_run):
    result, rec = cp_run(["cp", r"myvm:C:\f.txt", "./out"])
    assert result.exit_code == 0
    assert result.output.strip() == r"copied myvm:C:\f.txt -> ./out"
    assert rec.calls == [("copy_from", r"C:\f.txt", "./out", False)]


def test_cp_leading_colon_auto_selects(cp_run):
    result, rec = cp_run(["cp", "./f", r":C:\dir\f.txt"], running=("box",))
    assert result.exit_code == 0
    assert result.output.strip() == r"copied ./f -> box:C:\dir\f.txt"  # auto-selected
    assert rec.calls == [("copy_to", "./f", r"C:\dir\f.txt", False)]


def test_cp_overwrite_flag(cp_run):
    result, rec = cp_run(["cp", "-o", "./f", "myvm:/tmp/f"])
    assert rec.calls == [("copy_to", "./f", "/tmp/f", True)]


def test_cp_drive_letter_is_host_path_not_vm(cp_run):
    # Both sides are host paths (C:\x is a drive path, ./out has no colon).
    result, rec = cp_run(["cp", r"C:\x", "./out"])
    assert result.exit_code == 1
    assert "exactly one" in result.output
    assert rec.calls == []


def test_cp_no_guest_side_errors(cp_run):
    result, rec = cp_run(["cp", "./a", "./b"])
    assert result.exit_code == 1
    assert "exactly one" in result.output


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
    ("in", "inspect"),
    ("re", "restart"),
    ("ex", "exec"),
])
def test_alias_resolves_to_canonical_command(alias, canonical):
    ctx = click.Context(cli)
    assert cli.get_command(ctx, alias) is cli.get_command(ctx, canonical)


def test_alias_ss_log_runs(run):
    result, ctl = run(["ss", "log", "myvm"])
    assert result.exit_code == 0
    assert _last(ctl, "list")["module"] == "snapshot"


def test_alias_re_restarts(run):
    result, ctl = run(["re", "myvm"])
    assert result.exit_code == 0
    assert result.output.strip() == "restarted myvm"
    assert _last(ctl, "reset")["module"] == "power"


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


def test_inspect_renders_curated_summary(monkeypatch):
    class Ctl(FakeCtl):
        def resolve(self, name):
            return InspectVM("box", [])

    monkeypatch.setattr(cli_mod, "VMCtl", lambda: Ctl(("box",)))
    result = CliRunner().invoke(cli, ["inspect", "myvm"])
    assert result.exit_code == 0
    # A curated summary keyed on the canonical name, not the full dump: the
    # power line shows, the raw vmx displayName does not.
    assert result.output.strip() == "box\n  power:    on"


# --------------------------------------------------------------------------- #
# auth set (no vm key; config write)                                          #
# --------------------------------------------------------------------------- #


def test_auth_set_renders_confirmation(run):
    result, ctl = run(["auth", "set", "myvm", "--user", "u", "--password", "p"])
    assert result.exit_code == 0
    assert result.output.strip() == "credentials set for myvm"
    assert ctl.cred_calls == [("myvm", "u", "p")]


def test_auth_set_without_name_is_usage_error(run):
    result, _ = run(["auth", "set", "--user", "u", "--password", "p"])
    assert result.exit_code != 0


# --------------------------------------------------------------------------- #
# clone (top-level; in scope)                                                 #
# --------------------------------------------------------------------------- #


def test_clone_renders_confirmation_and_uses_canonical_name(monkeypatch):
    captured = {}

    def make_ctl():
        ctl = FakeCtl(running=("box",))
        captured["ctl"] = ctl
        return ctl

    monkeypatch.setattr(cli_mod, "VMCtl", make_ctl)
    result = CliRunner().invoke(cli, ["clone", "SRC", "dest"])
    assert result.exit_code == 0
    assert result.output.strip() == "cloned src -> dest"
    assert captured["ctl"].clone_calls == [("src", "dest", False)]


def test_clone_leading_dashdash_auto_selects(monkeypatch):
    captured = {}

    def make_ctl():
        ctl = FakeCtl(running=("box",))
        captured["ctl"] = ctl
        return ctl

    monkeypatch.setattr(cli_mod, "VMCtl", make_ctl)
    result = CliRunner().invoke(cli, ["clone", "--", "dest"])
    assert result.exit_code == 0
    assert result.output.strip() == "cloned box -> dest"
    assert captured["ctl"].clone_calls == [("box", "dest", False)]


# --------------------------------------------------------------------------- #
# error output contract (ADR-0007)                                            #
# --------------------------------------------------------------------------- #


def test_error_is_single_lowercase_line_on_stderr(monkeypatch):
    # `error: <msg>` on stderr, exit 1, clean stdout (no JSON wrapper).
    monkeypatch.setattr(cli_mod, "VMCtl", lambda: FakeCtl(running=()))
    result = CliRunner().invoke(cli, ["stop"])
    assert result.exit_code == 1
    assert result.stdout == ""  # stdout stays clean for pipes
    assert result.stderr.strip() == "error: no running VM to auto-select; pass a name"


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
    result, ctl = run(["clipboard", "push", "myvm", "hello world"])
    assert result.exit_code == 0
    assert result.output.strip() == "clipboard set on myvm"
    push = _last(ctl, "push_text")
    assert push["args"] == ["hello world"]


def test_clipboard_pull_auto_selects(run):
    result, ctl = run(["clipboard", "pull"], running=("box",))
    assert result.exit_code == 0
    assert _last(ctl, "pull_text")["module"] == "clipboard"


def test_clipboard_push_reads_piped_stdin(monkeypatch):
    ctl = FakeCtl(("box",))
    monkeypatch.setattr(cli_mod, "VMCtl", lambda: ctl)
    result = CliRunner().invoke(cli, ["clipboard", "push"], input="piped text")
    assert result.exit_code == 0
    assert result.output.strip() == "clipboard set on box"
    assert _last(ctl, "push_text")["args"] == ["piped text"]


def test_clipboard_push_empty_stdin_errors(monkeypatch):
    monkeypatch.setattr(cli_mod, "VMCtl", lambda: FakeCtl(("box",)))
    result = CliRunner().invoke(cli, ["clipboard", "push"])
    assert result.exit_code == 1
    assert "clipboard text is empty" in result.output
    assert "push -- TEXT" in result.output


def test_clipboard_push_lone_arg_gives_actionable_footgun_error(monkeypatch):
    monkeypatch.setattr(cli_mod, "VMCtl", lambda: FakeCtl(("box",)))
    result = CliRunner().invoke(cli, ["clipboard", "push", "hello"])
    assert result.exit_code == 1
    assert "'hello' was read as the VM name" in result.output
    assert "clipboard push -- hello" in result.output


def test_clipboard_push_dashdash_makes_lone_arg_text(run):
    result, ctl = run(["clipboard", "push", "--", "hello"], running=("box",))
    assert result.exit_code == 0
    assert result.output.strip() == "clipboard set on box"
    assert _last(ctl, "push_text")["args"] == ["hello"]


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
        super().__init__(name, [])
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
        return result, rec
    return _run


def test_sync_explicit_name(sync_run):
    result, rec = sync_run(["sync", "myvm", "--optional"])
    assert result.exit_code == 0
    assert result.output.strip() == "synced myvm"
    assert rec.calls == [("run", True, None, None, None)]


def test_sync_bare_auto_selects(sync_run):
    result, rec = sync_run(["sync"], running=("box",))
    assert result.exit_code == 0
    assert result.output.strip() == "synced box"
    assert rec.calls == [("run", False, None, None, None)]


def test_push_explicit_name_binds_positionals(sync_run):
    result, rec = sync_run(["push", "myvm", "./build", r"C:\app"])
    assert result.exit_code == 0
    assert result.output.strip() == r"pushed ./build -> myvm:C:\app"
    assert rec.calls == [("push", "./build", r"C:\app", None, None)]


def test_push_leading_dashdash_auto_selects(sync_run):
    result, rec = sync_run(["push", "--", "./build", r"C:\app"], running=("box",))
    assert result.exit_code == 0
    assert result.output.strip() == r"pushed ./build -> box:C:\app"
    assert rec.calls == [("push", "./build", r"C:\app", None, None)]


def test_push_passes_credential_override(sync_run):
    result, rec = sync_run(
        ["push", "myvm", "./build", r"C:\app", "-u", "cli", "-p", "new"])
    assert result.exit_code == 0
    assert rec.calls == [("push", "./build", r"C:\app", "cli", "new")]


# --------------------------------------------------------------------------- #
# command resolution                                                          #
# --------------------------------------------------------------------------- #


def test_unknown_command_still_errors(run):
    result, _ = run(["zzz", "myvm"])
    assert result.exit_code != 0
