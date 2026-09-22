"""Fase 3.5 del RFC-002: pase agéntico file-based + gate en sombra + staleness."""

import json

import pytest

from red_pill.memento.agentic import (
	ANNOTATE_SOCIAL_SYSTEM,
	ANNOTATE_WORK_SYSTEM,
	DUAL_SCORE_SYSTEM,
	REFINE_MULTI_SYSTEM,
	REFINE_SOCIAL_SYSTEM,
	REFINE_SYSTEM,
	REFINE_WORK_SYSTEM,
	_extract_json,
	cross_ref_candidates,
	pending_agentic,
	run_agentic,
	slugify_title,
)
from red_pill.memento.registry import MementoRegistry
from red_pill.memento.render import compute_hash, extract_body, render_session, write_session


@pytest.fixture(autouse=True)
def _hermetic_pipeline_flags(monkeypatch):
	"""Los tests del pase legacy (refine) no deben depender del .env del operador:
	fija los flags a los defaults de sombra (annotate OFF, ascensión OFF)."""
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_FROM_RAW", False)
	monkeypatch.setattr(cfg, "MEMENTO_STATIC_ASCENSION_ENABLED", False)


def fake_transport(significance=0.8):
	def transport(system, user, max_tokens):
		if system in (REFINE_WORK_SYSTEM, REFINE_SOCIAL_SYSTEM):
			return json.dumps(
				[
					{
						"title": "Idea única de prueba",
						"significance": significance,
						"emotion": "cyan",
						"intensity": 0.7,
						"theme": "memento_test",
						"relics": ["carpaccio"],
						"cross_refs": [],
						"fragment_ref": 1,
						"category_score": 0.8 if system == REFINE_WORK_SYSTEM else 0.2,
					}
				]
			)
		if system == REFINE_MULTI_SYSTEM:
			return json.dumps(
				[
					{
						"title": "Idea única de prueba",
						"significance": significance,
						"emotion": "cyan",
						"intensity": 0.7,
						"theme": "memento_test",
						"relics": ["carpaccio"],
						"cross_refs": [],
						"fragment_ref": 1,
					}
				]
			)
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


def test_fit_prompt_recorta_al_presupuesto_de_contexto():
	"""Regresión 2026-09-14: un index.md/split token-denso excedía n_ctx (10240)
	→ el llama-server devolvía 500 y el backfill no avanzaba. El transporte debe
	recortar el user content al presupuesto, sin tocar los splits normales."""
	from red_pill.memento.agentic import _fit_prompt

	# split normal (12k chars ≈ 3k tokens) → sin recorte
	normal = "x" * 12000
	assert _fit_prompt(normal) == normal

	# index.md gigante (90k chars ≈ 22k tokens) → recortado + marca
	big = "y" * 90000
	fitted = _fit_prompt(big)
	assert len(fitted) < len(big)
	assert "[... truncado" in fitted


def test_run_agentic_writes_distill_refine_and_stamps_significance(tmp_path):
	root, registry, rendered = _tree_with_session(tmp_path)
	stats = run_agentic(root, registry, [("opencode", "opencode:s1")], fake_transport(0.8))
	assert stats == {"processed": 1, "failed": 0, "would_ingest": 1, "static_ascended": 0}

	session_dir = root / rendered.dir_rel
	distill_files = sorted((session_dir / "distill").glob("*.md"))
	refine_files = sorted((session_dir / "refine").glob("*.md"))
	assert len(distill_files) == 1 and distill_files[0].name == "001-panel-adversarial-de-prueba.md"
	assert len(refine_files) == 1 and refine_files[0].name == "001-idea-nica-de-prueba.md"

	distill_text = distill_files[0].read_text(encoding="utf-8")
	assert "source_lines: memento/index.md#l" in distill_text and "title: Panel adversarial de prueba" in distill_text
	record = json.loads((session_dir / "_session.json").read_text(encoding="utf-8"))
	assert record["stages"]["distill"]["sections"] == 1
	assert record["stages"]["distill"]["prompt_version"]
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


