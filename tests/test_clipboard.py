from unittest.mock import MagicMock, patch

import pytest

import vmctl.modules.clipboard as cb
from vmctl.modules.clipboard import ClipboardModule

WINDOWS_CONFIG = {"guestOS": "windows9-64", "displayName": "TestVM"}
LINUX_CONFIG = {"guestOS": "ubuntu-64", "displayName": "TestVM"}

# An interactive desktop session: running + a live copy/paste capability. The
# gate passes on this; a login-screen guest reports copyPasteGuestVersion=0.
_INTERACTIVE = '{"running": true, "GuestCaps": {"copyPasteGuestVersion": 4}}'


def make_module(config_data, tools_query=_INTERACTIVE):
    """Build a module whose runner answers both vmcli queries it makes:

    ``ConfigParams query`` -> guestOS (for guest-type detection) and
    ``Tools Query`` -> the interactive-session facts (for the fail-loud gate).
    """
    runner = MagicMock()

    def _run_vmcli(_vmx, *args):
        if "Tools" in args:
            return tools_query
        return '{"guestOS": "%s"}' % config_data["guestOS"]

    runner.run_vmcli.side_effect = _run_vmcli
    runner.run_vmcli_action.return_value = {"success": True}
    return ClipboardModule("fake.vmx", runner, {"user": "u", "password": "p"})


def test_push_text_windows_uses_clip():
    mod = make_module(WINDOWS_CONFIG)
    with patch("tempfile.NamedTemporaryFile") as mock_tf, \
         patch("os.unlink"):
        mock_tf.return_value.__enter__.return_value.name = "/tmp/fake.txt"
        mock_tf.return_value.__enter__.return_value.write = MagicMock()
        mod.push_text("hello world")
    calls = [str(c) for c in mod._r.run_vmcli_action.call_args_list]
    # Windows push loads the clipboard via cmd.exe -> clip.exe (single token),
    # run --interactive against the absolute cmd path so it hits the desktop's
    # real clipboard rather than a phantom non-interactive one (ADR-0008).
    assert any(
        "clip" in c and "--interactive" in c and r"C:\\Windows\\System32\\cmd.exe" in c
        for c in calls
    )


def test_push_text_linux_uses_xclip():
    mod = make_module(LINUX_CONFIG)
    with patch("tempfile.NamedTemporaryFile") as mock_tf, \
         patch("os.unlink"):
        mock_tf.return_value.__enter__.return_value.name = "/tmp/fake.txt"
        mock_tf.return_value.__enter__.return_value.write = MagicMock()
        mod.push_text("hello world")
    calls = [str(c) for c in mod._r.run_vmcli_action.call_args_list]
    assert any("xclip" in c for c in calls)


def test_is_windows_guest_detection():
    mod = make_module(WINDOWS_CONFIG)
    assert mod._is_windows_guest() is True


def test_is_linux_guest_detection():
    mod = make_module(LINUX_CONFIG)
    assert mod._is_windows_guest() is False


def test_is_unknown_guest_detection():
    runner = MagicMock()
    runner.run_vmcli.return_value = '{"guestOS": "other-os"}'
    mod = ClipboardModule("fake.vmx", runner, {})
    assert mod._is_windows_guest() is False


# --------------------------------------------------------------------------- #
# guest_os_fn injection seam                                                  #
# --------------------------------------------------------------------------- #


def test_injected_guest_os_fn_skips_vmcli_query():
    runner = MagicMock()
    mod = ClipboardModule("fake.vmx", runner, {}, guest_os_fn=lambda: "windows10-64")
    assert mod._is_windows_guest() is True
    runner.run_vmcli.assert_not_called()  # detection used the injected fn


# --------------------------------------------------------------------------- #
# _cred_args                                                                  #
# --------------------------------------------------------------------------- #


def test_cred_args_builds_username_and_password():
    mod = make_module(WINDOWS_CONFIG)  # creds are {"user": "u", "password": "p"}
    assert mod._cred_args() == ["--username", "u", "--password", "p"]


