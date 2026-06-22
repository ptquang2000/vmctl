from unittest.mock import MagicMock, patch

import pytest

from vmctl.modules.clipboard import ClipboardModule

WINDOWS_CONFIG = {"guestOS": "windows9-64", "displayName": "TestVM"}
LINUX_CONFIG = {"guestOS": "ubuntu-64", "displayName": "TestVM"}


def make_module(config_data):
    runner = MagicMock()
    runner.run_vmcli.return_value = '{"guestOS": "%s"}' % config_data["guestOS"]
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
    # Windows push loads the clipboard via cmd.exe -> clip.exe (single token).
    assert any("clip" in c and "cmd.exe" in c for c in calls)


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