def test_is_llm_connection_error_detecta_timeouts_watchdog():
	"""2026-09-15: una generación que excede MEMENTO_LLM_TIMEOUT es un cuelgue
	(watchdog) → cuenta para el deferral, no un error del trabajo."""
	from red_pill.memento.agentic import _is_llm_connection_error

	assert _is_llm_connection_error(Exception("HTTPSConnectionPool ... Read timed out"))
	assert _is_llm_connection_error(Exception("Connection to 127.0.0.1 timed out"))
	assert _is_llm_connection_error(Exception("requests.exceptions.ReadTimeout: read timed out"))


def test_pending_agentic_redistill_since_filtra_lo_ya_reprocesado(tmp_path):
	"""2026-09-15: --redistill-round solo devuelve las sesiones de la ronda no
	re-procesadas (distilled_at anterior), para no repetir lo ya hecho al reanudar."""
	from red_pill.memento.agentic import pending_agentic

	root, registry, _rendered = _tree_with_session(tmp_path)
	run_agentic(root, registry, [("opencode", "opencode:s1")], fake_transport())
	# el distilled_at de s1 es ~ahora (>= ronda) → se salta
	assert pending_agentic(registry, force=True, redistill_since="2026-09-14T00:00:00Z") == []
	# una ronda futura no la ha alcanzado → vuelve como redistill
	assert pending_agentic(registry, force=True, redistill_since="2099-01-01T00:00:00Z") == [("opencode", "opencode:s1", "redistill")]
	# sin redistill_since (--force a pelo) → todas, como antes
	assert pending_agentic(registry, force=True) == [("opencode", "opencode:s1", "redistill")]


def test_advance_checkpoint_cuenta_solo_la_ronda(tmp_path):
	"""2026-09-15: con redistill_since el checkpoint bounded cuenta las sesiones
	de la ronda (distilled_at >= ronda), no todo el registry — así el driver
	cierra por contador de lo re-procesado en el re-destilado."""
	import json

	from red_pill.memento.agentic import _advance_checkpoint

	root, registry, _rendered = _tree_with_session(tmp_path)
	run_agentic(root, registry, [("opencode", "opencode:s1")], fake_transport())
	cp = tmp_path / "prog.json"

	# ronda pasada: s1 ya re-procesada → processed=1
	_advance_checkpoint(cp, registry, total=1, redistill_since="2026-09-14T00:00:00Z")
	assert json.loads(cp.read_text())["processed"] == 1
	# ronda futura: ninguna de la ronda → processed=0 (el driver sigue en curso)
	_advance_checkpoint(cp, registry, total=1, redistill_since="2099-01-01T00:00:00Z")
	assert json.loads(cp.read_text())["processed"] == 0


def test_pending_agentic_detects_missing_and_stale(tmp_path):
	root, registry, _rendered = _tree_with_session(tmp_path)
	assert pending_agentic(registry) == [("opencode", "opencode:s1", "missing")]

	run_agentic(root, registry, [("opencode", "opencode:s1")], fake_transport())
	assert pending_agentic(registry) == []

	registry.get("opencode", "opencode:s1")["memento_hash"] = "otro-hash"  # simula re-render con contenido nuevo
	assert pending_agentic(registry) == [("opencode", "opencode:s1", "stale")]


