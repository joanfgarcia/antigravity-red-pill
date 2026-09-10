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
				{
					"significance": significance,
					"emotion": "cyan",
					"intensity": 0.7,
					"theme": "memento_test",
					"relics": ["carpaccio"],
					"cross_refs": [],
				}
			)
		return json.dumps({"title": "Panel adversarial de prueba", "summary": "Resumen denso de la sección.", "keywords": ["memento", "test"]})

	return transport


def _tree_with_session(tmp_path, n_messages=5, session="opencode:s1"):
	root = tmp_path / "memento"
	registry = MementoRegistry(path=tmp_path / "reg.json")
	msgs = [
		{"role": "user" if i % 2 == 0 else "assistant", "content": f"Mensaje {i} útil.", "timestamp": 1787234592.0 + i * 60}
		for i in range(n_messages)
	]
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


def test_run_agentic_aborta_con_deferral_si_llm_cae_consecutivamente(tmp_path):
	"""Regresión 2026-09-08: si el LLM local se cae (3 fallos consecutivos de
	conexión), el pase agéntico DEBE abortar con señal de defer en vez de acumular
	cientos de 'failed' (el backfill nocturno falló 595 sesiones así)."""
	root, registry, rendered = _tree_with_session(tmp_path)

	def llm_down_transport(system, user, max_tokens):
		raise ConnectionError("Failed to establish a new connection to localhost:8760")

	# 3 sesiones distintas, todas con el LLM caído
	stats = run_agentic(root, registry, [("opencode", "opencode:s1")] * 3, llm_down_transport)
	assert stats.get("aborted_llm_down") is True, "3 fallos de conexión consecutivos deben abortar con defer"
	assert stats["processed"] == 0
	assert stats["failed"] == 3

	# un fallo NO de conexión no aborta
	def weird_transport(system, user, max_tokens):
		raise ValueError("prompt demasiado largo")

	stats2 = run_agentic(root, registry, [("opencode", "opencode:s1")] * 5, weird_transport)
	assert stats2.get("aborted_llm_down") is None, "fallos no-de-conexión no deben disparar el deferral"


def test_is_llm_connection_error_detecta_errores_de_red():
	from red_pill.memento.agentic import _is_llm_connection_error

	assert _is_llm_connection_error(ConnectionError("Connection refused"))
	assert _is_llm_connection_error(ConnectionRefusedError("refused"))
	assert _is_llm_connection_error(Exception("Max retries exceeded ... Connection refused"))
	assert _is_llm_connection_error(Exception("Remote end closed connection without response"))
	assert not _is_llm_connection_error(ValueError("JSON inválido del LLM"))


def test_pending_agentic_detects_missing_and_stale(tmp_path):
	root, registry, _rendered = _tree_with_session(tmp_path)
	assert pending_agentic(registry) == [("opencode", "opencode:s1", "missing")]

	run_agentic(root, registry, [("opencode", "opencode:s1")], fake_transport())
	assert pending_agentic(registry) == []

	registry.get("opencode", "opencode:s1")["memento_hash"] = "otro-hash"  # simula re-render con contenido nuevo
	assert pending_agentic(registry) == [("opencode", "opencode:s1", "stale")]


def test_run_agentic_no_muere_con_memento_hash_stale(tmp_path):
	"""Regresión 2026-09-10: el assert 'significance stamp moved the body' comparaba
	contra el memento_hash del registry, que puede estar stale por un re-render
	concurrente → falso positivo que mató el backfill de 595 sesiones. Ahora la
	verificación compara el hash del body ANTES vs DESPUÉS del sello (mismo
	fichero en disco), independiente del registry: una sesión con hash stale se
	procesa y sella sin abortar el run."""
	root, registry, rendered = _tree_with_session(tmp_path)
	# Simula re-render concurrente: el disco cambió pero el registry guarda hash viejo.
	registry.get("opencode", "opencode:s1")["memento_hash"] = "hash-viejo-stale"

	stats = run_agentic(root, registry, [("opencode", "opencode:s1")], fake_transport())
	assert stats["processed"] == 1, "la sesión stale se debe procesar y sellar"
	assert stats["failed"] == 0

	# El sello se escribió y el cuerpo NO se movió (hash antes==después del sello).
	idx = root / rendered.dir_rel / "memento" / "index.md"
	text = idx.read_text(encoding="utf-8")
	assert "significance: 0.8" in text
	assert compute_hash(extract_body(text)) == rendered.memento_hash, "el sello no debe mover el cuerpo"


def test_pending_agentic_crash_recovery_detecta_disco_sin_marcado(tmp_path):
	"""Regresión 2026-09-07: si el proceso muere (reboot) tras destilar en disco pero
	antes de guardar el registry, las sesiones NO deben re-procesarse salvo --force."""
	root, registry, rendered = _tree_with_session(tmp_path)
	# Simula el crash: se escribieron distill/refine pero el marcado agentic nunca llegó al registry.
	run_agentic(root, registry, [("opencode", "opencode:s1")], fake_transport())
	registry.get("opencode", "opencode:s1").pop("agentic", None)  # el marcado se perdió

	# Sin root (modo legacy): sigue apareciendo como missing (comportamiento previo).
	assert pending_agentic(registry) == [("opencode", "opencode:s1", "missing")]
	# Con root (crash recovery): el disco dice que ya está destilada → NO pendiente.
	assert pending_agentic(registry, root=root) == []
	# --force: re-procesado explícito.
	assert pending_agentic(registry, root=root, force=True) == [("opencode", "opencode:s1", "missing")]


def test_run_agentic_guarda_registry_por_sesion(tmp_path, monkeypatch):
	"""El marcado agentic persiste en disco por sesión (no solo al final del run)."""
	root, registry, _rendered = _tree_with_session(tmp_path)
	saves = []
	monkeypatch.setattr(registry, "save", lambda: saves.append(1))
	run_agentic(root, registry, [("opencode", "opencode:s1")], fake_transport())
	assert len(saves) == 1, "run_agentic debe guardar el registry tras cada sesión procesada"


def test_run_agentic_escribe_checkpoint_bounded_por_sesion(tmp_path):
	"""Modo bounded: el checkpoint {processed, total} se escribe tras cada sesión
	con cuenta GLOBAL del registry (no del lote), para resume correcto."""
	import json

	root, registry, _rendered = _tree_with_session(tmp_path)
	cp = tmp_path / "state" / "prog.json"
	run_agentic(root, registry, [("opencode", "opencode:s1")], fake_transport(), checkpoint_path=cp)
	data = json.loads(cp.read_text(encoding="utf-8"))
	assert data["processed"] == 1 and data["total"] == 1

	# La cuenta es GLOBAL del registry: s1 ya marcada + s2 recién procesada → 2.
	rendered2 = render_session(
		"opencode:s2", "opencode", "opencode",
		[{"role": "user", "content": "Mensaje útil.", "timestamp": 1787234592.0}],
	)
	write_session(root, rendered2)
	registry.upsert("opencode", "opencode:s2", {"dir": rendered2.dir_rel, "month": rendered2.month, "created_at": rendered2.created_at, "memento_hash": rendered2.memento_hash})
	cp2 = tmp_path / "state" / "prog2.json"
	run_agentic(root, registry, [("opencode", "opencode:s2")], fake_transport(), checkpoint_path=cp2)
	data2 = json.loads(cp2.read_text(encoding="utf-8"))
	assert data2["processed"] == 2, "checkpoint debe contar el progreso global del registry"


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
