from pathlib import Path

from ..runner import _extract_json
from ..vmx_parser import parse_vmx, parse_vmsd


class InspectModule:
    def __init__(self, vmx_path: str, runner):
        self._vmx = vmx_path
        self._r = runner

    def inspect(self) -> dict:
        queries = [
            ("power", ("Power", "query", "-f", "json")),
            ("chipset", ("Chipset", "query", "-f", "json")),
            ("snapshots", ("Snapshot", "query", "-f", "json")),
            ("disks", ("Disk", "query", "-f", "json")),
            ("ethernet", ("Ethernet", "query", "-f", "json")),
            ("serial", ("Serial", "Query", "-f", "json")),
            ("mks", ("MKS", "query", "-f", "json")),
            ("shares", ("HGFS", "query", "-f", "json")),
            ("tools", ("Tools", "Query", "-f", "json")),
            ("config", ("ConfigParams", "query", "-f", "json")),
        ]
        result = {}
        for key, args in queries:
            try:
                result[key] = self._r.run_vmcli_json(self._vmx, *args)
            except Exception as exc:
                result[key] = {"error": str(exc)}
        return result

    def parse_vmx(self) -> dict:
        vmx_path = Path(self._vmx)
        vmsd_path = vmx_path.with_suffix(".vmsd")
        return {
            "vmx": parse_vmx(str(vmx_path)),
            "vmsd": parse_vmsd(str(vmsd_path)) if vmsd_path.exists() else {},
        }
