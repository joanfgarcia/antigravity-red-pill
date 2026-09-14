"""Fase 4 §6.10: replay del query log de recall (umbral Q4)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace


def _load_module():
	import importlib.util

	spec = importlib.util.spec_from_file_location("memento_replay_recall", Path("scripts/memento_replay_recall.py"))
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def test_load_queries_parses_jsonl(tmp_path: Path):
	mod = _load_module()
	log = tmp_path / "search_query_log.jsonl"
	log.write_text(
		json.dumps({"ts": "2026-09-01T00:00:00Z", "action": "search_memory_research", "query": "query a"})
		+ "\n"
		+ json.dumps({"ts": "2026-09-02T00:00:00Z", "action": "search_memory_research", "query": "query b"})
		+ "\n"
		+ "línea corrupta\n",
		encoding="utf-8",
	)
	queries = mod.load_queries(log)
	assert len(queries) == 2
	assert queries[0]["query"] == "query a"
	assert queries[1]["query"] == "query b"


def test_replay_recall_counts_memento_hits(tmp_path: Path):
	mod = _load_module()
	log = tmp_path / "search_query_log.jsonl"
	log.write_text(json.dumps({"ts": "2026-09-01T00:00:00Z", "action": "search_memory_research", "query": "q"}) + "\n", encoding="utf-8")

	class FakeClient:
		def collection_exists(self, name):
			return name in ("work_memories", "social_memories")

	class FakeMM:
		def __init__(self):
			self.client = FakeClient()

		def search_and_reinforce(self, collection, query, limit, caller):
			# un hit normal + un hit ascendido (origin=memento)
			return [
				SimpleNamespace(score=0.9, payload={"origin": "memento", "theme": "x"}),
				SimpleNamespace(score=0.7, payload={"origin": None}),
			]

	mm = FakeMM()
	stats = mod.replay_recall(memory_manager=mm, log_path=log)
	assert stats["queries"] == 1
	assert stats["con_hits"] == 1
	assert stats["hit_rate"] == 100.0
	assert stats["hits_total"] == 4  # 2 hits × 2 colecciones
	assert stats["hits_memento"] == 2
	assert stats["pct_hits_memento"] == 50.0