def test_cred_args_empty_when_no_creds():
    runner = MagicMock()
    runner.run_vmcli.return_value = '{"guestOS": "windows9-64"}'
    mod = ClipboardModule("fake.vmx", runner, {})
    assert mod._cred_args() == []


def test_cred_args_partial_only_username():
    runner = MagicMock()
    runner.run_vmcli.return_value = '{"guestOS": "windows9-64"}'
    mod = ClipboardModule("fake.vmx", runner, {"user": "u"})
    assert mod._cred_args() == ["--username", "u"]


# --------------------------------------------------------------------------- #
# push_text: guest-path selection + credentialed copyTo                       #
# --------------------------------------------------------------------------- #


def _push(mod, text="hi"):
    with patch("tempfile.NamedTemporaryFile") as mock_tf, patch("os.unlink"):
        mock_tf.return_value.__enter__.return_value.name = "/tmp/fake.txt"
        mock_tf.return_value.__enter__.return_value.write = MagicMock()
        return mod.push_text(text)


def test_push_text_returns_success():
    assert _push(make_module(WINDOWS_CONFIG)) == {"success": True}


def test_push_text_windows_copies_to_windows_temp_path():
    mod = make_module(WINDOWS_CONFIG)
    _push(mod)
    calls = [str(c) for c in mod._r.run_vmcli_action.call_args_list]
    assert any("copyTo" in c and "vmctl_clip.txt" in c and "Windows" in c for c in calls)


def test_push_text_linux_copies_to_tmp_path():
    mod = make_module(LINUX_CONFIG)
    _push(mod)
    calls = [str(c) for c in mod._r.run_vmcli_action.call_args_list]
    assert any("copyTo" in c and "/tmp/vmctl_clip.txt" in c for c in calls)


def test_push_text_forwards_credentials_to_copyto():
    mod = make_module(WINDOWS_CONFIG)
    _push(mod)
    calls = [str(c) for c in mod._r.run_vmcli_action.call_args_list]
    assert any("copyTo" in c and "--username" in c and "--password" in c for c in calls)


# --------------------------------------------------------------------------- #
# pull_text: windows (poll) vs linux (single read)                            #
# --------------------------------------------------------------------------- #


def test_pull_text_windows_reads_via_powershell_get_clipboard():
    mod = make_module(WINDOWS_CONFIG)
    with patch.object(mod, "_read_guest_file", return_value="clip data"):
        result = mod.pull_text()
    assert result == {"text": "clip data"}
    calls = [str(c) for c in mod._r.run_vmcli_action.call_args_list]
    assert any("Get-Clipboard" in c and "vmctl_clip_out.txt" in c for c in calls)
    assert any("del /q" in c for c in calls)  # stale artifact cleared first
    # Both cmd runs are --interactive against the absolute cmd path (ADR-0008).
    assert all(
        "--interactive" in c and r"C:\\Windows\\System32\\cmd.exe" in c
        for c in calls
    )


def test_pull_text_linux_reads_via_xclip():
    mod = make_module(LINUX_CONFIG)
    with patch.object(mod, "_read_guest_file", return_value="linux clip"):
        result = mod.pull_text()
    assert result == {"text": "linux clip"}
    calls = [str(c) for c in mod._r.run_vmcli_action.call_args_list]
    assert any("xclip" in c and "-o" in c for c in calls)


def test_pull_text_linux_missing_file_yields_empty_string():
    mod = make_module(LINUX_CONFIG)
    with patch.object(mod, "_read_guest_file", return_value=None):
        assert mod.pull_text() == {"text": ""}


# --------------------------------------------------------------------------- #
# fail-loud interactive-session gate (ADR-0008, user stories 5/8/12)          #
# --------------------------------------------------------------------------- #


def _tools_query_calls(mod):
    return [c for c in mod._r.run_vmcli.call_args_list if "Tools" in c.args]


