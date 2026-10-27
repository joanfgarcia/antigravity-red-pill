"""Tests de detección de versión de OpenCode y resolución del seed v2.

Contrato (2026-10-27): red-pill sólo siembra OpenCode **v2 exacto**. v1 sólo se
facilita como migración, una v3 futura no se asume compatible, y una versión que
no se puede determinar aborta (nunca se cae a un tier por defecto).
"""

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
	mod = _load()
	# Ningún test debe depender de la máquina que corre la suite.
	os.environ.pop("REDPILL_OPENCODE_MAJOR", None)
	os.environ.pop("REDPILL_OPENCODE_VERSION", None)
	return mod


@pytest.fixture()
def no_probes(ov, monkeypatch):
	monkeypatch.setattr(ov, "_probe_cli", lambda binary="opencode": (None, None))
	monkeypatch.setattr(ov, "_probe_dpkg", lambda: (None, None))
	return ov


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


def test_select_config_seed_solo_v2(ov, tmp_path) -> None:
	"""Sólo existe el seed de la versión soportada: sin layouts heredados."""
	settings = tmp_path / "settings"
	settings.mkdir()
	(settings / "opencode.jsonc").write_text("{}")  # legacy V1 plano: ignorado
	(settings / "opencode.v3.jsonc").write_text("{}")  # futuro: no asumido
	(settings / "v2").mkdir()
	(settings / "v2" / "opencode.jsonc").write_text("{}")

	assert ov.select_config_seed(str(tmp_path)).endswith(os.path.join("v2", "opencode.jsonc"))


def test_select_config_seed_sin_seed_v2(ov, tmp_path) -> None:
	settings = tmp_path / "settings"
	settings.mkdir()
	(settings / "opencode.jsonc").write_text("{}")
	assert ov.select_config_seed(str(tmp_path)) is None


def test_supported_major_es_2(ov) -> None:
	assert ov.SUPPORTED_MAJOR == 2


def test_no_queda_inferencia_por_forma_del_config(ov) -> None:
	"""La versión no se adivina mirando el config: nada de `config_is_v2`."""
	assert not hasattr(ov, "config_is_v2")


# ── support_error: el contrato, en una tabla ──────────────────────────────────
def _info(ov, installed=True, major=2, version="2.1.4", source="cli"):
	v = (major, 1, 4) if major is not None and version else None
	return ov.OpenCodeInfo(installed, v, version, major, source)


def test_support_error_no_instalado_pasa(ov) -> None:
	assert ov.support_error(_info(ov, installed=False, major=None, version=None)) is None


def test_support_error_v2_pasa(ov) -> None:
	assert ov.support_error(_info(ov)) is None


def test_support_error_v1_aborta_y_habla_de_migracion(ov) -> None:
	msg = ov.support_error(_info(ov, major=1, version="1.19.4"))
	assert "v1" in msg and "MIGRACIÓN" in msg.upper()
	assert "migrate_opencode_v2.py" in msg
	assert "Nada se ha modificado" in msg


def test_support_error_v3_no_se_asume(ov) -> None:
	msg = ov.support_error(_info(ov, major=3, version="3.0.0"))
	assert "v3" in msg and "no se asume compatible" in msg


def test_support_error_version_indeterminada_aborta(ov) -> None:
	msg = ov.support_error(_info(ov, major=None, version=None, source="undetected"))
	assert "No se ha podido determinar la versión" in msg
	assert "REDPILL_OPENCODE_VERSION" in msg


# ── detect_info: fuentes explícitas, sin defaults ─────────────────────────────
def test_env_override_major(ov, monkeypatch) -> None:
	monkeypatch.setenv("REDPILL_OPENCODE_MAJOR", "2")
	info = ov.detect_info()
	assert info.major == 2 and info.source == "env"


def test_env_override_version(ov, monkeypatch) -> None:
	monkeypatch.setenv("REDPILL_OPENCODE_VERSION", "opencode v2.3.5")
	info = ov.detect_info()
	assert info.version == (2, 3, 5) and info.source == "env"


def test_cli_gana_si_dpkg_no_esta(ov, monkeypatch) -> None:
	monkeypatch.setattr(ov, "_probe_cli", lambda binary="opencode": ((2, 1, 4), "opencode v2.1.4"))
	monkeypatch.setattr(ov, "_probe_dpkg", lambda: (None, None))
	monkeypatch.setattr(ov, "_config_dir_present", lambda: None)
	info = ov.detect_info()
	assert info.major == 2 and info.source == "cli"


def test_dpkg_gana_si_la_cli_no_responde(ov, monkeypatch) -> None:
	monkeypatch.setattr(ov, "_probe_cli", lambda binary="opencode": (None, None))
	monkeypatch.setattr(ov, "_probe_dpkg", lambda: ((2, 1, 4), "2.1.4"))
	monkeypatch.setattr(ov, "_config_dir_present", lambda: None)
	info = ov.detect_info()
	assert info.major == 2 and info.source == "dpkg"


def test_cli_y_dpkg_en_desacuerdo_no_se_elige_ninguno(ov, monkeypatch) -> None:
	"""Elegir "el mayor" sería una suposición: host transitorio → indeterminado."""
	monkeypatch.setattr(ov, "_probe_cli", lambda binary="opencode": ((1, 19, 4), "1.19.4"))
	monkeypatch.setattr(ov, "_probe_dpkg", lambda: ((2, 1, 4), "2.1.4"))
	monkeypatch.setattr(ov, "_config_dir_present", lambda: "/tmp/oc")
	info = ov.detect_info()
	assert info.major is None and info.source == "conflict"
	assert ov.support_error(info) is not None


def test_config_presente_pero_sin_version_no_se_asume(no_probes, monkeypatch) -> None:
	monkeypatch.setattr(no_probes, "_config_dir_present", lambda: "/tmp/oc")
	info = no_probes.detect_info()
	assert info.installed is True and info.major is None and info.source == "undetected"
	assert no_probes.support_error(info) is not None


def test_nada_instalado(no_probes, monkeypatch) -> None:
	monkeypatch.setattr(no_probes, "_config_dir_present", lambda: None)
	info = no_probes.detect_info()
	assert info.installed is False and info.major is None
	assert no_probes.support_error(info) is None