def test_run_agentic_con_annotate_flag_escribe_notas_registro_y_registry(tmp_path, monkeypatch):
	"""E2E del camino nocturno con `MEMENTO_ANNOTATE_FROM_RAW=ON`: run_agentic debe
	anotar (no refinar), dejar `_session.json` + `annotate/`, y registrar la versión
	de annotate en el registry."""
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_FROM_RAW", True)
	monkeypatch.setattr(cfg, "MEMENTO_STATIC_ASCENSION_ENABLED", False)

	def transport(system, user, max_tokens):
		if system == ANNOTATE_WORK_SYSTEM:
			return json.dumps(
				[
					{
						"title": "Fix del endpoint",
						"text": "Joan me pide el fix del endpoint y le explico el plan.",
						"significance": 0.9,
						"emotion": "cyan",
						"intensity": 0.6,
						"theme": "fix",
						"relics": [],
					}
				]
			)
		if system == ANNOTATE_SOCIAL_SYSTEM:
			return "[]"
		if system == DUAL_SCORE_SYSTEM:
			return json.dumps([{"i": 0, "work_score": 0.9, "social_score": 0.1}])
		return json.dumps({"title": "Panel adversarial de prueba", "summary": "Resumen denso de la sección.", "keywords": ["memento", "test"]})

	root, registry, rendered = _tree_with_session(tmp_path)
	stats = run_agentic(root, registry, [("opencode", "opencode:s1")], transport)
	assert stats["processed"] == 1 and stats["failed"] == 0
	session_dir = root / rendered.dir_rel
	notes = sorted((session_dir / "annotate").glob("*.md"))
	assert len(notes) == 1
	assert "Joan me pide el fix" in notes[0].read_text(encoding="utf-8")
	assert list((session_dir / "refine").glob("*.md")) == []  # el refine legacy no corre
	record = json.loads((session_dir / "_session.json").read_text(encoding="utf-8"))
	assert record["stages"]["annotate"]["notas"] == 1
	entry = registry.get("opencode", "opencode:s1")
	assert entry["agentic"]["annotate_prompt_version"]
	assert entry["agentic"]["annotate_notes"] == 1


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
		"opencode:s2",
		"opencode",
		"opencode",
		[{"role": "user", "content": "Mensaje útil.", "timestamp": 1787234592.0}],
	)
	write_session(root, rendered2)
	registry.upsert(
		"opencode",
		"opencode:s2",
		{"dir": rendered2.dir_rel, "month": rendered2.month, "created_at": rendered2.created_at, "memento_hash": rendered2.memento_hash},
	)
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


# --- Fase 4 §5.4.1: distill fragmentado (partición por turnos con solape) ---


def test_split_messages_parses_turns():
	from red_pill.memento.agentic import _split_messages

	content = "## 2026-08-01 10:00:00 — Usuario\nhola\n\n## 2026-08-01 10:01:00 — Asistente\nadiós"
	msgs = _split_messages(content)
	assert len(msgs) == 2
	assert msgs[0][0].startswith("## 2026-08-01 10:00:00")
	assert msgs[0][1] == "hola"
	assert msgs[1][1] == "adiós"


def test_fragment_messages_overlap():
	from red_pill.memento.agentic import _fragment_messages

	messages = [(f"h{i}", f"body {i}") for i in range(6)]
	frags = _fragment_messages(messages, max_chars=30, overlap=2)
	assert len(frags) >= 2
	# el solape repite los últimos `overlap` mensajes del fragmento anterior
	if len(frags) >= 2:
		prev_tail = [m[0] for m in frags[0][-2:]]
		next_head = [m[0] for m in frags[1][:2]]
		assert prev_tail == next_head


def test_fragment_messages_subparte_un_turno_gigante():
	"""2026-09-15 (incidente b3f27f38): un único turno de 62K chars (una sola
	cabecera `## ts — role`) no cabía en 32K y no se fragmentaba. Ahora se
	sub-particiona por líneas con solape y la cabecera repetida."""
	from red_pill.memento.agentic import _fragment_messages, _split_long_message

	body = "\n".join(f"línea {i:03d} contenido de prueba" for i in range(10))
	messages = [("## 2026-03-07 — Usuario", body)]
	frags = _fragment_messages(messages, max_chars=150, overlap=2)
	assert len(frags) >= 3, "el turno gigante debe sub-particionarse en varios trozos"
	for frag in frags:
		assert frag[0][0] == "## 2026-03-07 — Usuario"  # cabecera repetida en cada trozo

	subs = _split_long_message(messages[0], max_chars=150, overlap=2)
	assert len(subs) >= 3
	# el solape repite las últimas líneas del trozo anterior al siguiente
	assert subs[0][1].split("\n")[-2:] == subs[1][1].split("\n")[:2]


