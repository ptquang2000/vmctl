from .power import PowerModule


class SnapshotModule:
    def __init__(self, vmx_path: str, runner, power=None):
        self._vmx = vmx_path
        self._r = runner
        # revert() manages the VM power lifecycle itself, so it needs Power
        # query/stop/start. Construct our own PowerModule when one isn't injected.
        self._power = power or PowerModule(vmx_path, runner)

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

    def revert(self, name: str, ensure_running: bool = False, gui: bool = True) -> dict:
        # Validate the snapshot name BEFORE touching power, so a typo never
        # leaves the VM powered off for nothing.
        uid = self._resolve_uid(name)
        # vmcli Snapshot Revert refuses to run while the VM is "online", and
        # reverting discards the running state anyway, so a hard stop is correct
        # (a graceful guest shutdown would be wasted and can hang without Tools).
        online = self._power.state().get("PowerState") == "on"
        if online:
            self._power.stop(hard=True)
        self._r.run_vmcli_action(self._vmx, "Snapshot", "Revert", str(uid))
        # Restore the prior power state: an online VM ends running again.
        # ensure_running forces a start regardless (suspended -> resume,
        # off -> cold boot).
        if online or ensure_running:
            self._power.start(gui=gui)
        return {"success": True}

    def delete(self, name: str, delete_children: bool = False) -> dict:
        uid = self._resolve_uid(name)
        args = ["Snapshot", "Delete", str(uid)]
        if delete_children:
            args.append("--deleteChildren")
        return self._r.run_vmcli_action(self._vmx, *args)
