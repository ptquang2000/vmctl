class PeripheralModule:
    def __init__(self, vmx_path: str, runner):
        self._vmx = vmx_path
        self._r = runner

    def list(self) -> dict:
        disks = self._r.run_vmcli_json(self._vmx, "Disk", "query", "-f", "json")
        serial = self._r.run_vmcli_json(self._vmx, "Serial", "Query", "-f", "json")
        return {"disks": disks, "serial": serial}

    def mount_iso(self, label: str, iso_path: str) -> dict:
        self._r.run_vmcli_action(
            self._vmx, "Disk", "SetBackingInfo", label, "cdrom_image", iso_path, "false"
        )
        return self._r.run_vmcli_action(self._vmx, "Disk", "ConnectionControl", label, "connect")

    def eject(self, label: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "Disk", "ConnectionControl", label, "disconnect")

    def connect_disk(self, label: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "Disk", "ConnectionControl", label, "connect")

    def disconnect_disk(self, label: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "Disk", "ConnectionControl", label, "disconnect")

    def connect_serial(self, label: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "Serial", "ConnectionControl", label, "connect")

    def disconnect_serial(self, label: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "Serial", "ConnectionControl", label, "disconnect")

    def connect_usb(self, device_name: str) -> dict:
        self._r.run_vmrun("connectNamedDevice", self._vmx, device_name)
        return {"success": True}

    def disconnect_usb(self, device_name: str) -> dict:
        self._r.run_vmrun("disconnectNamedDevice", self._vmx, device_name)
        return {"success": True}
