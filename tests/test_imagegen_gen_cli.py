"""`gen_cli.py` — launcher por elenco: resolución de modelo (por id o por rol) y snap.

No genera (eso carga modelos): solo ejercita las funciones puras de resolución.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MOD = REPO / "scripts" / "imagegen" / "gen_cli.py"
EXAMPLE = REPO / "examples" / "media_profiles.yaml.example"


def _load(monkeypatch):
	# El harness exige el env del elenco (falla limpio sin él): se lo damos.
	monkeypatch.setenv("REDPILL_MEDIA_PROFILES", str(EXAMPLE))
	monkeypatch.setenv("REDPILL_RUNTIMES", str(REPO / "examples" / "runtimes.yaml.example"))
	spec = importlib.util.spec_from_file_location("gen_cli_under_test", MOD)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def test_resolve_por_id(monkeypatch):
	m = _load(monkeypatch)
	data = {"media_profiles": {"a": {"backend": "diffusers"}}, "media_roles": {}}
	assert m._resolve_model(data, "a", None) == "a"


def test_resolve_por_rol_salta_not_capable(monkeypatch):
	m = _load(monkeypatch)
	data = {
		"media_profiles": {"a": {"not_capable_for": ["r"]}, "b": {}},
		"media_roles": {"r": ["a", "b"]},
	}
	assert m._resolve_model(data, None, "r") == "b"


def test_resolve_rol_por_defecto(monkeypatch):
	m = _load(monkeypatch)
	data = {"media_profiles": {"x": {}}, "media_roles": {m.DEFAULT_ROLE: ["x"]}}
	assert m._resolve_model(data, None, None) == "x"


def test_modelo_desconocido_aborta(monkeypatch):
	m = _load(monkeypatch)
	with pytest.raises(SystemExit):
		m._resolve_model({"media_profiles": {}}, "no-existe", None)


def test_snap_multiplo(monkeypatch):
	m = _load(monkeypatch)
	assert m._snap(1080, 8) == 1080
	assert m._snap(1080, 16) == 1088
	assert m._snap(1000, 16) == 992
	assert m._snap(1024, 1) == 1024
