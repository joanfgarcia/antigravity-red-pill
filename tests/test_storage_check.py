"""`storage_check.py` — detecta duplicados REALES (por hash) e ignora hardlinks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MOD = REPO / "scripts" / "storage_check.py"


def _load():
	spec = importlib.util.spec_from_file_location("storage_check", MOD)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def test_duplicado_real_y_hardlink(tmp_path):
	m = _load()
	content = b"x" * (2 * 1024 * 1024)  # 2 MB
	a = tmp_path / "a.bin"
	a.write_bytes(content)
	b = tmp_path / "b.bin"
	b.write_bytes(content)  # copia real (inodo distinto)
	c = tmp_path / "c.bin"
	c.hardlink_to(a)
	(tmp_path / "partial.bin.incomplete").write_bytes(b"z" * 10)

	by_size, incompletes = m._scan([tmp_path], min_size=1)
	real, _hardlinks = m._duplicates(by_size)

	real_paths = {p for d in real for p in d["paths"]}
	assert str(a) in real_paths and str(b) in real_paths
	# a y c comparten inodo → se colapsan a un representante (no cuenta 2ª vez)
	assert str(c) not in real_paths
	assert [p.name for p in incompletes] == ["partial.bin.incomplete"]


def test_hardlink_puro_no_es_duplicado(tmp_path):
	import os

	m = _load()
	content = b"y" * (2 * 1024 * 1024)
	a = tmp_path / "a.bin"
	a.write_bytes(content)
	os.link(a, tmp_path / "c.bin")
	by_size, _ = m._scan([tmp_path], min_size=1)
	real, hardlinks = m._duplicates(by_size)
	assert real == []  # solo hardlink → no ocupa de más
	assert hardlinks and len(hardlinks[0]["paths"]) == 2


def test_sin_duplicados(tmp_path):
	m = _load()
	(tmp_path / "one.bin").write_bytes(b"a" * (2 * 1024 * 1024))
	(tmp_path / "two.bin").write_bytes(b"b" * (2 * 1024 * 1024))
	by_size, _ = m._scan([tmp_path], min_size=1)
	real, _ = m._duplicates(by_size)
	assert real == []


def test_hf_models_en_multiples_caches(tmp_path):
	m = _load()
	# dos "cachés" con el mismo repo
	for root in ("c1", "c2"):
		d = tmp_path / root / "hub" / "models--org--name"
		d.mkdir(parents=True)
	multi = m._hf_models_in_multiple_caches([tmp_path / "c1", tmp_path / "c2"])
	assert "models--org--name" in multi and len(multi["models--org--name"]) == 2
