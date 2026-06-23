"""
Live integration tests for vmctl guest-operation modules.

These tests drive a real VM and require:

  * VMware Workstation installed.
  * A VM named ``vmctl-unittest`` with a ``init`` snapshot. This is a
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

import os
import tempfile
import time
import warnings

import pytest

from vmctl import VMCtl

VM_NAME = "vmctl-unittest"
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
    vm.power.start()
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
    vm.power.start()
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


# --------------------------------------------------------------------------- #
# clipboard_vm group                                                          #
# --------------------------------------------------------------------------- #


def test_clipboard_roundtrip(clipboard_vm):
    clipboard_vm.clipboard.push_text("hello clipboard")
    result = clipboard_vm.clipboard.pull_text()
    assert result["text"].strip() == "hello clipboard"


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

    Live ground truth (verified against vmctl-unittest): vmcli ``Guest ps -f
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
    vm.snapshot.revert(LIVETEST_SNAPSHOT, ensure_running=True)
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
