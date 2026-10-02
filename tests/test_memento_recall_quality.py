"""Feedback de recall 2026-09-25: texto a embeber, recall híbrido + MMR, dedup post-rewrite y huérfanos."""

from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest

from red_pill.memento import embed_text, hybrid
from red_pill.memento.agentic import annotate

# ── texto a embeber ──


@pytest.mark.parametrize(
	"raw, expected",
	[
		("Joan me dijo que el daemon perdía la VRAM.", "El daemon perdía la VRAM."),
		("Joan me pidió que revisara la adenda de Initech.", "Revisara la adenda de Initech."),
		("Le expliqué a Joan que el fallo era de FA.", "El fallo era de FA."),
		("Le expliqué que había que reiniciar.", "Había que reiniciar."),
		("Joan corrigió el bug de tree_hash.", "Joan corrigió el bug de tree_hash."),  # sin muletilla: intacto
		("Joan, el operador catalán, detectó el fallo.", "Joan detectó el fallo."),
	],
)
def test_strip_lead(raw, expected):
	assert embed_text.strip_lead(raw) == expected


def test_engram_embed_text_pone_el_ancla_delante():
	out = embed_text.engram_embed_text("Joan me dijo que la adenda tenía trampas.", "contract_review", ["Initech", "renovación"])
	assert out == "contract review · Initech, renovación · La adenda tenía trampas."


def test_embedding_text_for_respeta_flag_y_tipo(monkeypatch):
	import red_pill.config as cfg

	payload = {"node_type": "memento_engram", "theme": "t", "relics": ["R"]}
	monkeypatch.setattr(cfg, "MEMENTO_EMBED_ENRICHED", False, raising=False)
	assert embed_text.embedding_text_for("Joan me dijo que X.", payload) == "Joan me dijo que X."
	monkeypatch.setattr(cfg, "MEMENTO_EMBED_ENRICHED", True, raising=False)
	assert embed_text.embedding_text_for("Joan me dijo que X.", payload) == "t · R · X."
	assert embed_text.embedding_text_for("texto", {"node_type": "chronicle_node"}) == "texto"  # no-memento: intacto


# ── recall híbrido ──


def test_salient_terms_prioriza_identificadores_y_nombres():
	terms = hybrid.salient_terms("adenda de renovación de Initech y el bug de tree_hash en BIT-003")
	assert terms[:2] == ["BIT-003", "tree_hash"] or terms[:2] == ["tree_hash", "BIT-003"]
	assert "Initech" in terms


def test_rrf_merge_premia_consenso():
	assert hybrid.rrf_merge([["a", "b", "c"], ["c", "d"]])[0] == "c"


def test_mmr_select_evita_parafrasis():
	q = [1.0, 0.0, 0.0]
	vecs = [[0.95, 0.31, 0.0], [0.94, 0.33, 0.0], [0.7, 0.0, 0.71]]  # 0 y 1 casi iguales
	picked = hybrid.mmr_select(q, ["a", "b", "c"], vecs, k=2, lam=0.5)
	assert picked == ["a", "c"]


@pytest.mark.skipif(shutil.which("rg") is None, reason="necesita ripgrep")
def test_memento_keyword_hits_mapea_linea_a_nota(tmp_path):
	sess = tmp_path / "2026-08" / "memory_queue" / "s1"
	(sess / "memento").mkdir(parents=True)
	(sess / "memento" / "index.md").write_text("cabecera\n" * 3 + "Revisión de la adenda de Initech\n" + "relleno\n" * 20, encoding="utf-8")
	(sess / "annotate").mkdir()
	note = "---\nsource_lines: memento/index.md#l1-10\nascended: true\nascended_to: work_memories\nascended_point_id: p-1\n---\n\ntexto"
	(sess / "annotate" / "001-a.md").write_text(note, encoding="utf-8")
	(sess / "annotate" / "002-b.md").write_text(note.replace("l1-10", "l11-30").replace("p-1", "p-2"), encoding="utf-8")
	hits = hybrid.memento_keyword_hits("¿qué pasó con Initech?", "work_memories", root=tmp_path)
	assert [pid for pid, _ in hits] == ["p-1"]


# ── dedup post-rewrite y criterio de voz ──


def test_dedup_post_rewrite_colapsa_exactos_y_parafrasis():
	notes = [
		{"title": "A", "text": "La GPU operaba a 50W y el firmware lo causaba.", "significance": 0.9, "flags": []},
		{"title": "B", "text": "La GPU operaba a 50W y el firmware lo causaba.", "significance": 0.8, "flags": []},
		{"title": "C", "text": "Paráfrasis del mismo hecho sobre la potencia.", "significance": 0.7, "flags": []},
		{"title": "D", "text": "Otra cosa completamente distinta.", "significance": 0.6, "flags": []},
	]
	fake = {"La GPU": [1.0, 0.0], "Paráfrasis": [0.99, 0.14], "Otra": [0.0, 1.0]}

	def embed_fn(texts):
		return [next(v for k, v in fake.items() if t.startswith(k)) for t in texts]

	out = annotate.dedup_post_rewrite(notes, threshold=0.90, embed_fn=embed_fn)
	assert [n["title"] for n in out] == ["A", "D"]