def test_distill_session_fragments_long_work_unit(tmp_path):
	from red_pill.memento.agentic import _split_messages, distill_session

	root, _registry, rendered = _tree_with_session(tmp_path, n_messages=0)
	# Un work unit largo: index con muchos turnos largos
	dir_rel = rendered.dir_rel
	index_file = root / dir_rel / "memento" / "index.md"
	turns = "\n\n".join(
		f"## 2026-08-01 {10 + i:02d}:00:00 — {'Usuario' if i % 2 == 0 else 'Asistente'}\n{'mensaje ' + 'z' * 800 + str(i)}" for i in range(20)
	)
	index_file.write_text("---\nsession_id: opencode:s1\n---\n" + turns, encoding="utf-8")

	prompts = []

	def capturing_transport(system, user, max_tokens):
		prompts.append(user)
		return json.dumps({"title": f"Fragmento {len(prompts)}", "summary": f"resumen-{len(prompts)}", "keywords": ["frag"]})

	sections = distill_session(root, dir_rel, "opencode:s1", "opencode", capturing_transport, max_chars=5000, overlap=2)

	# partición real: hay turnos y el índice es largo
	assert len(_split_messages(turns)) >= 4
	assert len(sections) >= 2, "un work unit largo debe producir varios fragmentos"

	# marcado de parte y slugs NNN-<slug>-fragmento-i-de-N.md
	frags = [s for s in sections if s["fragments_total"] is not None]
	assert len(frags) == len(sections)
	total = frags[0]["fragments_total"]
	assert all(s["fragments_total"] == total for s in frags)
	assert all(f"-fragmento-{s['fragment']}-de-{total}" in s["file"] for s in frags)

	# prompt de continuación lleva el resumen anterior (memoria emocional)
	assert "resumen-1" in prompts[1]
	assert "continuación" in prompts[1].lower() or "continuation" in prompts[1].lower()

	# los ficheros existen y tienen el marcado en frontmatter
	distill_dir = root / dir_rel / "distill"
	for s in frags:
		text = (distill_dir / s["file"]).read_text(encoding="utf-8")
		assert f"fragment: {s['fragment']}" in text
		assert f"fragments_total: {total}" in text
		assert f"fragment_of: {s['nnn']}" in text


# --- Fase 4 §5.4.2: refine multi-idea (M destills → N ideas) ---


def test_extract_json_array():
	from red_pill.memento.agentic import _extract_json_array

	assert _extract_json_array('ruido [{"a": 1}, {"b": 2}] cola') == [{"a": 1}, {"b": 2}]
	assert _extract_json_array("[]") == []
	assert _extract_json_array("sin array") is None


def test_http_transport_reintenta_recortando_ante_500():
	from unittest.mock import MagicMock, patch

	from red_pill.memento.agentic import http_transport

	content = "x" * 5000

	def resp(status, text="{}"):
		m = MagicMock()
		m.status_code = status
		m.json.return_value = {"choices": [{"message": {"content": text}}]}
		m.raise_for_status.side_effect = None if status == 200 else __import__("requests").exceptions.HTTPError()
		return m

	with patch("requests.post") as mock_post:
		mock_post.side_effect = [resp(500), resp(200, '{"ok": 1}')]
		out = http_transport("sys", content, 64)
		assert out == '{"ok": 1}'
		# el segundo intento recortó el prompt (0.6 × 5000)
		assert len(mock_post.call_args_list[1].kwargs["json"]["messages"][1]["content"]) < 4000


