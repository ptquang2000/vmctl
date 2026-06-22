from pathlib import Path
from typing import Dict


def _parse_kvfile(path: str) -> Dict[str, str]:
    result = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.lower().startswith(".encoding"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip().strip('"')
    return result


def parse_vmx(vmx_path: str) -> Dict[str, str]:
    return _parse_kvfile(vmx_path)


def parse_vmsd(vmsd_path: str) -> Dict[str, str]:
    return _parse_kvfile(vmsd_path)
