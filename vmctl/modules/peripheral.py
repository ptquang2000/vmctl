import re

from ..exceptions import VMCtlError
from ..vmx_parser import parse_vmx


class PeripheralModule:
    """Connectable-device inventory and connect/disconnect dispatch.

    ``list()`` is the contract backbone: a flat, uniform inventory of every
    connectable device (disk, cdrom, serial, usb). ``connect``/``disconnect``
    resolve the user-supplied id back to a type via that inventory and dispatch
    to the per-type backend. The user sees one id namespace; the backend split
    (vmcli for disk/serial/cdrom, vmrun for usb) is hidden. See
    docs/adr/0004 and CONTEXT.md "peripheral devices".
    """

    # USB device .vmx keys look like "usb_xhci:4", "ehci:1", "usb:0" — a bus
    # prefix + ":" + index. The bare controllers (usb.present, usb_xhci.present)
    # carry no colon and are not connectable devices.
    _USB_DEVICE_RE = re.compile(r"^(?:usb_xhci|ehci|usb):\d+$")

    # type -> backend family (cdrom rides the disk backend).
    _BACKEND = {"disk": "disk", "cdrom": "disk", "serial": "serial", "usb": "usb"}

    def __init__(self, vmx_path: str, runner):
        self._vmx = vmx_path
        self._r = runner

    # -- inventory ---------------------------------------------------------

    def list(self) -> dict:
        """Flat inventory of connectable devices: one ``{id, type, connected,
        backing}`` entry per device, across disk/cdrom/serial/usb."""
        devices = []

        disk = self._r.run_vmcli_json(self._vmx, "Disk", "query", "-f", "json")
        for group in ("cdroms", "disks", "scsis"):
            for entry in disk.get(group, []):
                devices.append(self._disk_entry(entry))

        serial = self._r.run_vmcli_json(self._vmx, "Serial", "Query", "-f", "json")
        for entry in serial.get("devices", []):
            status = entry.get("connectionStatus")
            devices.append({
                "id": entry.get("label"),
                "type": "serial",
                "connected": status == "connected",
                "backing": entry.get("backingPathName"),
            })

        devices.extend(self._usb_devices())
        return {"devices": devices}

    @staticmethod
    def _disk_entry(entry: dict) -> dict:
        # cdrom vs disk is derived from the backing, not typed by the user.
        dtype = "cdrom" if entry.get("backingType") == "cdrom_image" else "disk"
        status = entry.get("connectionStatus")
        return {
            "id": entry.get("label"),
            "type": dtype,
            # Removable media report connectionStatus; fixed disks omit it and
            # are always attached while present.
            "connected": status == "connected" if status is not None else True,
            "backing": entry.get("backingPathName"),
        }

    def _usb_devices(self) -> list:
        # USB entries come from the .vmx named-device config — there is no
        # vmcli/vmrun verb that enumerates connectable *host* hardware, so this
        # is "devices the VM knows about", not a live host-USB probe.
        try:
            vmx = parse_vmx(self._vmx)
        except OSError:
            return []
        grouped = {}
        for key, val in vmx.items():
            prefix, _, sub = key.partition(".")
            if not sub or not self._USB_DEVICE_RE.match(prefix):
                continue
            grouped.setdefault(prefix, {})[sub] = val
        devices = []
        for prefix in sorted(grouped):
            props = grouped[prefix]
            if props.get("present", "").upper() != "TRUE":
                continue
            devices.append({
                "id": prefix,
                "type": "usb",
                # No connection-status key exists in the .vmx for a USB device,
                # so the connected state is unknown (see CONTEXT.md note).
                "connected": None,
                "backing": props.get("deviceType"),
            })
        return devices

    # -- connect / disconnect ----------------------------------------------

    def connect(self, id: str) -> dict:
        return self._dispatch(id, "connect")

    def disconnect(self, id: str) -> dict:
        return self._dispatch(id, "disconnect")

    def _dispatch(self, id: str, op: str) -> dict:
        devices = self.list()["devices"]
        matches = [d for d in devices if d["id"] == id]
        if not matches:
            valid = ", ".join(d["id"] for d in devices) or "(none)"
            raise VMCtlError(f"unknown device id {id!r}; valid ids: {valid}")
        types = {d["type"] for d in matches}
        if len(types) > 1:
            kinds = ", ".join(sorted(types))
            raise VMCtlError(
                f"device id {id!r} is ambiguous across types ({kinds}); "
                "cannot disambiguate"
            )
        backend = self._BACKEND[matches[0]["type"]]
        return getattr(self, f"_{op}_{backend}")(id)

    # -- per-type backends -------------------------------------------------

    def _connect_disk(self, label: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "Disk", "ConnectionControl", label, "connect")

    def _disconnect_disk(self, label: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "Disk", "ConnectionControl", label, "disconnect")

    def _connect_serial(self, label: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "Serial", "ConnectionControl", label, "connect")

    def _disconnect_serial(self, label: str) -> dict:
        return self._r.run_vmcli_action(self._vmx, "Serial", "ConnectionControl", label, "disconnect")

    def _connect_usb(self, device_name: str) -> dict:
        self._r.run_vmrun("connectNamedDevice", self._vmx, device_name)
        return {"success": True}

    def _disconnect_usb(self, device_name: str) -> dict:
        self._r.run_vmrun("disconnectNamedDevice", self._vmx, device_name)
        return {"success": True}

    # -- iso ---------------------------------------------------------------

    def mount_iso(self, id: str, iso_path: str) -> dict:
        """Rebind a cdrom's backing to ``iso_path`` then connect it — something
        plain ``connect`` cannot do (it does not change the backing)."""
        self._r.run_vmcli_action(
            self._vmx, "Disk", "SetBackingInfo", id, "cdrom_image", iso_path, "false"
        )
        return self._r.run_vmcli_action(self._vmx, "Disk", "ConnectionControl", id, "connect")