def test_http_transport_exito():
	from unittest.mock import MagicMock, patch

	from red_pill.memento.agentic import http_transport

	m = MagicMock()
	m.status_code = 200
	m.json.return_value = {"choices": [{"message": {"content": "RESULT"}}]}
	with patch("requests.post", return_value=m):
		assert http_transport("sys", "user", 64) == "RESULT"


def test_engine_id_detecta_modelo_y_cachea(monkeypatch):
	from red_pill.memento import agentic

	class FakeResp:
		def read(self):
			return b'{"data": [{"id": "modelo-x"}], "object": "list"}'

	monkeypatch.setattr(agentic.runtime, "_ENGINE_CACHE", None)
	monkeypatch.setattr(__import__("urllib.request", fromlist=["request"]), "urlopen", lambda *a, **k: FakeResp())
	assert agentic.engine_id() == "modelo-x"
	assert agentic.engine_id() == "modelo-x"  # cacheado (urlopen solo se llama 1 vez)


def test_as_list_normaliza():
	from red_pill.memento.agentic import _as_list

	assert _as_list(["a"]) == ["a"]
	assert _as_list(None) == []
	assert _as_list("s") == ["s"]
	assert _as_list(2) == []  # int (el LLM a veces devuelve int) → no revienta


def test_dedup_ideas_fusiona_work_y_social_duplicadas():
	"""2026-09-15: el MISMO fragmento produce la idea técnica en WORK (cat~0.9) y
	su versión social en SOCIAL (cat~0.3). La dedup conserva UNA (mayor significance)."""
	from red_pill.memento.agentic import _dedup_ideas

	ideas = [
		{
			"title": "Ajustar formato HKDFLabel para alinear",
			"theme": "hkdf_label_format",
			"significance": 0.95,
			"category_score": 0.95,
			"relics": ["formato HKDFLabel"],
		},
		{
			"title": "Joan me dice que el formato HKDFLabel",
			"theme": "hkdf_label_format",
			"significance": 0.85,
			"category_score": 0.30,
			"relics": ["formato HKDFLabel"],
		},
	]
	kept = _dedup_ideas(ideas)
	assert len(kept) == 1
	assert kept[0]["significance"] == 0.95  # la de mayor significance (work)
	assert kept[0]["category_score"] == 0.95


def test_dedup_ideas_conserva_ideas_distintas():
	from red_pill.memento.agentic import _dedup_ideas

	ideas = [
		{"title": "Refactor del endpoint de autenticación", "theme": "auth_endpoint", "significance": 0.9, "category_score": 0.9, "relics": []},
		{"title": "Reflexión personal sobre el descanso", "theme": "descanso_personal", "significance": 0.6, "category_score": 0.1, "relics": []},
	]
	assert len(_dedup_ideas(ideas)) == 2


def test_trazabilidad_engine_y_prompt_version(tmp_path, monkeypatch):
	"""2026-09-15: distill y refine guardan el modelo real y la versión del prompt
	con que se hicieron — permite saber si un engrama se hizo con granite/aya y si
	los prompts cambiaron desde entonces."""
	from red_pill.memento import agentic
	from red_pill.memento.agentic import distill_session, refine_session

	monkeypatch.setattr(agentic.runtime, "engine_id", lambda: "Granite-4.1-8B-Q4_K_M.gguf")
	monkeypatch.setattr(agentic.runtime, "distill_prompt_version", lambda: "d123")
	monkeypatch.setattr(agentic.runtime, "refine_prompt_version", lambda: "r456")

	root, _registry, rendered = _tree_with_session(tmp_path)
	sections = distill_session(root, rendered.dir_rel, "opencode:s1", "opencode", fake_transport())
	refine_session(root, rendered.dir_rel, "opencode:s1", "opencode", sections, [], fake_transport(), 0.3)

	sd = root / rendered.dir_rel
	distill_text = next((sd / "distill").glob("*.md")).read_text(encoding="utf-8")
	refine_text = next((sd / "refine").glob("*.md")).read_text(encoding="utf-8")
	assert "engine: Granite-4.1-8B-Q4_K_M.gguf" in distill_text
	assert "prompt_version: d123" in distill_text
	assert "engine: Granite-4.1-8B-Q4_K_M.gguf" in refine_text
	assert "prompt_version: r456" in refine_text

	# el registry también lo guarda
	run_agentic(root, _registry, [("opencode", "opencode:s1")], fake_transport())
	ag = _registry.get("opencode", "opencode:s1")["agentic"]
	assert ag["engine"] == "Granite-4.1-8B-Q4_K_M.gguf"
	assert "distill_prompt_version" in ag and "refine_prompt_version" in ag


