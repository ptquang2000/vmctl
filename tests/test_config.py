import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import vmctl.config as config_module
from vmctl.config import load_config, save_config


def test_load_config_defaults(tmp_path):
    cfg_path = tmp_path / ".vmctl" / "config.json"
    with patch.object(config_module, "CONFIG_PATH", cfg_path):
        cfg = load_config()
    assert "vmware_home" in cfg
    assert "scan_roots" in cfg
    assert "credentials" in cfg
    assert cfg["credentials"] == {}


def test_load_config_from_file(tmp_path):
    cfg_path = tmp_path / "config.json"
    data = {
        "vmware_home": r"C:\custom\VMware",
        "scan_roots": [r"C:\VMs"],
        "credentials": {"myvm": {"user": "admin", "password": "s3cr3t"}},
    }
    cfg_path.write_text(json.dumps(data))
    with patch.object(config_module, "CONFIG_PATH", cfg_path):
        cfg = load_config()
    assert cfg["vmware_home"] == r"C:\custom\VMware"
    assert cfg["scan_roots"] == [r"C:\VMs"]
    assert cfg["credentials"]["myvm"]["user"] == "admin"


def test_save_and_reload_config(tmp_path):
    cfg_path = tmp_path / ".vmctl" / "config.json"
    with patch.object(config_module, "CONFIG_PATH", cfg_path):
        cfg = load_config()
        cfg["credentials"]["testvm"] = {"user": "u", "password": "p"}
        save_config(cfg)
        reloaded = load_config()
    assert reloaded["credentials"]["testvm"]["user"] == "u"


def test_load_config_missing_keys_filled_with_defaults(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text('{"vmware_home": "custom"}')
    with patch.object(config_module, "CONFIG_PATH", cfg_path):
        cfg = load_config()
    assert "scan_roots" in cfg
    assert "credentials" in cfg
