from pathlib import Path
from typing import Dict, List


class VMRegistry:
    def __init__(self, scan_roots: List[str]):
        self._map: Dict[str, str] = {}
        for root in scan_roots:
            root_path = Path(root)
            if not root_path.exists():
                continue
            for vmx in root_path.rglob("*.vmx"):
                name = vmx.stem.lower()
                self._map[name] = str(vmx)

    def find(self, name: str) -> str:
        key = name.lower()
        if key in self._map:
            return self._map[key]
        matches = {k: v for k, v in self._map.items() if key in k}
        if len(matches) == 1:
            return next(iter(matches.values()))
        if len(matches) > 1:
            raise ValueError(f"Ambiguous VM name '{name}': matches {list(matches.keys())}")
        raise ValueError(f"VM '{name}' not found in scan roots")

    def list_all(self) -> Dict[str, str]:
        return dict(self._map)
