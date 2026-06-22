from typing import Optional

from ..runner import _extract_json


class SharesModule:
    """
    HGFS shared folder management.

    Labels map to VMX sharedFolderN keys. `add` auto-assigns the next
    available index; all other operations look up the index by label.
    The label is the `sharedFolderN` prefix (e.g. "sharedFolder0") as
    returned by HGFS query.  Guest-visible name is controlled separately
    via guest_name / set_guest_name.
    """

    def __init__(self, vmx_path: str, runner):
        self._vmx = vmx_path
        self._r = runner

    # ------------------------------------------------------------------ #
    # helpers                                                              #
    # ------------------------------------------------------------------ #

    def _set(self, key: str, value: str) -> None:
        self._r.run_vmcli_action(self._vmx, "ConfigParams", "SetEntry", key, value)

    def _next_index(self) -> int:
        folders = self.list().get("folders", [])
        return len(folders)

    def _index_for(self, label: str) -> Optional[int]:
        """Return the numeric index for the sharedFolderN label, or None."""
        prefix = "sharedFolder"
        if label.startswith(prefix) and label[len(prefix):].isdigit():
            return int(label[len(prefix):])
        return None

    def _require_index(self, label: str) -> int:
        idx = self._index_for(label)
        if idx is None:
            raise ValueError(
                f"'{label}' is not a valid share label. "
                "Use the 'sharedFolderN' format (e.g. 'sharedFolder0')."
            )
        return idx

    # ------------------------------------------------------------------ #
    # public API                                                           #
    # ------------------------------------------------------------------ #

    def list(self) -> dict:
        raw = self._r.run_vmcli(self._vmx, "HGFS", "query", "-f", "json")
        return _extract_json(raw)

    def add(
        self,
        host_path: str,
        writable: bool = False,
        guest_name: Optional[str] = None,
    ) -> dict:
        idx = self._next_index()
        prefix = f"sharedFolder{idx}"
        effective_guest = guest_name if guest_name is not None else prefix
        self._set(f"{prefix}.present", "TRUE")
        self._set(f"{prefix}.enabled", "TRUE")
        self._set(f"{prefix}.hostPath", host_path)
        self._set(f"{prefix}.readAccess", "TRUE")
        self._set(f"{prefix}.writeAccess", "TRUE" if writable else "FALSE")
        self._set(f"{prefix}.guestName", effective_guest)
        self._set("sharedFolder.maxNum", str(idx + 1))
        return {"success": True, "label": prefix}

    def remove(self, label: str) -> dict:
        idx = self._require_index(label)
        self._set(f"sharedFolder{idx}.present", "FALSE")
        return {"success": True}

    def set_path(self, label: str, host_path: str) -> dict:
        idx = self._require_index(label)
        self._set(f"sharedFolder{idx}.hostPath", host_path)
        return {"success": True}

    def set_writable(self, label: str, writable: bool) -> dict:
        idx = self._require_index(label)
        self._set(f"sharedFolder{idx}.writeAccess", "TRUE" if writable else "FALSE")
        return {"success": True}

    def set_enabled(self, label: str, enabled: bool) -> dict:
        idx = self._require_index(label)
        self._set(f"sharedFolder{idx}.enabled", "TRUE" if enabled else "FALSE")
        return {"success": True}

    def set_guest_name(self, label: str, guest_name: str) -> dict:
        idx = self._require_index(label)
        self._set(f"sharedFolder{idx}.guestName", guest_name)
        return {"success": True}
