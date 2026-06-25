"""Unit tests for ``vm.sync`` (SyncModule) -- no network, no VM, no real sss.

Mock-light, like ``tests/test_network.py``: inject fakes for ``network`` /
``power`` and a fake ``sss`` module via ``sys.modules`` so the module's lazy
``import sss`` resolves to it. Asserts target resolution (running + non-empty
IP), credential pass-through, profile-required gating, and ``SssError`` wrapping.
"""

import sys
import types
from unittest.mock import MagicMock

import pytest

from vmctl.modules.sync import SyncModule
from vmctl.exceptions import VMCtlError


class _FakeSssError(Exception):
    pass


def _make_fake_sss(session):
    """A stand-in ``sss`` module exposing ``connect`` (returns ``session``) and
    ``SssError``. ``connect`` is a MagicMock so calls/kwargs can be asserted."""
    mod = types.ModuleType("sss")
    mod.SssError = _FakeSssError
    mod.connect = MagicMock(return_value=session)
    return mod


def _make_session(profile=object(), lifecycle=None, path=None, raises=None):
    """A fake ``Sss`` session usable as a context manager (``with session``)."""
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    session.profile = profile
    if raises is not None:
        session.run_lifecycle.side_effect = raises
        session.sync.path.side_effect = raises
    else:
        session.run_lifecycle.return_value = lifecycle or {"sync": "ok"}
        session.sync.path.return_value = path or {"copied": 1}
    return session


def _make_module(state="on", ip="10.0.0.5", credentials=None):
    network = MagicMock()
    network.ip.return_value = {"ip": ip}
    power = MagicMock()
    power.state.return_value = {"PowerState": state}
    return SyncModule(network, power, credentials)


@pytest.fixture
def fake_sss(monkeypatch):
    """Install a fake ``sss`` module; tests set ``.session`` to control it."""
    holder = {}

    def install(session):
        mod = _make_fake_sss(session)
        monkeypatch.setitem(sys.modules, "sss", mod)
        holder["mod"] = mod
        return mod

    holder["install"] = install
    return holder


def test_run_not_running_raises_and_skips_sss(fake_sss):
    mod = _make_module(state="suspended")
    fake = fake_sss["install"](_make_session())
    with pytest.raises(VMCtlError, match="not running"):
        mod.run()
    fake.connect.assert_not_called()


def test_run_running_but_no_ip_raises_and_skips_sss(fake_sss):
    mod = _make_module(state="on", ip="")
    fake = fake_sss["install"](_make_session())
    with pytest.raises(VMCtlError, match="no guest IP"):
        mod.run()
    fake.connect.assert_not_called()


def test_run_passes_host_and_credentials(fake_sss):
    creds = {"user": "test", "password": "secret"}
    mod = _make_module(state="on", ip="192.168.1.20", credentials=creds)
    fake = fake_sss["install"](_make_session())
    mod.run()
    _, kwargs = fake.connect.call_args
    assert kwargs["host"] == "192.168.1.20"
    assert kwargs["user"] == "test"
    assert kwargs["password"] == "secret"


def test_run_no_credentials_passes_none(fake_sss):
    # User Story 6: no registered creds -> None/None, so sss can use key/agent.
    mod = _make_module(state="on", ip="192.168.1.20", credentials=None)
    fake = fake_sss["install"](_make_session())
    mod.run()
    _, kwargs = fake.connect.call_args
    assert kwargs["user"] is None
    assert kwargs["password"] is None


def test_run_forwards_sync_optional_and_project_dir(fake_sss):
    mod = _make_module()
    session = _make_session()
    fake = fake_sss["install"](session)
    mod.run(sync_optional=True, project_dir="/proj")
    _, kwargs = fake.connect.call_args
    assert kwargs["project_dir"] == "/proj"
    session.run_lifecycle.assert_called_once_with(sync_optional=True)


def test_run_raises_when_no_profile_resolved(fake_sss):
    mod = _make_module()
    session = _make_session(profile=None)
    fake_sss["install"](session)
    with pytest.raises(VMCtlError, match="No sss sync profile"):
        mod.run()
    session.run_lifecycle.assert_not_called()


def test_run_wraps_ssserror(fake_sss):
    mod = _make_module()
    session = _make_session(raises=_FakeSssError("boom"))
    fake_sss["install"](session)
    with pytest.raises(VMCtlError, match="boom"):
        mod.run()


def test_push_passes_source_dest_and_host(fake_sss):
    mod = _make_module(state="on", ip="10.1.2.3",
                       credentials={"user": "u", "password": "p"})
    session = _make_session(path={"copied": 3})
    fake = fake_sss["install"](session)
    result = mod.push("./build", r"C:\app")
    assert result == {"copied": 3}
    _, kwargs = fake.connect.call_args
    assert kwargs["host"] == "10.1.2.3"
    session.sync.path.assert_called_once_with("./build", r"C:\app")


def test_push_not_running_raises_and_skips_sss(fake_sss):
    mod = _make_module(state="off")
    fake = fake_sss["install"](_make_session())
    with pytest.raises(VMCtlError, match="not running"):
        mod.push("./build", r"C:\app")
    fake.connect.assert_not_called()


def test_push_wraps_ssserror(fake_sss):
    mod = _make_module()
    session = _make_session(raises=_FakeSssError("sftp failed"))
    fake_sss["install"](session)
    with pytest.raises(VMCtlError, match="sftp failed"):
        mod.push("./build", r"C:\app")


def test_missing_sss_install_raises_actionable(monkeypatch):
    # Lazy import: if sss isn't installed, surface an actionable VMCtlError.
    monkeypatch.setitem(sys.modules, "sss", None)  # forces ImportError
    mod = _make_module()
    with pytest.raises(VMCtlError, match="sss is not installed"):
        mod.run()
