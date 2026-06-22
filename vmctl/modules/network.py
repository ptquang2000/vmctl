class NetworkModule:
    def __init__(self, vmx_path: str, runner):
        self._vmx = vmx_path
        self._r = runner

    def list(self) -> dict:
        return self._r.run_vmcli_json(self._vmx, "Ethernet", "query", "-f", "json")

    def connect(self, label: str) -> dict:
        # vmcli Ethernet ConnectionControl takes only <connectOp> (no device label)
        return self._r.run_vmcli_action(self._vmx, "Ethernet", "ConnectionControl", "connect")

    def disconnect(self, label: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "Ethernet", "ConnectionControl", "disconnect")

    def set_type(self, label: str, conn_type: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "Ethernet", "SetConnectionType", label, conn_type)

    def set_name(self, label: str, network_name: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "Ethernet", "SetNetworkName", label, network_name)
