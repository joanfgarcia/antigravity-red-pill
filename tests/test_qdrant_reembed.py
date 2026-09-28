"""qdrant_reembed: dry-run sin escrituras, solo reescribe lo que no casa, reanudable e idempotente."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np


def _load():
	spec = importlib.util.spec_from_file_location("qdrant_reembed", Path("scripts/qdrant_reembed.py"))
	mod = importlib.util.module_from_spec(spec)
	assert spec.loader is not None
	spec.loader.exec_module(mod)
	return mod


def _vec(text: str) -> list:
	"""Embedding falso y determinista: un vector por texto."""
	rng = np.random.default_rng(abs(hash(text)) % (2**32))
	return rng.normal(size=8).tolist()


class _Encoder:
	def embed(self, texts, batch_size=64):
		return [_vec(t) for t in texts]


class _Client:
	def __init__(self, points):
		self.points = {p["id"]: p for p in points}
		self.writes = []
		self.snapshots = 0

	def count(self, collection_name, exact=True):
		return SimpleNamespace(count=len(self.points))

	def create_snapshot(self, collection_name):
		self.snapshots += 1
		return SimpleNamespace(name=f"snap-{self.snapshots}")

	def scroll(self, collection_name, limit, offset, with_vectors, with_payload):
		ids = sorted(self.points)
		start = 0 if offset is None else ids.index(offset)
		chunk = ids[start : start + limit]
		nxt = ids[start + limit] if start + limit < len(ids) else None
		return [SimpleNamespace(id=i, vector=self.points[i]["vector"], payload={"content": self.points[i]["content"]}) for i in chunk], nxt

	def update_vectors(self, collection_name, points, wait=True):
		for pv in points:
			self.writes.append(pv.id)
			self.points[pv.id]["vector"] = pv.vector


def _points(n_ok: int, n_bad: int, n_empty: int = 0):
	pts = []
	for i in range(n_ok):
		pts.append({"id": i, "content": f"ok {i}", "vector": _vec(f"ok {i}")})
	for i in range(n_ok, n_ok + n_bad):
		pts.append({"id": i, "content": f"mal {i}", "vector": _vec(f"otro texto {i}")})
	for i in range(n_ok + n_bad, n_ok + n_bad + n_empty):
		pts.append({"id": i, "content": "", "vector": _vec("x")})
	return pts


def test_dry_run_no_escribe(tmp_path):
	mod = _load()
	client = _Client(_points(5, 3))
	state = mod.run(client, _Encoder(), "work_memories", apply=False, checkpoint=None)
	assert client.writes == [] and client.snapshots == 0
	assert state["would_update"] == 3
	assert state["done"] is True


def test_apply_solo_reescribe_lo_que_no_casa_e_idempotente(tmp_path):
	mod = _load()
	client = _Client(_points(5, 3, n_empty=2))
	cp = tmp_path / "cp.json"
	state = mod.run(client, _Encoder(), "work_memories", apply=True, checkpoint=cp)
	assert sorted(client.writes) == [5, 6, 7]
	assert state["sin_texto"] == 2 and state["done"] is True
	assert client.snapshots == 1 and json.loads(cp.read_text())["snapshot"] == "snap-1"
	# Re-ejecutar tras completar: nada que hacer, ni snapshot nuevo.
	mod.run(client, _Encoder(), "work_memories", apply=True, checkpoint=cp)
	assert sorted(client.writes) == [5, 6, 7] and client.snapshots == 1
	# Barrido nuevo sobre la colección ya arreglada: 0 escrituras (convergente).
	cp.unlink()
	mod.run(client, _Encoder(), "work_memories", apply=True, checkpoint=cp, snapshot=False)
	assert sorted(client.writes) == [5, 6, 7]


def test_tramos_reanudan_por_offset(tmp_path, monkeypatch):
	mod = _load()
	monkeypatch.setattr(mod, "_SCROLL_PAGE", 4)
	client = _Client(_points(6, 6))
	cp = tmp_path / "cp.json"
	s1 = mod.run(client, _Encoder(), "work_memories", apply=True, checkpoint=cp, max_points=4)
	assert s1["scanned"] == 4 and s1["done"] is False
	s2 = mod.run(client, _Encoder(), "work_memories", apply=True, checkpoint=cp, max_points=4)
	assert s2["scanned"] == 8
	s3 = mod.run(client, _Encoder(), "work_memories", apply=True, checkpoint=cp, max_points=4)
	assert s3["scanned"] == 12 and s3["done"] is True
	assert sorted(client.writes) == list(range(6, 12))  # cada punto malo, una sola vez
	assert client.snapshots == 1
