from pathlib import Path

import pytest

from vmctl.vmx_parser import parse_vmx, parse_vmsd

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_vmx_basic():
    result = parse_vmx(str(FIXTURES / "test_vm.vmx"))
    assert result["displayName"] == "Test VM"
    assert result["guestOS"] == "windows9-64"
    assert result["memsize"] == "2048"
    assert result["numvcpus"] == "2"


def test_parse_vmx_skips_encoding():
    result = parse_vmx(str(FIXTURES / "test_vm.vmx"))
    assert ".encoding" not in result


def test_parse_vmx_skips_comments():
    result = parse_vmx(str(FIXTURES / "test_vm.vmx"))
    assert "This is a comment" not in str(result)


def test_parse_vmx_strips_quotes():
    result = parse_vmx(str(FIXTURES / "test_vm.vmx"))
    assert result["displayName"] == "Test VM"
    assert '"' not in result["displayName"]


def test_parse_vmsd():
    result = parse_vmsd(str(FIXTURES / "test_vm.vmsd"))
    assert result["snapshot.lastUID"] == "2"
    assert result["snapshot0.displayName"] == "init"
    assert result["snapshot1.displayName"] == "with-tools"


def test_parse_vmx_colon_key():
    result = parse_vmx(str(FIXTURES / "test_vm.vmx"))
    assert result["nvme0:0.present"] == "TRUE"
    assert result["nvme0:0.fileName"] == "test.vmdk"
