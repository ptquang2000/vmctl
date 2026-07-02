import os
import re
from typing import Optional

from ..exceptions import VMCtlError


def _is_abs(path: str) -> bool:
    # Treat a Windows drive-absolute ("C:\..."), UNC ("\\host\..."), or POSIX
    # ("/...") path as absolute regardless of host os.path flavour.
    return bool(re.match(r"[A-Za-z]:[\\/]|[\\/]{2}|/", path))


def _basename(path: str) -> str:
    # Split on either separator so a Windows host path is handled correctly
    # regardless of which os.path flavour is active.
    return re.split(r"[\\/]", path.rstrip("\\/"))[-1]


def _resolve_dest(dest: str, source: str) -> str:
    # The VIX copy verbs require the destination to be a full FILE path; a bare
    # directory won't receive the file under its source name. Apply cp/scp
    # semantics when the destination is written with explicit directory intent --
    # it ends in a separator, or is a bare drive root like "C:" -- by appending
    # the source's basename so the file keeps its name inside that directory.
    if dest.endswith(("\\", "/")):
        return dest + _basename(source)
    if re.fullmatch(r"[A-Za-z]:", dest):
        return dest + "\\" + _basename(source)
    return dest


class GuestModule:
    def __init__(self, vmx_path: str, runner, credentials: dict):
        self._vmx = vmx_path
        self._r = runner
        self._creds = credentials

    def _cred_args(self) -> list:
        args = []
        if self._creds.get("user"):
            args += ["--username", self._creds["user"]]
        if self._creds.get("password"):
            args += ["--password", self._creds["password"]]
        return args

    def _vmrun_auth(self) -> list:
        # vmrun's guest verbs take creds as `-gu <user> -gp <pass>` BEFORE the
        # verb (the vars.py guestEnv convention), unlike vmcli's --username/
        # --password.
        if self._creds.get("user"):
            return ["-gu", self._creds["user"], "-gp", self._creds.get("password", "")]
        return []

    def run(
        self,
        program: str,
        *prog_args: str,
        no_wait: bool = True,
        interactive: bool = False,
    ) -> dict:
        # Flags must precede the program: vmcli Guest run treats everything
        # after the program path as program-argument tokens, so a trailing
        # --noWait/--interactive would be (mis)handled as a program arg.
        args = ["Guest", "run"] + self._cred_args()
        if no_wait:
            args.append("--noWait")
        if interactive:
            args.append("--interactive")
        args.append(program)
        if prog_args:
            args += list(prog_args)
        try:
            return self._r.run_vmcli_action(self._vmx, *args)
        except VMCtlError as e:
            # An interactive launch resolves the program on the host side and
            # does NOT search the guest PATH, so a bare name like "cmd.exe"
            # fails with "A file was not found" even though it works without
            # --interactive. Point at the absolute-path requirement.
            if interactive and "not found" in str(e).lower() and not _is_abs(program):
                raise VMCtlError(
                    f"interactive 'guest run' could not find '{program}'; "
                    f"--interactive does not search the guest PATH, so the "
                    f"program must be an absolute path (e.g. "
                    f"'C:\\Windows\\System32\\cmd.exe')"
                ) from e
            raise

    def ps(self) -> dict:
        # vmcli Guest ps supports -f json (verified live); it returns a clean
        # {"processes": [{name, pid, cmd, user, eCode, eTime, start}, ...]}
        # object. Prefer it over scraping the YAML-ish default text output.
        args = ["Guest", "ps"] + self._cred_args() + ["-f", "json"]
        return self._r.run_vmcli_json(self._vmx, *args)

    def kill(self, pid: int) -> dict:
        args = ["Guest", "kill"] + self._cred_args() + [str(pid)]
        return self._r.run_vmcli_action(self._vmx, *args)

    def copy_to(self, host_path: str, guest_path: str, overwrite: bool = False) -> dict:
        # cp is single-file; a directory source is refused up front with an
        # actionable pointer to `vmctl push` (which does trees natively over
        # SSH). Local check -- no wasted VIX round-trip.
        if os.path.isdir(host_path):
            raise VMCtlError(
                f"'{host_path}' is a directory; 'vmctl cp' copies a single "
                f"file. For directory trees use 'vmctl push'."
            )
        # guest_path is the destination; resolve directory-intent forms to a
        # full file path (cp/scp semantics).
        guest_path = _resolve_dest(guest_path, host_path)
        auth = self._vmrun_auth()
        # vmrun's copy verbs always overwrite; enforce -o ourselves so the flag
        # keeps meaning -- refuse an existing dest unless overwrite was asked.
        if not overwrite and self._r.run_vmrun_test(
            *auth, "fileExistsInGuest", self._vmx, guest_path
        ):
            raise VMCtlError(
                f"guest destination '{guest_path}' already exists; pass "
                f"-o/--overwrite to replace it"
            )
        self._r.run_vmrun(*auth, "CopyFileFromHostToGuest",
                          self._vmx, host_path, guest_path)
        return {"success": True}

    def copy_from(self, guest_path: str, host_path: str, overwrite: bool = False) -> dict:
        # cp is single-file; refuse a directory guest source up front, pointing
        # at `vmctl push`. directoryExistsInGuest answers this directly on the
        # transport we already use.
        auth = self._vmrun_auth()
        if self._r.run_vmrun_test(
            *auth, "directoryExistsInGuest", self._vmx, guest_path
        ):
            raise VMCtlError(
                f"guest source '{guest_path}' is a directory; 'vmctl cp' copies "
                f"a single file. For directory trees use 'vmctl push'."
            )
        # host_path is the destination; resolve directory-intent forms to a
        # full file path (cp/scp semantics).
        host_path = _resolve_dest(host_path, guest_path)
        # vmrun's copy verbs always overwrite; enforce -o ourselves.
        if not overwrite and os.path.exists(host_path):
            raise VMCtlError(
                f"host destination '{host_path}' already exists; pass "
                f"-o/--overwrite to replace it"
            )
        self._r.run_vmrun(*auth, "CopyFileFromGuestToHost",
                          self._vmx, guest_path, host_path)
        return {"success": True}
