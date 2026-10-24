"""Systemd templates for Forge/Loom: hardening and no TCP for Forge."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _unit(name: str) -> str:
	return (ROOT / "systemd" / name).read_text(encoding="utf-8")


def test_forge_unit_uses_uds_and_cgroup():
	text = _unit("redpill-forge.service")
	assert "--host %t/red-pill/forge/forge.sock" in text
	assert "--port" not in text
	assert "RestrictAddressFamilies=AF_UNIX" in text
	assert "PrivateNetwork=yes" in text
	assert "RuntimeDirectory=red-pill/forge" in text
	assert "UMask=0077" in text
	assert "MemoryMax=7G" in text
	assert "MemorySwapMax=0" in text


def test_loom_unit_is_loopback_and_cgroup():
	text = _unit("redpill-loom.service")
	assert "--host 127.0.0.1" in text
	assert "--port 52625" in text
	assert "MemoryMax=10G" in text
	assert "MemorySwapMax=0" in text
	assert "IPAddressDeny=any" in text
	assert "IPAddressAllow=localhost" in text
	assert "UMask=0077" in text


def test_installer_exists():
	assert (ROOT / "scripts" / "install_mini_services.sh").is_file()
