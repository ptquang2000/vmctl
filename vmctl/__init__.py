import functools

from .config import load_config, save_config
from .exceptions import VMCtlError
from .registry import VMRegistry
from .runner import Runner, _extract_json
from .modules.clipboard import ClipboardModule
from .modules.filesystem import FilesystemModule
from .modules.guest import GuestModule
from .modules.inspect import InspectModule
from .modules.mks import MKSModule
from .modules.network import NetworkModule
from .modules.peripheral import PeripheralModule
from .modules.power import PowerModule
from .modules.shares import SharesModule
from .modules.snapshot import SnapshotModule
from .modules.tools import ToolsModule
from .modules.vars import VarsModule

__all__ = ["VMCtl", "VM", "VMCtlError"]


class VM:
    def __init__(self, name: str, vmx_path: str, runner: Runner, credentials: dict):
        self.name = name
        self.vmx_path = vmx_path
        self._runner = runner
        self.power = PowerModule(vmx_path, runner)
        self.snapshot = SnapshotModule(vmx_path, runner, self.power)
        self.network = NetworkModule(vmx_path, runner)
        self.peripheral = PeripheralModule(vmx_path, runner)
        self.guest = GuestModule(vmx_path, runner, credentials)
        self.clipboard = ClipboardModule(
            vmx_path, runner, credentials, guest_os_fn=lambda: self._guest_os
        )
        self.fs = FilesystemModule(
            vmx_path, runner, credentials, guest_os_fn=lambda: self._guest_os
        )
        self.tools = ToolsModule(vmx_path, runner)
        self.shares = SharesModule(vmx_path, runner)
        self.mks = MKSModule(vmx_path, runner)
        self.vars = VarsModule(vmx_path, runner, credentials)
        self.inspect = InspectModule(vmx_path, runner)

    @functools.cached_property
    def _guest_os(self) -> str:
        raw = self._runner.run_vmcli(
            self.vmx_path, "ConfigParams", "query", "-f", "json"
        )
        cfg = _extract_json(raw)
        return cfg.get("guestOS", "")


class VMCtl:
    def __init__(self):
        self._config = load_config()
        self._registry = VMRegistry(self._config.get("scan_roots", []))
        self._runner = Runner(
            self._config.get("vmware_home", r"C:\Program Files\VMware\VMware Workstation")
        )

    def get(self, name: str) -> VM:
        vmx_path = self._registry.find(name)
        # Resolve to the canonical registry name so the VM (and the CLI's `vm`
        # output key) carry one stable identity regardless of how the caller
        # spelled or abbreviated the name.
        canonical = self._registry.name_for_path(vmx_path) or name
        credentials = self._config.get("credentials", {}).get(canonical.lower(), {})
        return VM(canonical, vmx_path, self._runner, credentials)

    def resolve(self, name) -> VM:
        """Return the requested VM, or the single running in-scope VM when name
        is omitted (``None``)."""
        if name is None:
            return self._auto_select()
        return self.get(name)

    def _running_paths(self) -> list:
        raw = self._runner.run_vmrun("list")
        paths = []
        for line in raw.splitlines():
            line = line.strip()
            if line and not line.startswith("Total running VMs:"):
                paths.append(line)
        return paths

    def _running_in_scope(self) -> list:
        """Canonical names of VMs that are both running and in the registry."""
        names = []
        for path in self._running_paths():
            name = self._registry.name_for_path(path)
            if name is not None:
                names.append(name)
        return names

    def _auto_select(self) -> VM:
        running = self._running_in_scope()
        if not running:
            raise ValueError("no running VM to auto-select; pass a name")
        if len(running) > 1:
            candidates = ", ".join(sorted(running))
            raise ValueError(
                f"multiple running VMs ({candidates}); pass a name"
            )
        return self.get(running[0])

    def list_vms(self) -> dict:
        return {"running": self._running_paths(), "discovered": self._registry.list_all()}

    def clone(self, name: str, dest: str, linked: bool = False) -> dict:
        vmx_path = self._registry.find(name)
        clone_type = "linked" if linked else "full"
        self._runner.run_vmrun("clone", vmx_path, dest, clone_type)
        return {"success": True}

    def set_credentials(self, name: str, user: str, password: str) -> None:
        self._config.setdefault("credentials", {})[name.lower()] = {
            "user": user,
            "password": password,
        }
        save_config(self._config)
