import os
import re
from typing import Optional

from ..exceptions import VMCtlError

# vmcli Guest copyTo silently fails on sizeable files: ≤60 KB copies fine,
# ≥64 KB fails with an opaque "Unknown error" and the file never lands in the
# guest (verified live against vmctl-unittest, 2026-06-22). The wall sits in the
# (60 KB, 64 KB] gray zone; we refuse at the highest proven-good size rather than
# attempt a transfer that fails silently mid-flight. See CONTEXT.md "Guest file
# copy".
_COPY_TO_MAX_BYTES = 60 * 1024

_LARGE_FILE_HINT = (
    "is too large for 'guest copy-to' (limit {limit} bytes; vmcli Guest copyTo "
    "fails silently on larger files). For sizeable payloads use an HGFS shared "
    "folder ('vmctl shares add <host_dir>') or attach the file as an ISO "
    "('vmctl peripheral mount-iso')."
)


def _basename(path: str) -> str:
    # Split on either separator so a Windows host path is handled correctly
    # regardless of which os.path flavour is active.
    return re.split(r"[\\/]", path.rstrip("\\/"))[-1]


def _resolve_dest(dest: str, source: str) -> str:
    # vmcli copyTo/copyFrom require <toPath> to be a full FILE path; a directory
    # is rejected with "The object is not a file". Apply cp/scp semantics when
    # the destination is written with explicit directory intent -- it ends in a
    # separator, or is a bare drive root like "C:" -- by appending the source's
    # basename so the file keeps its name inside that directory.
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

    def run(
        self,
        program: str,
        *prog_args: str,
        no_wait: bool = True,
        interactive: bool = False,
    ) -> dict:
        args = ["Guest", "run"] + self._cred_args() + [program]
        if prog_args:
            args += list(prog_args)
        if no_wait:
            args.append("--noWait")
        if interactive:
            args.append("--interactive")
        return self._r.run_vmcli_action(self._vmx, *args)

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
        # Refuse oversize files up front rather than let vmcli attempt a transfer
        # that fails silently (opaque "Unknown error", file never lands). If the
        # host file can't be stat'd (e.g. does not exist), skip the check so
        # unrelated errors keep surfacing from vmcli unchanged.
        try:
            size = os.path.getsize(host_path)
        except OSError:
            size = None
        if size is not None and size > _COPY_TO_MAX_BYTES:
            raise VMCtlError(
                f"'{host_path}' " + _LARGE_FILE_HINT.format(limit=_COPY_TO_MAX_BYTES)
            )
        # guest_path is the destination; resolve directory-intent forms to a
        # full file path (cp/scp semantics).
        guest_path = _resolve_dest(guest_path, host_path)
        args = ["Guest", "copyTo"] + self._cred_args()
        if overwrite:
            args.append("--overwrite")
        args += [host_path, guest_path]
        try:
            return self._r.run_vmcli_action(self._vmx, *args)
        except VMCtlError as e:
            # Residual case: an existing guest directory given without a trailing
            # separator (e.g. C:\Users) can't be detected locally; vmcli rejects
            # it as "The object is not a file" -- here that means the dest.
            if "not a file" in str(e).lower():
                raise VMCtlError(
                    f"guest destination '{guest_path}' is a directory; "
                    f"append a filename or a trailing separator (e.g. "
                    f"'{guest_path.rstrip(chr(92) + '/')}\\')"
                ) from e
            raise

    def copy_from(self, guest_path: str, host_path: str, overwrite: bool = False) -> dict:
        # host_path is the destination; resolve directory-intent forms to a
        # full file path (cp/scp semantics).
        host_path = _resolve_dest(host_path, guest_path)
        args = ["Guest", "copyFrom"] + self._cred_args()
        if overwrite:
            args.append("--overwrite")
        args += [guest_path, host_path]
        try:
            return self._r.run_vmcli_action(self._vmx, *args)
        except VMCtlError as e:
            # For copyFrom the "not a file" object is the guest SOURCE, not the
            # host dest -- vmcli reports a directory source this way.
            if "not a file" in str(e).lower():
                raise VMCtlError(
                    f"guest source '{guest_path}' is a directory; "
                    f"copy_from copies a single file, not a directory"
                ) from e
            raise
