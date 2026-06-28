"""
Live integration tests for vmctl guest-operation modules.

These tests drive a real VM and require:

  * VMware Workstation installed.
  * A VM named ``vmctl`` with a ``init`` snapshot. This is a
    *suspended, logged-in memory snapshot* (VMware Tools installed, guest
    credentials ``test`` / ``test``): taken while logged into the desktop so
    that ``revert`` + ``power start`` *resumes* a live interactive session
    rather than cold-booting to the login screen. See PRD-integration-provisioning.md
    for the one-time provisioning procedure.
  * vmctl config at ``~/.vmctl/config.json`` with that VM in scan_roots and
    credentials registered for it.

Fixtures are module-scoped and grouped by domain (fs, guest, clipboard, vars).
Each fixture reverts the VM to ``init``, boots it once, waits for an
interactive desktop session (see ``_wait_for_tools``), yields the live ``VM``
object, and powers the VM off on teardown. One boot cycle per group; a failure
in one group does not affect the others.

Verification pattern: fire-and-forget guest commands cannot be checked by
stdout, so tests write an artifact to a known guest path, copy it back to the
host, and assert on the host-side content.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import warnings

import pytest

from sss import Sss, connect
from sss.config import Profile
from sss.sync import SyncEngine
from vmctl import VMCtl
from vmctl.exceptions import VMCtlError

VM_NAME = "vmctl"
SNAPSHOT = "init"
TOOLS_TIMEOUT_S = 180
TOOLS_POLL_S = 5


def _wait_for_tools(vm) -> None:
    """Block until an interactive desktop session exists, or fail after a timeout.

    ``running`` alone is insufficient: it flips ``True`` while the VM still sits
    at the login screen, so the clipboard test (which runs ``--interactive``
    PowerShell) would race the login. The per-user-session Tools agent
    (``vmtoolsd -n vmusr``) only reports a copy/paste capability once an
    interactive desktop exists -- verified live, ``GuestCaps.copyPasteGuestVersion``
    reads ``0`` at the login screen and ``> 0`` when logged in. Gate on both
    signals from the same single query so the suspended-logged-in ``init``
    snapshot is confirmed resumed before any guest op runs.
    """
    deadline = time.time() + TOOLS_TIMEOUT_S
    last = None
    while time.time() < deadline:
        try:
            last = vm.tools.query()
        except Exception as e:  # tools not yet responsive during early boot
            last = {"error": str(e)}
        else:
            running = last.get("running") is True
            copy_paste = last.get("GuestCaps", {}).get("copyPasteGuestVersion", 0)
            if running and copy_paste > 0:
                return
        time.sleep(TOOLS_POLL_S)
    pytest.fail(f"VMware Tools never reported an interactive session within "
                f"{TOOLS_TIMEOUT_S}s (last query: {last})")


def _boot_clean_vm():
    """Revert to the init snapshot, boot, and wait for Tools.

    Hard-stop the VM before reverting. Fixtures are module-scoped and coexist,
    so a prior group's teardown ``power.stop`` fires only at end-of-module --
    after later groups set up. ``snapshot.revert`` faithfully surfaces vmcli's
    "VM must be off" constraint, so reverting a still-online VM errors with
    "VM is in an invalid state (online)". A pre-revert stop is not additionally
    destructive (revert discards running state anyway); errors are ignored when
    the VM is already off.
    """
    vm = VMCtl().get(VM_NAME)
    try:
        vm.power.stop(hard=True)
    except Exception:
        pass
    vm.snapshot.revert(SNAPSHOT)
    vm.power.start(gui=False)  # headless -- no Workstation console window
    _wait_for_tools(vm)
    return vm


# Fixed name (a random one is impossible -- Math.random/Date.now unavailable --
# and a fixed name is what makes idempotent purging possible) and the cmd-field
# marker for the long-lived probe process.
LIVETEST_SNAPSHOT = "vmctl-livetest-mem"
PING_MARKER = "ping -n 99999"


def _purge_snapshot(vm, name) -> None:
    """Idempotently delete every snapshot matching ``name``, draining duplicates.

    ``_resolve_uid`` returns the *first* match on a duplicate display name, and
    VMware permits duplicate names, so a prior crashed run can leave several
    ``name`` snapshots stranded in the tree. Loop ``delete(delete_children=True)``
    until ``_resolve_uid`` raises "not found". Cleanup failures are surfaced
    loudly (``warnings.warn``) rather than masked with a silent ``except: pass``
    -- silent tree pollution reads as "all clean" when it isn't.
    """
    while True:
        try:
            vm.snapshot.delete(name, delete_children=True)
        except ValueError:
            return  # _resolve_uid: no more matches -> fully drained
        except Exception as e:  # runner/vmcli failure -- warn but don't spin
            warnings.warn(f"failed to purge snapshot {name!r}: {e}")
            return


def _revert_init_and_purge(vm) -> None:
    """Stop, revert to ``init``, then purge the live-test snapshot. Leaves VM off.

    Off-revert-purge ordering (respects the VM-must-be-off constraint): reverting
    to ``init`` detaches "current" from the test snapshot so it deletes cleanly.
    Used on both fixture setup (recover a snapshot stranded by a crashed run) and
    teardown (don't pollute the tree for the next run).
    """
    try:
        vm.power.stop(hard=True)
    except Exception:
        pass
    vm.snapshot.revert(SNAPSHOT)
    _purge_snapshot(vm, LIVETEST_SNAPSHOT)


def _make_group_fixture():
    """Build a module-scoped fixture that yields a freshly booted VM."""
    vm = _boot_clean_vm()
    try:
        yield vm
    finally:
        try:
            vm.power.stop(hard=True)
        except Exception:
            pass


@pytest.fixture(scope="module")
def fs_vm():
    yield from _make_group_fixture()


@pytest.fixture(scope="module")
def guest_vm():
    yield from _make_group_fixture()


@pytest.fixture(scope="module")
def clipboard_vm():
    yield from _make_group_fixture()


@pytest.fixture(scope="module")
def vars_vm():
    yield from _make_group_fixture()


@pytest.fixture(scope="module")
def snapshot_vm():
    """Dedicated boot for the live snapshot-lifecycle test.

    The test does ``stop -> revert -> start`` mid-execution, which wipes any
    sibling test's state and resets the snapshot pointer, so it cannot share a
    group fixture -- it always needs its own boot. Setup and teardown both purge
    the fixed-name live-test snapshot (idempotent dual-side): the setup-side
    purge recovers from a prior run that hard-crashed mid-test and stranded a
    snapshot.
    """
    vm = VMCtl().get(VM_NAME)
    _revert_init_and_purge(vm)
    vm.power.start(gui=False)  # headless
    _wait_for_tools(vm)
    try:
        yield vm
    finally:
        _revert_init_and_purge(vm)


# --------------------------------------------------------------------------- #
# fs_vm group                                                                 #
# --------------------------------------------------------------------------- #

TEST_DIR = r"C:\vmctl-test"


def test_fs_mkdir(fs_vm):
    result = fs_vm.fs.mkdir(TEST_DIR)
    assert result["success"] is True


def test_fs_mktemp_default_dir(fs_vm):
    result = fs_vm.fs.create_temp_file()
    path = result["path"]
    assert path.startswith(r"C:\Windows\Temp")
    assert "vmctl_" in path


def test_fs_ls_empty_dir(fs_vm):
    result = fs_vm.fs.ls(TEST_DIR)
    assert result["entries"] == []


def test_fs_stage_file_via_copy(fs_vm):
    """Stage hello.txt for the mv/rm chain by copying a host file into the guest.

    Uses ``copy_to`` rather than an in-guest shell redirect: ``vmcli Guest run``
    accepts only a single programArgs token, so ``cmd.exe /c echo ... > file``
    (program + multiple tokens) is rejected. ``copy_to`` is the canonical,
    verified staging path; the dedicated ``guest.run`` coverage lives in the
    guest group (``test_guest_run_writes_artifact``).
    """
    payload = "hello"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".txt", delete=False
    ) as f:
        f.write(payload)
        host_in = f.name
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        host_out = f.name
    try:
        fs_vm.guest.copy_to(host_in, rf"{TEST_DIR}\hello.txt", overwrite=True)
        fs_vm.guest.copy_from(rf"{TEST_DIR}\hello.txt", host_out, overwrite=True)
        with open(host_out, encoding="utf-8", errors="replace") as f:
            content = f.read()
    finally:
        os.unlink(host_in)
        os.unlink(host_out)
    assert "hello" in content


def test_fs_mv(fs_vm):
    fs_vm.fs.mv(rf"{TEST_DIR}\hello.txt", rf"{TEST_DIR}\moved.txt")
    result = fs_vm.fs.ls(TEST_DIR)
    assert "moved.txt" in result["entries"]


def test_fs_rm(fs_vm):
    result = fs_vm.fs.rm(rf"{TEST_DIR}\moved.txt")
    assert result["success"] is True


def test_fs_rmdir(fs_vm):
    result = fs_vm.fs.rmdir(TEST_DIR)
    assert result["success"] is True


def test_fs_env(fs_vm):
    result = fs_vm.fs.env()
    # Env var names keep the guest's literal casing -- Windows reports "Path",
    # Linux "PATH" -- and the library must not normalize it (cross-platform
    # contract). Windows env names are case-insensitive, so assert that way.
    names = {k.lower() for k in result["env"]}
    assert "path" in names


# --------------------------------------------------------------------------- #
# guest_vm group                                                              #
# --------------------------------------------------------------------------- #


def test_guest_ps(guest_vm):
    result = guest_vm.guest.ps()
    procs = result["processes"]
    assert isinstance(procs, list) and procs, "expected a non-empty process list"
    # Each entry parsed from `-f json` carries a pid and a name.
    assert all("pid" in p and "name" in p for p in procs)
    # VMware Tools must be running for the fixture to have booted, so its
    # daemon is a reliable known process to assert on (not a tautology).
    names = {p.get("name", "").lower() for p in procs}
    assert any("vmtoolsd" in n for n in names)


def test_guest_run_writes_artifact(guest_vm):
    """Exercise guest.run end-to-end via the artifact pattern.

    guest.run is fire-and-forget, so verify it ran by having it produce a file
    and copying that back. vmcli Guest run takes a single programArgs token, so
    the whole command is one cmd.exe ``/c`` string; run synchronously (no_wait
    off) since cmd's builtin echo+redirect is a direct child that completes
    before the call returns.
    """
    marker = "guest-run-artifact-42"
    guest_path = r"C:\Windows\Temp\vmctl_run_artifact.txt"
    guest_vm.guest.run("cmd.exe", rf"/c echo {marker}> {guest_path}", no_wait=False)
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        host_out = f.name
    try:
        guest_vm.guest.copy_from(guest_path, host_out, overwrite=True)
        with open(host_out, encoding="utf-8", errors="replace") as f:
            content = f.read()
    finally:
        os.unlink(host_out)
    assert marker in content


def test_guest_copy_roundtrip(guest_vm):
    guest_vm.fs.mkdir(TEST_DIR)
    payload = "round-trip payload"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".txt", delete=False
    ) as f:
        f.write(payload)
        host_in = f.name
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        host_out = f.name
    try:
        guest_vm.guest.copy_to(host_in, rf"{TEST_DIR}\in.txt", overwrite=True)
        guest_vm.guest.copy_from(rf"{TEST_DIR}\in.txt", host_out, overwrite=True)
        with open(host_out, encoding="utf-8", errors="replace") as f:
            content = f.read()
    finally:
        os.unlink(host_in)
        os.unlink(host_out)
    assert content.strip() == payload


# --- sync/push (sss over SSH) -------------------------------------------------
# These share the guest_vm boot (no new cycle). They require the prerequisite an
# OpenSSH server in the ``init`` snapshot reachable as test/test on port 22 (see
# tests/INTEGRATION.md); until that exists they skip rather than fail, leaving
# the rest of the suite unaffected. Clean cross-check: sss writes over SSH, vmctl
# reads back over Tools.
SYNC_DIR = r"C:\vmctl-sync-test"


def _resolve_guest_ip(vm, timeout_s=90, poll_s=3) -> str:
    """Poll until the guest reports an IP, or return "" after ``timeout_s``.

    ``_wait_for_tools`` gates on the interactive Tools session, NOT the network
    lease -- so right after a memory-snapshot resume the NIC may not yet hold a
    DHCP lease, and ``vmrun getGuestIPAddress`` *raises* "Unable to get the IP
    address" (not an empty string) until it does. sync's design is single-read /
    no-poll because the *caller* readies the guest; this harness is that caller,
    so it waits for the address here before driving sync over SSH.
    """
    def _ip():
        try:
            return vm.network.ip().get("ip", "")
        except VMCtlError:
            return ""
    return _poll(_ip, timeout_s=timeout_s, poll_s=poll_s) or ""


def _require_sshd(vm) -> str:
    """Wait for the guest IP + a reachable sshd on port 22; skip if absent."""
    ip = _resolve_guest_ip(vm)
    if not ip:
        pytest.skip(
            "guest never reported an IP -- the init snapshot needs a connected "
            "NIC; see tests/INTEGRATION.md"
        )

    def _port_open():
        try:
            with socket.create_connection((ip, 22), timeout=5):
                return True
        except OSError:
            return False

    if not _poll(_port_open, timeout_s=30, poll_s=3):
        pytest.skip(
            f"no sshd reachable at {ip}:22 -- the init snapshot needs an OpenSSH "
            "server (test/test); see tests/INTEGRATION.md"
        )
    return ip


def test_sync_push_lands_file(guest_vm):
    """``vm.sync.push`` a host file into a guest dir; read it back over Tools."""
    _require_sshd(guest_vm)
    payload = "pushed-over-ssh-7"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".txt", delete=False
    ) as f:
        f.write(payload)
        host_in = f.name
    basename = os.path.basename(host_in)
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        host_out = f.name
    try:
        result = guest_vm.sync.push(host_in, SYNC_DIR)
        assert result["uploaded_count"] >= 1
        # vmctl reads back over Tools -- the cross-channel confirmation.
        listing = guest_vm.fs.ls(SYNC_DIR)
        assert basename in listing["entries"]
        guest_vm.guest.copy_from(rf"{SYNC_DIR}\{basename}", host_out, overwrite=True)
        with open(host_out, encoding="utf-8", errors="replace") as f:
            content = f.read()
    finally:
        os.unlink(host_in)
        os.unlink(host_out)
    assert content.strip() == payload


def test_sync_lifecycle_injected_profile(guest_vm):
    """``vm.sync.run`` with an injected throwaway Profile + base_dir (touches no
    real ~/.sss/config.json); assert the mapped file landed in the guest."""
    _require_sshd(guest_vm)
    from sss import Profile

    payload = "lifecycle-mapped-file-9"
    base_dir = tempfile.mkdtemp()
    src_name = "mapped.txt"
    with open(os.path.join(base_dir, src_name), "w", encoding="utf-8") as f:
        f.write(payload)
    dest_dir = SYNC_DIR + r"\lifecycle"
    profile = Profile(name="test-injected", source_files={src_name: dest_dir})

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        host_out = f.name
    try:
        result = guest_vm.sync.run(profile=profile, base_dir=base_dir)
        assert result["sync"]["uploaded_count"] >= 1
        guest_vm.guest.copy_from(rf"{dest_dir}\{src_name}", host_out, overwrite=True)
        with open(host_out, encoding="utf-8", errors="replace") as f:
            content = f.read()
    finally:
        os.unlink(host_out)
        os.unlink(os.path.join(base_dir, src_name))
        os.rmdir(base_dir)
    assert content.strip() == payload


# --------------------------------------------------------------------------- #
# clipboard_vm group                                                          #
# --------------------------------------------------------------------------- #


def test_clipboard_roundtrip(clipboard_vm):
    clipboard_vm.clipboard.push_text("hello clipboard")
    result = clipboard_vm.clipboard.pull_text()
    assert result["text"].strip() == "hello clipboard"


def test_clipboard_push_pipes_stdin_via_cli(clipboard_vm):
    """Live end-to-end of the piped-stdin path: a real OS pipe into the actual
    CLI (`echo <text> | vmctl clipboard push`) must land in the guest clipboard.

    The unit tests stub stdin in-process via ``CliRunner(input=...)``; this proves
    the real plumbing connects -- a child process with a genuine non-tty stdin,
    real ``~/.vmctl`` config resolution, and the live guest. The name is omitted,
    so the CLI auto-selects the single running VM (the booted ``vmctl``)."""
    text = "piped via cli"
    proc = subprocess.run(
        [sys.executable, "-c", "import vmctl.cli as c; c.cli()", "clipboard", "push"],
        input=text.encode("utf-8"),
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    payload = json.loads(proc.stdout.decode("utf-8"))
    assert payload == {"vm": VM_NAME, "success": True}

    result = clipboard_vm.clipboard.pull_text()
    assert result["text"].strip() == text


# --------------------------------------------------------------------------- #
# vars_vm group                                                               #
# --------------------------------------------------------------------------- #


def test_vars_guest_var_roundtrip(vars_vm):
    vars_vm.vars.write("guestVar", "testkey", "testvalue")
    result = vars_vm.vars.read("guestVar", "testkey")
    assert result["value"] == "testvalue"


def test_vars_guest_env_roundtrip(vars_vm):
    vars_vm.vars.write("guestEnv", "VMCTL_TEST", "envvalue")
    result = vars_vm.vars.read("guestEnv", "VMCTL_TEST")
    assert result["value"] == "envvalue"


# --------------------------------------------------------------------------- #
# snapshot_vm group                                                           #
# --------------------------------------------------------------------------- #


def _marker_in(p) -> bool:
    """True if process ``p``'s command line carries the ping marker.

    Live ground truth (verified against vmctl): vmcli ``Guest ps -f
    json`` puts the full command line of the ``cmd.exe`` parent in its ``name``
    field (``"cmd.exe" /c ping -n 99999 127.0.0.1``) and omits ``cmd`` for that
    entry; the child ``PING.EXE`` has no marker. So match the marker against
    ``name`` and ``cmd`` together -- on the marker, never a bare process name
    (many entries share ``cmd.exe`` / ``PING.EXE``)."""
    return PING_MARKER in (p.get("name", "") + " " + p.get("cmd", ""))


def _is_alive(p) -> bool:
    """True if process ``p`` is still running (not a retained exit record).

    Live ground truth: vmcli ``Guest ps`` does NOT drop terminated processes --
    it keeps them in the table with a non-zero ``eCode`` and an ``eTime`` (exit
    time). A live process reads ``eCode "0"`` and ``eTime "0"``; a killed one
    flips to ``eCode "1"`` with ``eTime`` set, and a clean exit keeps ``eCode
    "0"`` but sets ``eTime``. So ``eTime == "0"`` is the reliable still-running
    signal. All ps fields are strings, so compare as strings."""
    return p.get("eCode") == "0" and p.get("eTime") == "0"


def _find_live_marked_pid(vm):
    """Return the pid (a string -- ps fields are all strings) of the live
    marker-carrying process, or ``None`` if it is absent or only present as an
    exited record."""
    for p in vm.guest.ps()["processes"]:
        if _marker_in(p) and _is_alive(p):
            return p.get("pid")
    return None


def _poll(predicate, timeout_s, poll_s=1):
    """Poll ``predicate`` until it returns truthy or the timeout elapses; return
    its last value."""
    deadline = time.time() + timeout_s
    value = predicate()
    while not value and time.time() < deadline:
        time.sleep(poll_s)
        value = predicate()
    return value


def test_snapshot_memory_resume(snapshot_vm):
    """Prove ``take(memory=True)`` + ``revert`` *resumes a live guest* rather than
    cold-booting -- the load-bearing assumption the whole harness leans on.

    A disk snapshot + cold boot would also restore files and relaunch startup
    processes, so file/disk markers prove nothing. The assertion target is
    therefore VOLATILE state: a specific PID, killed and never relaunched,
    reappearing can only come from a restored RAM image.
    """
    vm = snapshot_vm

    # 1. Launch a long-lived, identifiable, no-GUI process. The whole command is
    #    a single ``/c`` token (vmcli Guest run accepts only one programArgs
    #    token); ``ping -n 99999`` both keeps the cmd.exe parent alive (cmd /c
    #    waits for ping) and tags its command line.
    vm.guest.run("cmd.exe", f"/c {PING_MARKER} 127.0.0.1", no_wait=True)

    # 2. Find it by the command-line marker and record its pid (--noWait returns
    #    before ps necessarily sees it, so poll).
    pid = _poll(lambda: _find_live_marked_pid(vm), timeout_s=30)
    assert pid is not None, f"marked process ({PING_MARKER!r}) never appeared in ps"

    # 3. Capture memory state while the process is alive.
    vm.snapshot.take(LIVETEST_SNAPSHOT, memory=True)

    # 4. Kill it and confirm it is no longer alive. vmcli ps keeps the killed
    #    pid as an exited record (eCode "1", eTime set), so "gone" means no
    #    *live* marker process remains, not absence from the table.
    vm.guest.kill(int(pid))
    gone = _poll(lambda: _find_live_marked_pid(vm) is None, timeout_s=15)
    assert gone, f"killed process ({PING_MARKER!r}) still alive after kill"

    # 5. Revert to the memory snapshot. The library now owns the lifecycle: with
    #    the VM running, revert(..., ensure_running=True) hard-stops it, reverts,
    #    and starts it again in one call -- exercising the running-VM auto-stop
    #    path and leaving the VM running (no manual stop/start here).
    vm.snapshot.revert(LIVETEST_SNAPSHOT, ensure_running=True, gui=False)
    _wait_for_tools(vm)

    # 6a. PID survival -- the hard, cold-boot-impossible assertion. The SAME pid
    #     AND the cmd marker alive again can only come from a restored memory
    #     image; pid-AND-marker together defeats the theoretical OS PID-reuse
    #     race.
    resumed = _poll(
        lambda: next(
            (
                p
                for p in vm.guest.ps()["processes"]
                if p.get("pid") == pid and _marker_in(p) and _is_alive(p)
            ),
            None,
        ),
        timeout_s=30,
    )
    assert resumed is not None, (
        f"pid {pid} with marker {PING_MARKER!r} did not survive the memory "
        f"revert -- the snapshot cold-booted instead of resuming the RAM image"
    )

    # 6b. Fast interactive-resume signal (secondary). _wait_for_tools already
    #     gated on it, but assert directly: a logged-in desktop resumed within
    #     seconds (copyPasteGuestVersion > 0), not a cold boot to a login screen.
    q = vm.tools.query()
    assert q.get("running") is True
    assert q.get("GuestCaps", {}).get("copyPasteGuestVersion", 0) > 0


# --------------------------------------------------------------------------- #
# sss group                                                                   #
# --------------------------------------------------------------------------- #
# Live coverage of sss's *own* primitives (exec / service / sync / push /     #
# files / process) over real SSH. Moved here from sss's own test suite per    #
# ADR-0004 (sss/docs/adr/0004): sss stays target-agnostic and never imports   #
# vmctl, so any harness that boots a VM and drives sss against it belongs in   #
# vmctl's suite. vmctl resolves the guest (IP + stored creds) and hands sss a  #
# plain host -- the exact production handoff path (ADR-0003).                  #


def _win(path: str) -> str:
    return path.replace("/", "\\")


@pytest.fixture(scope="module")
def sss_conn():
    """Connection params (host/user/password) for the freshly booted guest.

    Boots the same headless ``init`` VM the other groups use, waits for a
    reachable sshd, and resolves vmctl's stored guest credentials via the same
    resolver production uses. Yields a dict so tests can open *additional*
    independent sessions (the session-survival test needs a second connect).
    """
    vm = _boot_clean_vm()
    ip = _require_sshd(vm)
    user, password = vm.sync._resolve_credentials(None, None)
    try:
        yield {"host": ip, "user": user, "password": password}
    finally:
        try:
            vm.power.stop(hard=True)
        except Exception:
            pass


@pytest.fixture(scope="module")
def session(sss_conn):
    """A connected sss ``Sss`` session against the booted guest over SSH."""
    s = connect(**sss_conn)
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def sandbox(session):
    """A unique scratch dir under the guest's TEMP, removed on teardown.

    Every destructive op operates inside here, so no real service, process, or
    install path is ever touched. Cleanup runs even when the test fails.
    """
    out = session.exec("echo %TEMP%")["stdout"].strip()
    if not out or "%" in out:  # non-cmd shell left it unexpanded
        out = r"C:\Windows\Temp"
    temp = out.replace("\\", "/").rstrip("/")
    token = uuid.uuid4().hex[:12]
    scratch = f"{temp}/sss-it-{token}"
    session._conn.mkdir_p(scratch)
    try:
        yield {"dir": scratch, "token": token}
    finally:
        session.files.delete([scratch])


def test_sss_exec_roundtrip(session):
    result = session.exec("echo sss-live")
    assert result["exit_code"] == 0
    assert "sss-live" in result["stdout"]


def test_sss_service_query_does_not_crash(session):
    # Query-only on the live target: a bogus service is reported not_found,
    # never raised. (The force-kill path is covered by unit tests.)
    result = session.service.stop("sss-nonexistent-service", timeout=0)
    assert result["success"] is False and result["reason"] == "not_found"


def test_sss_sync_uploads_then_skips(session, sandbox, tmp_path):
    """SyncEngine over real SFTP: a fresh file uploads, an unchanged one skips."""
    src = tmp_path / "payload"
    src.mkdir()
    (src / "hello.txt").write_text("sss-live-sync")

    dest = sandbox["dir"] + "/synced"
    profile = Profile("it-sync", source_dirs={"payload": [dest]})
    engine = SyncEngine(base_dir=str(tmp_path))

    first = engine.run(profile, session._conn)
    assert any("hello.txt" in u for u in first.uploaded)
    assert not first.skipped

    second = engine.run(profile, session._conn)
    assert any("hello.txt" in s for s in second.skipped)
    assert not second.uploaded


def test_sss_push_uploads_then_skips(session, sandbox, tmp_path):
    """``s.sync.path`` over real SFTP: ad-hoc push of a file and a directory.

    Exercises the profile-less ``push`` path end-to-end -- a file lands at
    ``dest/<basename>``, a directory has its contents merged into ``dest`` (not
    nested under ``dest/<dirname>``), and a second identical push skips.
    """
    payload = tmp_path / "build"
    payload.mkdir()
    (payload / "artifact.txt").write_text("sss-live-push")
    (payload / "sub").mkdir()
    (payload / "sub" / "nested.txt").write_text("sss-live-push-nested")

    # File push -> dest/<basename>.
    file_dest = sandbox["dir"] + "/file-push"
    first_file = session.sync.path(str(payload / "artifact.txt"), file_dest)
    uploaded = first_file["uploaded"]
    assert any(u.endswith("/file-push/artifact.txt") for u in uploaded)
    assert session._conn.stat(file_dest + "/artifact.txt") is not None

    # Second identical push skips (mtime/size unchanged).
    second_file = session.sync.path(str(payload / "artifact.txt"), file_dest)
    assert any("artifact.txt" in s for s in second_file["skipped"])
    assert not second_file["uploaded"]

    # Directory push -> contents merged into dest, NOT nested under dest/build.
    dir_dest = sandbox["dir"] + "/dir-push"
    dir_result = session.sync.path(str(payload), dir_dest)
    assert session._conn.stat(dir_dest + "/artifact.txt") is not None
    assert session._conn.stat(dir_dest + "/sub/nested.txt") is not None
    assert session._conn.stat(dir_dest + "/build") is None
    assert all("/build/" not in u for u in dir_result["uploaded"])


def test_sss_files_remove_and_delete(session, sandbox, tmp_path):
    """files.remove (`del`) drops a file; files.delete (`rmdir`) drops a tree."""
    sub = sandbox["dir"] + "/files"
    session._conn.mkdir_p(sub)

    local = tmp_path / "junk.txt"
    local.write_text("data")
    target_file = sub + "/junk.txt"
    session._conn.put(str(local), target_file)
    assert session._conn.stat(target_file) is not None

    assert session.files.remove([target_file])["success"]
    assert session._conn.stat(target_file) is None

    session._conn.put(str(local), sub + "/again.txt")
    assert session.files.delete([sub])["success"]
    assert session._conn.stat(sub) is None


def test_sss_process_spawn_and_kill(session, sandbox):
    """Spawn a throwaway waiter tagged with a unique token, then kill by token.

    ``waitfor.exe /t 60 <TOKEN>`` blocks on a never-signalled event (self-expires
    in 60s as a cleanup backstop) and is not in the process module's protected
    set. ``process.kill`` matches the token surgically against the command line,
    so only this waiter is affected.
    """
    token = "sssit" + sandbox["token"]
    session.process.start("waitfor.exe", "/t", "60", token)

    killed = []
    for _ in range(15):  # Start-Process returns before the child is visible
        result = session.process.kill(token)
        killed = result["killed"]
        if killed:
            break
        time.sleep(1)

    assert killed, f"throwaway waiter tagged {token!r} never appeared / wasn't killed"
    assert any("waitfor" in k["name"].lower() for k in killed)


def test_sss_process_survives_session_close(session, sandbox, sss_conn):
    """A process started by sss must outlive the SSH session that launched it.

    This is the regression gate for sss/docs/adr/0002. Start a token-tagged
    waiter on session A, then open an *independent* session B (a fresh
    ``connect`` to the same guest) and assert the waiter is still alive there --
    the property the old ``Start-Process`` launch could never satisfy, since the
    child died with session A's job object. Only then kill it by token and
    confirm it's gone.

    ``waitfor.exe /t 60 <TOKEN>`` blocks (self-expiring in 60s as a cleanup
    backstop, comfortably past reconnect + poll time) and is not protected, so
    ``process.kill`` matches the token surgically.
    """
    token = "sssalive" + sandbox["token"]
    session.process.start("waitfor.exe", "/t", "60", token)

    other = connect(**sss_conn)
    try:
        alive = False
        for _ in range(15):  # the scheduled-task launch isn't instantaneous
            ps = (
                'powershell "Get-CimInstance Win32_Process | '
                f"Where-Object {{ $_.CommandLine -like '*{token}*' }} | "
                'Select-Object -First 1 ProcessId | ConvertTo-Json"'
            )
            if other.exec(ps)["stdout"].strip():
                alive = True
                break
            time.sleep(1)
        assert alive, (
            f"process tagged {token!r} did not survive into a fresh session "
            "(start_process launch did not outlive the launching session)"
        )

        result = other.process.kill(token)
        assert result["killed"], f"failed to kill surviving process tagged {token!r}"
        assert any("waitfor" in k["name"].lower() for k in result["killed"])
    finally:
        other.close()


def test_sss_run_lifecycle_in_sandbox(session, sandbox, tmp_path):
    """Full pre_sync -> sync -> post_sync over a test-authored, sandboxed profile.

    The real BarApp profile never runs: this profile's every step stays inside
    the scratch dir. Built on the live connection via a fresh ``Sss`` so its
    sync base_dir points at the local payload.
    """
    src = tmp_path / "life"
    src.mkdir()
    (src / "app.txt").write_text("lifecycle")

    dest = sandbox["dir"] + "/install"
    pre_marker = sandbox["dir"] + "/pre.flag"
    post_marker = sandbox["dir"] + "/post.flag"
    profile = Profile(
        "it-lifecycle",
        source_dirs={"life": [dest]},
        pre_sync=[{"op": "exec", "args": {"cmd": f'echo pre> "{_win(pre_marker)}"'}}],
        post_sync=[{"op": "exec", "args": {"cmd": f'echo post> "{_win(post_marker)}"'}}],
    )

    lifecycle = Sss(session._conn, profile=profile, base_dir=str(tmp_path))
    result = lifecycle.run_lifecycle()

    assert result["pre_sync"][0]["result"]["exit_code"] == 0
    assert session._conn.stat(pre_marker) is not None
    assert any("app.txt" in u for u in result["sync"]["uploaded"])
    assert result["post_sync"][0]["result"]["exit_code"] == 0
    assert session._conn.stat(post_marker) is not None
