"""Fase 3.5 del RFC-002: pase agéntico file-based + gate en sombra + staleness."""

import json

from red_pill.memento.agentic import (
	REFINE_SYSTEM,
	_extract_json,
	cross_ref_candidates,
	pending_agentic,
	run_agentic,
	slugify_title,
)
from red_pill.memento.registry import MementoRegistry
from red_pill.memento.render import compute_hash, extract_body, render_session, write_session


def fake_transport(significance=0.8):
	def transport(system, user, max_tokens):
		if system == REFINE_SYSTEM:
			return json.dumps(
				{"significance": significance, "emotion": "cyan", "intensity": 0.7, "theme": "memento_test", "relics": ["carpaccio"], "cross_refs": []}
			)
		return json.dumps({"title": "Panel adversarial de prueba", "summary": "Resumen denso de la sección.", "keywords": ["memento", "test"]})

	return transport


def _tree_with_session(tmp_path, n_messages=5, session="opencode:s1"):
	root = tmp_path / "memento"
	registry = MementoRegistry(path=tmp_path / "reg.json")
	msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"Mensaje {i} útil.", "timestamp": 1787234592.0 + i * 60} for i in range(n_messages)]
	rendered = render_session(session, "opencode", "opencode", msgs)
	write_session(root, rendered)
	registry.upsert(
		"opencode",
		session,
		{
			"dir": rendered.dir_rel,
			"month": rendered.month,
			"created_at": rendered.created_at,
			"message_count": rendered.message_count,
			"memento_hash": rendered.memento_hash,
			"workspace": "-home-joan-Workspace",
		},
	)
	return root, registry, rendered


def test_slugify_and_json_extraction():
	assert slugify_title("Panel adversarial: Qwen vs Hermes — árbol") == "panel-adversarial-qwen-vs-hermes-rbol"
	assert _extract_json('ruido {"a": 1, "b": {"c": 2}} cola')["b"]["c"] == 2
	assert _extract_json("sin json") is None


def test_run_agentic_writes_distill_refine_and_stamps_significance(tmp_path):
	root, registry, rendered = _tree_with_session(tmp_path)
	stats = run_agentic(root, registry, [("opencode", "opencode:s1")], fake_transport(0.8))
	assert stats == {"processed": 1, "failed": 0, "would_ingest": 1}

	session_dir = root / rendered.dir_rel
	distill_files = sorted((session_dir / "distill").glob("*.md"))
	refine_files = sorted((session_dir / "refine").glob("*.md"))
	assert len(distill_files) == 1 and distill_files[0].name == "001-panel-adversarial-de-prueba.md"
	assert len(refine_files) == 1 and refine_files[0].name == distill_files[0].name

	distill_text = distill_files[0].read_text(encoding="utf-8")
	assert "source_lines: memento/index.md#l" in distill_text and "title: Panel adversarial de prueba" in distill_text
	refine_text = refine_files[0].read_text(encoding="utf-8")
	assert "significance: 0.80" in refine_text and "distill_ref: distill/001-panel-adversarial-de-prueba.md" in refine_text

	# El sello en frontmatter NO mueve el cuerpo (contrato §4.5.1)
	index_text = (session_dir / "memento" / "index.md").read_text(encoding="utf-8")
	assert "significance: 0.8" in index_text
	assert compute_hash(extract_body(index_text)) == rendered.memento_hash

	agentic = registry.get("opencode", "opencode:s1")["agentic"]
	assert agentic["sections"] == 1 and agentic["gate_would_ingest"] is True
	assert agentic["hash"] == rendered.memento_hash


def test_low_significance_skips_refine_and_gate(tmp_path):
	root, registry, rendered = _tree_with_session(tmp_path)
	stats = run_agentic(root, registry, [("opencode", "opencode:s1")], fake_transport(0.1))
	assert stats["would_ingest"] == 0
	assert list((root / rendered.dir_rel / "refine").glob("*.md")) == []  # 0.1 < MEMENTO_REFINE_MIN_SIGNIFICANCE
	assert registry.get("opencode", "opencode:s1")["agentic"]["gate_would_ingest"] is False


def test_pending_agentic_detects_missing_and_stale(tmp_path):
	root, registry, _rendered = _tree_with_session(tmp_path)
	assert pending_agentic(registry) == [("opencode", "opencode:s1", "missing")]

	run_agentic(root, registry, [("opencode", "opencode:s1")], fake_transport())
	assert pending_agentic(registry) == []

	registry.get("opencode", "opencode:s1")["memento_hash"] = "otro-hash"  # simula re-render con contenido nuevo
	assert pending_agentic(registry) == [("opencode", "opencode:s1", "stale")]


def test_cross_ref_candidates_by_day_and_workspace(tmp_path):
	_root, registry, _rendered = _tree_with_session(tmp_path)
	registry.upsert("claude_code", "claude_code:x", {"dir": "d", "created_at": "2026-08-20T18:00:00Z"})  # mismo día
	registry.upsert("claude_code", "claude_code:y", {"dir": "d2", "created_at": "2026-01-01T00:00:00Z", "workspace": "-home-joan-Workspace"})
	registry.upsert("claude_code", "claude_code:z", {"dir": "d3", "created_at": "2026-01-02T00:00:00Z"})  # ni día ni workspace

	candidates = cross_ref_candidates(registry, "opencode", "opencode:s1")
	assert candidates == ["claude_code:x", "claude_code:y"]


async def test_memento_stale_janitor_emits_muted_signal(tmp_path):
	from unittest.mock import MagicMock

	from red_pill.swarm.agents.janitor_plugins.memento_stale import MementoStalePlugin

	root, registry, _rendered = _tree_with_session(tmp_path)
	run_agentic(root, registry, [("opencode", "opencode:s1")], fake_transport())
	registry.get("opencode", "opencode:s1")["memento_hash"] = "otro-hash"
	registry.save()

	mem = MagicMock()
	janitor = MagicMock()
	result = await MementoStalePlugin().execute(janitor, {}, registry_path=tmp_path / "reg.json", memory_manager=mem)
	assert result["stale"] == 1
	kwargs = mem.inject_signal.call_args.kwargs
	assert kwargs["name"] == "memento_stale_distill" and kwargs["muted"] is True
	assert json.loads(kwargs["message"]) == ["opencode|opencode:s1"]
