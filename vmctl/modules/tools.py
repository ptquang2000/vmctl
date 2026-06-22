from typing import Optional


class ToolsModule:
    def __init__(self, vmx_path: str, runner):
        self._vmx = vmx_path
        self._r = runner

    def query(self) -> dict:
        return self._r.run_vmcli_json(self._vmx, "Tools", "Query", "-f", "json")

    def install(self, iso_path: Optional[str] = None, cmdline: Optional[str] = None) -> dict:
        return self._run_tools_op("Install", iso_path, cmdline)

    def upgrade(self, iso_path: Optional[str] = None, cmdline: Optional[str] = None) -> dict:
        return self._run_tools_op("Upgrade", iso_path, cmdline)

    def _run_tools_op(self, op: str, iso_path: Optional[str], cmdline: Optional[str]) -> dict:
        # vmcli's --help lists numeric backing types (0,1,2) but the parser
        # actually requires the enum names: none (bundled ISO), image
        # (explicit --backingPath), uri.
        args = ["Tools", op]
        if iso_path is None:
            args += ["--backingType", "none"]
        else:
            args += ["--backingType", "image", "--backingPath", iso_path]
        if cmdline is not None:
            args += ["--cmdline", cmdline]
        return self._r.run_vmcli_action(self._vmx, *args)
