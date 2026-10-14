"""`model_approve.py` — registro de procedencia (manifiesto) + hashing local."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MOD = REPO / "scripts" / "model_approve.py"


def _load():
	spec = importlib.util.spec_from_file_location("model_approve", MOD)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def test_record_save_load_roundtrip(tmp_path):
	m = _load()
	p = tmp_path / "manifest.json"
	data = m.load_manifest(p)
	assert data["models"] == {}
	m.record_model(data, "x", {"source": "custom", "components": {"a": "h"}})
	m.save_manifest(p, data)
	again = m.load_manifest(p)
	assert again["models"]["x"]["components"]["a"] == "h"


def test_local_components_hash(tmp_path):
	m = _load()
	f = tmp_path / "enc.gguf"
	f.write_bytes(b"hello-world")
	comps = m.local_components([f"encoder={f}"])
	assert comps["encoder"] == hashlib.sha256(b"hello-world").hexdigest()


def test_local_components_falta_fichero(tmp_path):
	m = _load()
	with pytest.raises(SystemExit):
		m.local_components(["nope=/ruta/que/no/existe"])


def test_manifest_path_env(monkeypatch, tmp_path):
	m = _load()
	monkeypatch.setenv("REDPILL_MODEL_MANIFEST", str(tmp_path / "m.json"))
	assert m.manifest_path() == tmp_path / "m.json"
