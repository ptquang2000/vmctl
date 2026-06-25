import os
from pathlib import Path
from typing import Dict, List, Optional


def _normalize_path(path: str) -> str:
    """Case- and separator-insensitive key for comparing two .vmx paths.

    ``vmrun list`` and the registry's ``rglob`` can report the same file with
    different casing or separators (and short vs long forms), so reverse-mapping
    a running path back to a registry name needs a normalized comparison.
    """
    return os.path.normcase(os.path.normpath(path))


class VMRegistry:
    def __init__(self, scan_roots: List[str], aliases: Optional[Dict[str, str]] = None):
        self._map: Dict[str, str] = {}
        # Aliases are keyed case-insensitively, like discovered stems.
        self._aliases: Dict[str, str] = {
            k.lower(): v for k, v in (aliases or {}).items()
        }
        for root in scan_roots:
            root_path = Path(root)
            if not root_path.exists():
                continue
            for vmx in root_path.rglob("*.vmx"):
                name = vmx.stem.lower()
                self._map[name] = str(vmx)

    def _resolve_alias(self, alias: str, value: str) -> str:
        """Resolve one alias value to a .vmx path -- one hop, never recursive.

        A value is either path-shaped (a .vmx path, possibly out of scope) or
        name-shaped (a registry stem); it is never another alias.
        """
        path_shaped = value.endswith(".vmx") or "/" in value or "\\" in value
        if path_shaped:
            if Path(value).exists():
                return value
            raise ValueError(f"alias '{alias}' points to missing .vmx: {value}")
        key = value.lower()
        if key in self._map:
            return self._map[key]
        raise ValueError(f"alias '{alias}' -> '{value}': VM not found")

    def find(self, name: str) -> str:
        key = name.lower()
        # Explicit aliases win over fuzzy discovery (exact stem / substring).
        if key in self._aliases:
            return self._resolve_alias(name, self._aliases[key])
        if key in self._map:
            return self._map[key]
        matches = {k: v for k, v in self._map.items() if key in k}
        if len(matches) == 1:
            return next(iter(matches.values()))
        if len(matches) > 1:
            raise ValueError(f"Ambiguous VM name '{name}': matches {list(matches.keys())}")
        raise ValueError(f"VM '{name}' not found in scan roots")

    def name_for_path(self, vmx_path: str) -> Optional[str]:
        """Reverse-map a .vmx path to its registry name, or None if not in scope.

        Matches case-insensitively / path-normalized, so a running VM reported by
        ``vmrun list`` resolves to the canonical registry name (and credentials).
        """
        target = _normalize_path(vmx_path)
        for name, path in self._map.items():
            if _normalize_path(path) == target:
                return name
        return None

    def list_all(self) -> Dict[str, str]:
        return dict(self._map)
