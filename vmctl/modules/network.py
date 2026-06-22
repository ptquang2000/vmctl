class NetworkModule:
    def __init__(self, vmx_path: str, runner):
        self._vmx = vmx_path
        self._r = runner

    def list(self) -> dict:
        return self._r.run_vmcli_json(self._vmx, "Ethernet", "query", "-f", "json")

    def ip(self) -> dict:
        # Runtime guest IP, not the static adapter config that list() returns.
        # vmcli Ethernet query only exposes the .vmx adapter config (connType,
        # MAC, network name) and has no equivalent for the live guest IP, so we
        # read guestInfo via vmrun. This is the layering rule ("vmcli where it
        # works, vmrun where it doesn't"), not an exception to it.
        #
        # No -wait: getGuestIPAddress -wait blocks until an IP exists and can
        # hang indefinitely. This is a fast snapshot -- callers poll if needed.
        # Running with no IP yet -> "" (exit 0); powered off -> vmrun exits
        # non-zero and run_vmrun raises VMCtlError.
        return {"ip": self._r.run_vmrun("getGuestIPAddress", self._vmx).strip()}

    def connect(self, label: str) -> dict:
        # vmcli Ethernet ConnectionControl takes only <connectOp> (no device label)
        return self._r.run_vmcli_action(self._vmx, "Ethernet", "ConnectionControl", "connect")

    def disconnect(self, label: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "Ethernet", "ConnectionControl", "disconnect")

    def set_type(self, label: str, conn_type: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "Ethernet", "SetConnectionType", label, conn_type)

    def set_name(self, label: str, network_name: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "Ethernet", "SetNetworkName", label, network_name)
