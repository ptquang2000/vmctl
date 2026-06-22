class SnapshotModule:
    def __init__(self, vmx_path: str, runner):
        self._vmx = vmx_path
        self._r = runner

    def list(self) -> dict:
        return self._r.run_vmcli_json(self._vmx, "Snapshot", "query", "-f", "json")

    def _resolve_uid(self, name: str) -> int:
        data = self.list()
        for snap in data.get("snapshots", []):
            if snap["displayName"].lower() == name.lower():
                return snap["uid"]
        raise ValueError(f"Snapshot '{name}' not found")

    def take(self, name: str, memory: bool = False, description: str = None) -> dict:
        args = ["Snapshot", "Take", name]
        if memory:
            args.append("--memory")
        if description is not None:
            args += ["--description", description]
        return self._r.run_vmcli_action(self._vmx, *args)

    def revert(self, name: str) -> dict:
        uid = self._resolve_uid(name)
        return self._r.run_vmcli_action(self._vmx, "Snapshot", "Revert", str(uid))

    def delete(self, name: str, delete_children: bool = False) -> dict:
        uid = self._resolve_uid(name)
        args = ["Snapshot", "Delete", str(uid)]
        if delete_children:
            args.append("--deleteChildren")
        return self._r.run_vmcli_action(self._vmx, *args)