def test_rewrite_solo_notas_con_bandera_voice(monkeypatch):
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_VOICE_V2", True, raising=False)
	assert not annotate._needs_voice_rewrite("Joan corrigió el bug de tree_hash.")
	assert annotate._needs_voice_rewrite("Se corrigió el bug de tree_hash.")
	assert annotate._needs_voice_rewrite("Aleth creó la rama de release.")


# ── huérfanos ──


class _Client:
	def __init__(self, points):
		self.points = points
		self.deleted = []

	def collection_exists(self, name):
		return name == "work_memories"

	def scroll(self, collection_name, scroll_filter, limit, offset, with_payload, with_vectors):
		return [SimpleNamespace(id=p["id"], payload={"refine_ref": p["ref"]}) for p in self.points], None

	def delete(self, collection_name, points_selector):
		self.deleted += list(points_selector.points)


def test_reconcile_orphans_solo_borra_huerfanos_de_sesiones_cerradas(tmp_path):
	from red_pill.memento.ascension import reconcile_orphans

	for sess, meta, partial in (("s-cerrada", True, False), ("s-a-medias", True, True)):
		d = tmp_path / "2026-09" / "opencode" / sess / "annotate"
		d.mkdir(parents=True)
		(d / "001-viva.md").write_text("x", encoding="utf-8")
		if meta:
			(d / "_meta.json").write_text("{}", encoding="utf-8")
		if partial:
			(d / "_partial.json").write_text("{}", encoding="utf-8")
	pts = [
		{"id": "viva", "ref": "2026-09/opencode/s-cerrada/annotate/001-viva.md"},
		{"id": "huerfana", "ref": "2026-09/opencode/s-cerrada/annotate/002-vieja.md"},
		{"id": "a-medias", "ref": "2026-09/opencode/s-a-medias/annotate/002-vieja.md"},
		{"id": "legacy", "ref": "2026-09/opencode/s-cerrada/refine/001-x.md"},
	]
	client = _Client(pts)
	mm = SimpleNamespace(client=client)
	dry = reconcile_orphans(tmp_path, mm, dry_run=True)
	assert dry["huerfanos"] == 1 and client.deleted == []
	stats = reconcile_orphans(tmp_path, mm)
	assert client.deleted == ["huerfana"]
	assert stats["omitidos_sesion_a_medias"] == 1


def test_rrf_scores_y_mmr_con_relevancia_por_rango():
	"""Con relevancia fusionada, un candidato de palabra clave con vector malo puede ganar."""
	fused = hybrid.rrf_scores([["sem1", "sem2"], ["kw1", "sem2"]])
	assert fused[0][0] == "sem2"  # consenso
	q = [1.0, 0.0]
	items = [pid for pid, _ in fused]
	vecs = {"sem1": [1.0, 0.0], "sem2": [0.99, 0.1], "kw1": [0.0, 1.0]}  # kw1: coseno 0 con la consulta
	picked = hybrid.mmr_select(q, items, [vecs[i] for i in items], k=2, lam=0.85, relevance=[s for _, s in fused])
	assert "kw1" in picked  # con coseno como relevancia nunca entraría
	assert hybrid.mmr_select(q, items, [vecs[i] for i in items], k=2, lam=0.85) == ["sem1", "sem2"]


def test_voz_v2_detras_de_flag(monkeypatch):
	"""OFF: voz v1 y fingerprint intactos; ON: voz v2 con su propia huella."""
	import red_pill.config as cfg
	from red_pill.memento.agentic import runtime

	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_VOICE_V2", False, raising=False)
	v1 = runtime.annotate_prompt_version()
	assert annotate._needs_voice_rewrite("Joan corrigió el bug.")  # v1: no está en 1ª persona → se reescribe
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_VOICE_V2", True, raising=False)
	assert runtime.annotate_prompt_version() != v1
	assert not annotate._needs_voice_rewrite("Joan corrigió el bug.")


# ── voz v2.1 (piloto 2026-09-26) ──


