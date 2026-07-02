import json
import re
import subprocess
import tempfile
from pathlib import Path

from .exceptions import VMCtlError


class Runner:
    def __init__(self, vmware_home: str):
        home = Path(vmware_home)
        self.vmcli = str(home / "vmcli.exe")
        self.vmrun = str(home / "vmrun.exe")

    def _exec(self, cmd: list) -> str:
        # Capture via temp files rather than pipes. `vmrun start` launches
        # long-lived children (vmware.exe / vmware-vmx) that inherit the
        # parent's stdout/stderr handles. With capture_output=True (os.pipe),
        # communicate() blocks on pipe EOF, which never arrives until the VM
        # GUI exits, so the call hangs for the VM's entire lifetime. Writing
        # to real files makes run() wait only for the direct child to exit.
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as out, \
             tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as err:
            result = subprocess.run(
                cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=err, text=True
            )
            out.seek(0)
            err.seek(0)
            stdout = out.read()
            stderr = err.read()
        if result.returncode != 0:
            msg = (stderr.strip() or stdout.strip() or
                   f"process exited with code {result.returncode}")
            raise VMCtlError(msg, returncode=result.returncode, stderr=stderr)
        return stdout

    def run_vmcli(self, vmx_path: str, *args) -> str:
        return self._exec([self.vmcli, vmx_path] + list(args))

    def run_vmcli_json(self, vmx_path: str, *args) -> dict:
        text = self.run_vmcli(vmx_path, *args)
        return _extract_json(text)

    def run_vmcli_action(self, vmx_path: str, *args) -> dict:
        self.run_vmcli(vmx_path, *args)
        return {"success": True}

    def run_vmrun(self, *args) -> str:
        return self._exec([self.vmrun, "-T", "ws"] + list(args))

    def _exec_capture(self, cmd: list):
        # Like _exec but does NOT raise on a non-zero exit -- returns
        # (returncode, stdout). The capture path (exec -t) needs a non-zero guest
        # exit as data, not an exception: `vmrun runProgramInGuest` propagates the
        # guest program's own exit code, and a failing guest command is a normal
        # captured outcome, not a runner failure. Same temp-file capture as _exec
        # (see there for why pipes would hang).
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as out, \
             tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as err:
            result = subprocess.run(
                cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=err, text=True
            )
            out.seek(0)
            stdout = out.read()
        return result.returncode, stdout

    def run_vmrun_capture(self, *args):
        """Run a vmrun subcommand, returning ``(exit_code, stdout)`` without
        raising on a non-zero exit. For the exec-capture path only."""
        return self._exec_capture([self.vmrun, "-T", "ws"] + list(args))

    def run_vmrun_test(self, *args) -> bool:
        # For the existence-predicate verbs (directoryExistsInGuest,
        # fileExistsInGuest), which invert intuition: path EXISTS -> exit 0
        # (stdout "The ... exists."); ABSENT -> exit 127 (stdout "The ... does
        # not exist.", empty stderr). _exec raises on any nonzero code, so a
        # normal "false" would arrive as an exception indistinguishable from a
        # real failure. Run without letting that raise, then parse stdout:
        # "exists." and not "does not" -> True; "does not exist" -> False;
        # anything else (auth failure, VM off, Tools wedged) -> raise. This is
        # the ONLY consumer of the inverted-exit-code contract.
        try:
            out = self._exec([self.vmrun, "-T", "ws"] + list(args))
        except VMCtlError as e:
            out = (e.stderr or "") + (str(e) or "")
        low = out.lower()
        if "does not exist" in low:
            return False
        if "exists." in low and "does not" not in low:
            return True
        raise VMCtlError(out.strip() or "vmrun existence check failed")


def _extract_json(text: str) -> dict:
    match = re.search(r"[{\[]", text)
    if not match:
        return {}
    return json.loads(text[match.start():])
