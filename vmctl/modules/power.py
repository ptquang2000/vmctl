class PowerModule:
    def __init__(self, vmx_path: str, runner):
        self._vmx = vmx_path
        self._r = runner

    def state(self) -> dict:
        return self._r.run_vmcli_json(self._vmx, "Power", "query", "-f", "json")

    def start(self, paused: bool = False, gui: bool = True) -> dict:
        # vmcli Power Start requires __vmware__ group membership; vmrun works without it
        args = ["start", self._vmx]
        if paused:
            args.append("nogui")  # vmrun has no --paused; use nogui as closest proxy
        else:
            # gui opens the Workstation console; nogui boots headless (in the
            # background) -- the memory snapshot's interactive session is
            # restored either way.
            args.append("gui" if gui else "nogui")
        self._r.run_vmrun(*args)
        return {"success": True}

    def stop(self, hard: bool = False) -> dict:
        self._r.run_vmrun("stop", self._vmx, "hard" if hard else "soft")
        return {"success": True}

    def reset(self, hard: bool = False) -> dict:
        self._r.run_vmrun("reset", self._vmx, "hard" if hard else "soft")
        return {"success": True}

    def suspend(self) -> dict:
        self._r.run_vmrun("suspend", self._vmx)
        return {"success": True}

    def pause(self) -> dict:
        self._r.run_vmrun("pause", self._vmx)
        return {"success": True}

    def unpause(self) -> dict:
        self._r.run_vmrun("unpause", self._vmx)
        return {"success": True}
