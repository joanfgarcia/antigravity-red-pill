"""Tests de detección de versión de OpenCode y resolución de seed versionado."""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
VERSION_PATH = os.path.join(REPO_ROOT, "scripts", "opencode_version.py")


def _load() -> object:
	spec = importlib.util.spec_from_file_location("opencode_version_under_test", VERSION_PATH)
	mod = importlib.util.module_from_spec(spec)
	sys.modules["opencode_version_under_test"] = mod
	spec.loader.exec_module(mod)
	return mod


@pytest.fixture()
def ov():
	return _load()


@pytest.mark.parametrize(
	"text,expected",
	[
		("1.19.4", (1, 19, 4)),
		("opencode v2.1.4\n", (2, 1, 4)),
		("opencode v2.1.4 (build abc)", (2, 1, 4)),
		("1.19.4-1", (1, 19, 4)),
		("no version here", None),
		("", None),
		(None, None),
	],
)
def test_parse_version(ov, text, expected) -> None:
	assert ov.parse_version(text) == expected


def test_config_is_v2(ov) -> None:
	assert ov.config_is_v2({"plugin": ["x"], "mcp": {"S": {}}}) is False
	assert ov.config_is_v2({"plugins": []}) is True
	assert ov.config_is_v2({"permissions": []}) is True
	assert ov.config_is_v2({"providers": {}}) is True
	assert ov.config_is_v2({"mcp": {"servers": {}}}) is True


def test_select_config_seed_layouts(ov, tmp_path) -> None:
	settings = tmp_path / "settings"
	settings.mkdir()
	(settings / "opencode.jsonc").write_text("{}")
	(settings / "opencode.v3.jsonc").write_text("{}")
	(settings / "v2").mkdir()
	(settings / "v2" / "opencode.jsonc").write_text("{}")

	assert ov.select_config_seed(str(tmp_path), 2).endswith(os.path.join("v2", "opencode.jsonc"))
	assert ov.select_config_seed(str(tmp_path), 3).endswith("opencode.v3.jsonc")
	assert ov.select_config_seed(str(tmp_path), 1).endswith("opencode.jsonc")  # flat fallback
	assert ov.select_config_seed(str(tmp_path), 9).endswith("opencode.jsonc")  # unknown fallback


def test_plugin_pin_and_migration_gates(ov) -> None:
	assert ov.needs_v1_plugin_pin(1) is True
	assert ov.needs_v1_plugin_pin(2) is False
	assert ov.requires_config_migration(2) is True


def test_env_override_major(ov, monkeypatch) -> None:
	monkeypatch.setenv("REDPILL_OPENCODE_MAJOR", "2")
	info = ov.detect_info()
	assert info.major == 2 and info.source == "env"


def test_env_override_version(ov, monkeypatch) -> None:
	monkeypatch.setenv("REDPILL_OPENCODE_VERSION", "opencode v2.3.5")
	info = ov.detect_info()
	assert info.version == (2, 3, 5) and info.source == "env"


def test_highest_probe_wins(ov, monkeypatch) -> None:
	monkeypatch.delenv("REDPILL_OPENCODE_MAJOR", raising=False)
	monkeypatch.delenv("REDPILL_OPENCODE_VERSION", raising=False)
	monkeypatch.setattr(ov, "_probe_cli", lambda binary="opencode": ((1, 19, 4), "1.19.4"))
	monkeypatch.setattr(ov, "_probe_dpkg", lambda: ((2, 1, 4), "2.1.4"))
	monkeypatch.setattr(ov, "_config_dir_present", lambda: "/tmp/oc")
	info = ov.detect_info()
	assert info.major == 2 and info.source == "dpkg"


def test_config_shape_fallback(ov, monkeypatch, tmp_path) -> None:
	monkeypatch.delenv("REDPILL_OPENCODE_MAJOR", raising=False)
	monkeypatch.delenv("REDPILL_OPENCODE_VERSION", raising=False)
	monkeypatch.setattr(ov, "_probe_cli", lambda binary="opencode": (None, None))
	monkeypatch.setattr(ov, "_probe_dpkg", lambda: (None, None))
	monkeypatch.setattr(ov, "_config_dir_present", lambda: None)
	cfg = tmp_path / "opencode.jsonc"
	cfg.write_text('{"mcp": {"servers": {}}}')
	info = ov.detect_info(config_path=str(cfg))
	assert info.major == 2 and info.source == "config"
