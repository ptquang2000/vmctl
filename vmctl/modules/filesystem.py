from typing import Callable, Optional


class FilesystemModule:
    def __init__(
        self,
        vmx_path: str,
        runner,
        credentials: dict,
        guest_os_fn: Optional[Callable[[], str]] = None,
    ):
        self._vmx = vmx_path
        self._r = runner
        self._creds = credentials
        self._guest_os_fn = guest_os_fn or self._query_guest_os

    def _cred_args(self) -> list:
        args = []
        if self._creds.get("user"):
            args += ["--username", self._creds["user"]]
        if self._creds.get("password"):
            args += ["--password", self._creds["password"]]
        return args

    def _query_guest_os(self) -> str:
        from ..runner import _extract_json
        raw = self._r.run_vmcli(self._vmx, "ConfigParams", "query", "-f", "json")
        cfg = _extract_json(raw)
        return cfg.get("guestOS", "")

    def _default_temp_dir(self) -> str:
        guest_os = self._guest_os_fn()
        return r"C:\Windows\Temp" if "windows" in guest_os.lower() else "/tmp"

    def ls(
        self,
        path: str,
        regexp: Optional[str] = None,
        index: Optional[int] = None,
        max: Optional[int] = None,
    ) -> dict:
        args = ["Guest", "ls"] + self._cred_args() + [path]
        if regexp is not None:
            args += ["--regexp", regexp]
        if index is not None:
            args += ["--index", str(index)]
        if max is not None:
            args += ["--max", str(max)]
        raw = self._r.run_vmcli(self._vmx, *args)
        return _parse_ls(raw)

    def env(self) -> dict:
        args = ["Guest", "env"] + self._cred_args()
        raw = self._r.run_vmcli(self._vmx, *args)
        return _parse_env(raw)

    def mkdir(self, path: str, parents: bool = False) -> dict:
        args = ["Guest", "mkdir"] + self._cred_args()
        if parents:
            args.append("--parent")
        args.append(path)
        return self._r.run_vmcli_action(self._vmx, *args)

    def rm(self, path: str) -> dict:
        args = ["Guest", "rm"] + self._cred_args() + [path]
        return self._r.run_vmcli_action(self._vmx, *args)

    def rmdir(self, path: str, recursive: bool = False) -> dict:
        args = ["Guest", "rmdir"] + self._cred_args()
        if recursive:
            args.append("--recursive")
        args.append(path)
        return self._r.run_vmcli_action(self._vmx, *args)

    def mv(self, src: str, dst: str, overwrite: bool = False) -> dict:
        args = ["Guest", "mv"] + self._cred_args()
        if overwrite:
            args.append("--overwrite")
        args += [src, dst]
        return self._r.run_vmcli_action(self._vmx, *args)

    def mvdir(self, src: str, dst: str, overwrite: bool = False) -> dict:
        args = ["Guest", "mvdir"] + self._cred_args()
        if overwrite:
            args.append("--overwrite")
        args += [src, dst]
        return self._r.run_vmcli_action(self._vmx, *args)

    def create_temp_file(
        self,
        prefix: str = "vmctl_",
        suffix: str = "",
        directory: Optional[str] = None,
    ) -> dict:
        if directory is None:
            directory = self._default_temp_dir()
        args = ["Guest", "createTempFile"] + self._cred_args() + [prefix, suffix, directory]
        raw = self._r.run_vmcli(self._vmx, *args)
        return {"path": raw.strip()}

    def create_temp_dir(
        self,
        prefix: str = "vmctl_",
        suffix: str = "",
        directory: Optional[str] = None,
    ) -> dict:
        if directory is None:
            directory = self._default_temp_dir()
        args = ["Guest", "createTempDir"] + self._cred_args() + [prefix, suffix, directory]
        raw = self._r.run_vmcli(self._vmx, *args)
        return {"path": raw.strip()}


def _parse_ls(text: str) -> dict:
    """Parse ``vmcli Guest ls`` output into a list of filenames.

    vmcli has no ``-f json`` for ``ls`` (verified live -- ``-f`` is rejected),
    so it emits a fixed columnar table::

        Perms      Fl Owner Group File size      Mod time   Create Time  Access Time          Filename          Symlink
        0           1     0     0         0  Jun 22 08:52  Jun 22 08:52  Jun 22 08:52                .
        0           5     0     0         0  Jun 22 08:52  Dec 07 16:03  Jun 22 08:52               ..

    There are 14 whitespace-delimited fields before the filename (5 scalar
    columns + three "Mon Day HH:MM" timestamps), then the name and an optional
    symlink target. Split at most 14 times so the remainder is the name (plus
    any symlink), and drop the header row and the ``.``/``..`` self entries so
    an empty directory parses to ``[]``.
    """
    entries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 14)
        if len(parts) < 15 or parts[0] == "Perms":
            continue
        name = parts[14].strip()
        if name in (".", ".."):
            continue
        entries.append(name)
    return {"entries": entries}


def _parse_env(text: str) -> dict:
    env = {}
    for line in text.splitlines():
        line = line.strip()
        if "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return {"env": env}