def test_v21_plantillas_con_alcance_del_operador(monkeypatch):
	"""El alcance WORK/SOCIAL sale de la config (oficio del operador) y entra en la huella."""
	import red_pill.config as cfg
	from red_pill.memento.agentic import prompts, runtime

	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_VOICE_V2", True, raising=False)
	monkeypatch.setattr(cfg, "MEMENTO_WORK_SCOPE", "derecho laboral y contratos", raising=False)
	monkeypatch.setattr(cfg, "MEMENTO_SOCIAL_SCOPE", "vida personal", raising=False)
	jurista = runtime.annotate_prompt_version()
	work = prompts.ANNOTATE_WORK_USER_V2.format(identity="", voice="", fragment="x", work_scope="derecho laboral y contratos", social_scope="")
	assert "WORK here means: derecho laboral y contratos" in work
	assert '"Joan implementó X." → "Joan implementó X."' in work  # sin la muletilla v1
	assert "{work_scope}" not in prompts.DUAL_SCORE_USER_V2.format(memories="m", work_scope="w", social_scope="s")
	monkeypatch.setattr(cfg, "MEMENTO_WORK_SCOPE", "código y sistemas", raising=False)
	assert runtime.annotate_prompt_version() != jurista  # otro oficio, otra huella


def test_v21_reescribe_ingles_y_aleth_en_tercera(monkeypatch):
	import red_pill.config as cfg

	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_VOICE_V2", True, raising=False)
	assert annotate.looks_english("Aleth updated the CHANGELOG.md to document the Sentinel Auditor validation")
	assert not annotate.looks_english("Joan corrigió el bug de tree_hash en la rama de la release")
	assert annotate._needs_voice_rewrite("Aleth updated the CHANGELOG.")
	assert annotate._needs_voice_rewrite("Aleth verificó la jurisprudencia de la adenda.")
	assert not annotate._needs_voice_rewrite("Joan corrigió el bug de tree_hash.")


def test_job_submit_rechaza_rutas_volatiles():
	from red_pill.cli import _volatile_paths

	assert _volatile_paths({"step_command": "x --root /tmp/claude-1000/pilot"}) == ["/tmp/claude-1000/pilot"]
	assert _volatile_paths({"a": "/dev/shm/q", "b": "/var/tmp/ok", "c": "~/tmp/ok", "d": "/home/joan/tmp/ok"}) == ["/dev/shm/q"]


# ── vista del fragmento (piloto v2.2) ──

_FRAG = "\n".join(
	[
		"## 2026-07-09 07:00:32 — Usuario",
		"arregla tree.py",
		"## (sin fecha) — Asistente",
		"voy a mirar",
		"## (sin fecha) — Tool",
		"[Code Edit] tree.py",
		"## Resultado — cerrado",
		"## (sin fecha) — Asistente",
		"He corregido tree.py.",
		"## 2026-07-09 07:10:00 — Usuario",
		"gracias",
	]
)


def test_fragment_view_actores_y_pares():
	from red_pill.memento.agentic.fragments import fragment_view

	assert fragment_view(_FRAG, "raw") == _FRAG
	actors = fragment_view(_FRAG, "actors", "Joan", "Aleth")
	assert "— Aleth (herramienta)" in actors and "— Usuario" not in actors
	assert "## Resultado — cerrado" in actors  # título markdown: sigue siendo cuerpo
	pairs = fragment_view(_FRAG, "pairs", "Joan", "Aleth")
	assert "voy a mirar" not in pairs and "[Code Edit]" not in pairs  # sin intermedios ni herramientas
	assert "He corregido tree.py." in pairs and pairs.count("— Joan") == 2


def test_vista_no_raw_entra_en_la_huella(monkeypatch):
	import red_pill.config as cfg
	from red_pill.memento.agentic import runtime

	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_VOICE_V2", False, raising=False)
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_FRAGMENT_VIEW", "raw", raising=False)
	raw = runtime.annotate_prompt_version()
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_FRAGMENT_VIEW", "pairs", raising=False)
	assert runtime.annotate_prompt_version() != raw


def test_fragment_view_tool_results_de_claude_code_no_son_del_operador():
	from red_pill.memento.agentic.fragments import fragment_view

	frag = "\n".join(
		[
			"## 2026-08-14 12:39:00 — Usuario",
			"revisa el repo",
			"## 2026-08-14 12:39:05 — Asistente",
			"miro el estado",
			"## 2026-08-14 12:39:06 — Usuario",
			"[TOOL RESULT: On branch main, nothing to commit]",
			"## 2026-08-14 12:39:09 — Asistente",
			"El repo está limpio.",
		]
	)
	actors = fragment_view(frag, "actors", "Joan", "Aleth")
	assert actors.count("— Joan") == 1 and "— Aleth (herramienta)" in actors
	pairs = fragment_view(frag, "pairs", "Joan", "Aleth")
	assert "[TOOL RESULT" not in pairs and "miro el estado" not in pairs  # el intermedio ya no es "final"
	assert "El repo está limpio." in pairs
