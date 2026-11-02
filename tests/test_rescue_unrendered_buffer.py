"""Rescate del buffer legacy a Memento (2026-11-02).

Los turnos sin `session_id` no se pueden renderizar por la vía normal y el tope de
30 días los borra en silencio. El rescate los escribe como sesiones sintéticas
`legacy-<día>` y marca los puntos para que el janitor pueda soltarlos sin pérdida.
"""

import importlib.util
import json
import time
from pathlib import Path

from qdrant_client.http import models

_SPEC = importlib.util.spec_from_file_location("rescue_buffer", Path("scripts/rescue_unrendered_buffer.py"))
assert _SPEC and _SPEC.loader
rescue_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rescue_mod)


def _seed(mm, content, ts, session_id=None):
	mm.storage.ensure_collection("interaction_memories")
	mm.client.upsert(
		collection_name="interaction_memories",
		points=[
			models.PointStruct(
				id=abs(hash((content, ts))) % (2**63),
				vector=[0.0] * mm.cfg.VECTOR_SIZE,
				payload={
					"content": content,
					"timestamp": ts,
					"metadata": {"session_id": session_id, "originator": "unknown"},
				},
			)
		],
	)


def _iso_day(ts):
	return time.strftime("%Y-%m-%d", time.gmtime(ts))


class TestRescate:
	def test_escribe_sesion_sintetica_y_marca_los_puntos(self, memory_manager, tmp_path):
		ts = time.time() - 40 * 86400
		_seed(memory_manager, "USER: hola\n\nASSISTANT: qué tal", ts)
		report = rescue_mod.rescue(memory=memory_manager, memento_root=tmp_path / "memento", registry_path=tmp_path / "reg.json")
		assert report["points"] == 1
		sid = f"legacy-{_iso_day(ts)}"
		assert report["written"] == 1
		index = tmp_path / "memento" / _iso_day(ts)[:7] / "legacy" / sid / "memento" / "index.md"
		assert index.exists(), index
		reg = json.loads((tmp_path / "reg.json").read_text())
		assert sid in reg["registry"]["legacy"]
		# El punto queda marcado: el janitor ya puede soltarlo sin perder nada.
		pts, _ = memory_manager.client.scroll("interaction_memories", limit=10, with_payload=True)
		assert (pts[0].payload.get("metadata") or {}).get("session_id") == sid

	def test_ignora_los_que_ya_tienen_sesion(self, memory_manager, tmp_path):
		_seed(memory_manager, "USER: a\n\nASSISTANT: b", time.time() - 40 * 86400, session_id="ses_viva")
		report = rescue_mod.rescue(memory=memory_manager, memento_root=tmp_path / "memento", registry_path=tmp_path / "reg.json")
		assert report["points"] == 0

	def test_dry_run_no_escribe_nada(self, memory_manager, tmp_path):
		_seed(memory_manager, "USER: a\n\nASSISTANT: b", time.time() - 40 * 86400)
		report = rescue_mod.rescue(
			dry_run=True, memory=memory_manager, memento_root=tmp_path / "memento", registry_path=tmp_path / "reg.json"
		)
		assert report["points"] == 1 and report["written"] == 0
		assert not (tmp_path / "memento").exists()
		assert not (tmp_path / "reg.json").exists()
