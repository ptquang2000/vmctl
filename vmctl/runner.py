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


def _extract_json(text: str) -> dict:
    match = re.search(r"[{\[]", text)
    if not match:
        return {}
    return json.loads(text[match.start():])
