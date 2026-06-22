from typing import Optional


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
        args = ["Guest", "copyTo"] + self._cred_args()
        if overwrite:
            args.append("--overwrite")
        args += [host_path, guest_path]
        return self._r.run_vmcli_action(self._vmx, *args)

    def copy_from(self, guest_path: str, host_path: str, overwrite: bool = False) -> dict:
        args = ["Guest", "copyFrom"] + self._cred_args()
        if overwrite:
            args.append("--overwrite")
        args += [guest_path, host_path]
        return self._r.run_vmcli_action(self._vmx, *args)
