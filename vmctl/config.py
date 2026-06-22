import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".vmctl" / "config.json"

_DEFAULTS = {
    "vmware_home": r"C:\Program Files\VMware\VMware Workstation",
    "scan_roots": [],
    "credentials": {},
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return dict(_DEFAULTS)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    for k, v in _DEFAULTS.items():
        cfg.setdefault(k, v)
    return cfg


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