def test_refine_session_multi_idea(tmp_path):
	"""3 destills que forman 2 ideas → 2 refine (no 3, no 1)."""
	from red_pill.memento.agentic import REFINE_SOCIAL_SYSTEM, REFINE_WORK_SYSTEM, refine_session

	root, _registry, rendered = _tree_with_session(tmp_path)
	sections = [
		{"nnn": "001", "file": "001-a.md", "title": "A", "summary": "sA", "source_lines": "l1-5", "fragment": 1, "fragments_total": 2},
		{"nnn": "001", "file": "001-b.md", "title": "B", "summary": "sB", "source_lines": "l1-5", "fragment": 2, "fragments_total": 2},
		{"nnn": "002", "file": "002-c.md", "title": "C", "summary": "sC", "source_lines": "l6-9", "fragment": None, "fragments_total": None},
	]

	def multi_transport(system, user, max_tokens):
		if system in (REFINE_WORK_SYSTEM, REFINE_SOCIAL_SYSTEM):
			if "Title: C" in user:  # work unit 002 → sin ideas
				return "[]"
			return json.dumps(
				[
					{
						"title": "Refactor del endpoint de auth",
						"significance": 0.7,
						"emotion": "blue",
						"intensity": 0.5,
						"theme": "auth_endpoint",
						"relics": ["desbloqueado el lint"],
						"cross_refs": [],
						"fragment_ref": 1,
						"category_score": 0.8 if system == REFINE_WORK_SYSTEM else 0.2,
					},
					{
						"title": "Reflexión sobre el descanso",
						"significance": 0.6,
						"emotion": "teal",
						"intensity": 0.4,
						"theme": "descanso_personal",
						"relics": [],
						"cross_refs": [],
						"fragment_ref": 2,
					},
				]
			)
		return json.dumps({})

	msig = refine_session(root, rendered.dir_rel, "opencode:s1", "opencode", sections, [], multi_transport, min_significance=0.3)
	assert msig == 0.7

	refine_dir = root / rendered.dir_rel / "refine"
	files = sorted(p.name for p in refine_dir.glob("*.md"))
	# work unit 001 → 2 ideas (2 ficheros); work unit 002 → transport dict vacío → _extract_json_array devuelve None → 0
	assert files == ["001-refactor-del-endpoint-de-auth.md", "001-reflexi-n-sobre-el-descanso.md"]

	text = (refine_dir / "001-reflexi-n-sobre-el-descanso.md").read_text(encoding="utf-8")
	assert "distill_ref: distill/001-b.md" in text  # fragment_ref=2 → origen del 2º fragment
	assert "fragment_ref: 2" in text
	assert "significance: 0.60" in text
	assert "category_score: 0.50" in text  # default del curador si no lo puntúa