def test_push_queries_tools_before_guest_op():
    mod = make_module(WINDOWS_CONFIG)
    _push(mod)
    assert _tools_query_calls(mod), "push must gate on a Tools Query first"


def test_pull_queries_tools_before_guest_op():
    mod = make_module(WINDOWS_CONFIG)
    with patch.object(mod, "_read_guest_file", return_value="x"):
        mod.pull_text()
    assert _tools_query_calls(mod), "pull must gate on a Tools Query first"


def test_push_raises_when_no_interactive_session():
    mod = make_module(WINDOWS_CONFIG, tools_query='{"running": true, "GuestCaps": {"copyPasteGuestVersion": 0}}')
    with pytest.raises(cb.VMCtlError, match="copyPasteGuestVersion=0"):
        _push(mod)
    # Fail loud BEFORE touching the guest -- no copyTo/clip fired.
    mod._r.run_vmcli_action.assert_not_called()


def test_pull_raises_when_no_interactive_session():
    mod = make_module(WINDOWS_CONFIG, tools_query='{"running": true, "GuestCaps": {"copyPasteGuestVersion": 0}}')
    with pytest.raises(cb.VMCtlError, match="copyPasteGuestVersion=0"):
        mod.pull_text()
    mod._r.run_vmcli_action.assert_not_called()


def test_gate_raises_when_not_running():
    mod = make_module(WINDOWS_CONFIG, tools_query='{"running": false, "GuestCaps": {"copyPasteGuestVersion": 4}}')
    with pytest.raises(cb.VMCtlError):
        _push(mod)


def test_gate_passes_when_capability_present():
    # copyPasteGuestVersion > 0 AND running -> no raise (the interactive case).
    _push(make_module(WINDOWS_CONFIG))  # _INTERACTIVE default; would raise if gated wrong


def test_linux_push_is_not_gated():
    # No proven equivalent signal on Linux; the xclip path carries no gate and
    # must not issue a Tools Query.
    mod = make_module(LINUX_CONFIG, tools_query="unused")
    _push(mod)
    assert not _tools_query_calls(mod)


# --------------------------------------------------------------------------- #
# _read_guest_file                                                            #
# --------------------------------------------------------------------------- #


def test_read_guest_file_returns_copied_text():
    mod = make_module(WINDOWS_CONFIG)

    def fake_copy_from(guest_path, host_path):
        with open(host_path, "w", encoding="utf-8") as fh:
            fh.write("round-tripped")

    with patch.object(mod, "_copy_from", side_effect=fake_copy_from):
        assert mod._read_guest_file("C:\\guest.txt") == "round-tripped"


def test_read_guest_file_returns_none_on_copy_failure():
    mod = make_module(WINDOWS_CONFIG)
    with patch.object(mod, "_copy_from", side_effect=Exception("boom")):
        assert mod._read_guest_file("C:\\missing.txt") is None


# --------------------------------------------------------------------------- #
# _poll_guest_file: retry until content, and bounded timeout                  #
# --------------------------------------------------------------------------- #


def test_poll_guest_file_retries_until_content(monkeypatch):
    mod = make_module(WINDOWS_CONFIG)
    monkeypatch.setattr(cb.time, "time", lambda: 0.0)  # never hits the deadline
    monkeypatch.setattr(cb.time, "sleep", lambda _s: None)
    with patch.object(mod, "_read_guest_file", side_effect=[None, "", "ready"]):
        assert mod._poll_guest_file("C:\\out.txt") == "ready"


def test_poll_guest_file_times_out_to_empty(monkeypatch):
    mod = make_module(WINDOWS_CONFIG)
    # time(): deadline calc -> 0, first loop check -> 0 (<25, enter), next -> 1000 (exit)
    ticks = iter([0.0, 0.0, 1000.0])
    monkeypatch.setattr(cb.time, "time", lambda: next(ticks))
    monkeypatch.setattr(cb.time, "sleep", lambda _s: None)
    with patch.object(mod, "_read_guest_file", return_value=""):
        assert mod._poll_guest_file("C:\\out.txt") == ""