def test_refine_session_filters_below_min(tmp_path):
	from red_pill.memento.agentic import refine_session

	root, _registry, rendered = _tree_with_session(tmp_path)
	sections = [{"nnn": "001", "file": "001-a.md", "title": "A", "summary": "sA", "source_lines": "l1-5", "fragment": None, "fragments_total": None}]

	def low_transport(system, user, max_tokens):
		return json.dumps([{"title": "Idea baja", "significance": 0.1, "theme": "z", "relics": [], "cross_refs": []}])

	refine_session(root, rendered.dir_rel, "opencode:s1", "opencode", sections, [], low_transport, min_significance=0.3)
	assert list((root / rendered.dir_rel / "refine").glob("*.md")) == []


def test_refine_session_empty_array_no_files(tmp_path):
	from red_pill.memento.agentic import refine_session

	root, _registry, rendered = _tree_with_session(tmp_path)
	sections = [{"nnn": "001", "file": "001-a.md", "title": "A", "summary": "sA", "source_lines": "l1-5", "fragment": None, "fragments_total": None}]

	def empty_transport(system, user, max_tokens):
		return "[]"

	msig = refine_session(root, rendered.dir_rel, "opencode:s1", "opencode", sections, [], empty_transport, min_significance=0.3)
	assert msig == 0.0
	assert list((root / rendered.dir_rel / "refine").glob("*.md")) == []


def _alta(system, user, max_tokens):
	return json.dumps([{"title": "Idea alta", "significance": 0.9, "theme": "t", "relics": [], "cross_refs": []}])


def test_refine_preserva_sello_de_ascension_en_redistill(tmp_path):
	"""La re-destilización no debe des-ascender: si la identidad (`source_lines`)
	no cambió, el refine conserva el sello (ascender es upsert idempotente)."""
	from red_pill.memento.agentic import refine_session
	from red_pill.memento.render import update_frontmatter_fields

	root, _registry, rendered = _tree_with_session(tmp_path)
	sections = [{"nnn": "001", "file": "001-a.md", "title": "A", "summary": "sA", "source_lines": "l1-5", "fragment": None, "fragments_total": None}]

	refine_session(root, rendered.dir_rel, "opencode:s1", "opencode", sections, [], _alta, min_significance=0.3)
	refine_path = next((root / rendered.dir_rel / "refine").glob("*.md"))
	update_frontmatter_fields(refine_path, {"ascended": True, "ascended_at": "2026-09-17T00:00:00Z", "ascended_to": "work_memories"})

	refine_session(root, rendered.dir_rel, "opencode:s1", "opencode", sections, [], _alta, min_significance=0.3)
	text = next((root / rendered.dir_rel / "refine").glob("*.md")).read_text(encoding="utf-8")
	assert "ascended: true" in text
	assert "ascended_to: work_memories" in text


def test_refine_no_preserva_sello_si_cambia_source_lines(tmp_path):
	"""Si el contenido avanzó (otro `source_lines`), el refine es nuevo: sin sello."""
	from red_pill.memento.agentic import refine_session
	from red_pill.memento.render import update_frontmatter_fields

	root, _registry, rendered = _tree_with_session(tmp_path)
	s1 = [{"nnn": "001", "file": "001-a.md", "title": "A", "summary": "sA", "source_lines": "l1-5", "fragment": None, "fragments_total": None}]
	s2 = [{"nnn": "001", "file": "001-a.md", "title": "A", "summary": "sA", "source_lines": "l1-9", "fragment": None, "fragments_total": None}]

	refine_session(root, rendered.dir_rel, "opencode:s1", "opencode", s1, [], _alta, min_significance=0.3)
	refine_path = next((root / rendered.dir_rel / "refine").glob("*.md"))
	update_frontmatter_fields(refine_path, {"ascended": True, "ascended_at": "2026-09-17T00:00:00Z", "ascended_to": "work_memories"})

	refine_session(root, rendered.dir_rel, "opencode:s1", "opencode", s2, [], _alta, min_significance=0.3)
	text = next((root / rendered.dir_rel / "refine").glob("*.md")).read_text(encoding="utf-8")
	assert "ascended: false" in text
