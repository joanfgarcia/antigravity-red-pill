"""NB-001 F2b (P4): reuso incremental por unidad en annotate.

Contrato (PLAN-NB-001 §3 F2 / D-NB-03/08/09/10):
- `annotate/_partial.json` sigue siendo el checkpoint INTRA-run (MEM-009); no cambia.
- Nuevo manifest persistente `annotate/_meta.json` por `unit_key` (rango) que
  sobrevive al éxito: `content_hash`, `annotate_prompt_version`, `engine`,
  `degraded` y la lista de ficheros de notas por unidad.
- Al re-anotar una sesión que creció se reusan las unidades cuyo hash+versión
  coinciden (sin llamar al modelo) y solo se extraen las nuevas; el resto del
  pipeline (rewrite/score/gate) queda intacto.
- Renombrado/`source_lines` refrescados como en P3; huérfanos al final; una
  unidad `degraded` nunca se reusa.
- Flag `MEMENTO_ANNOTATE_REUSE_ENABLED` (RULE 4, default OFF): OFF → comportamiento
  actual exacto.
"""

import json
import re

import pytest

import red_pill.config as cfg
from red_pill.memento.agentic import (
	ANNOTATE_SOCIAL_SYSTEM,
	ANNOTATE_WORK_SYSTEM,
	DEGRADED_MARKER,
	DUAL_SCORE_SYSTEM,
	annotate_session,
)
from red_pill.memento.agentic import runtime as agentic_runtime

DIR_REL = "2026-10/opencode/opencode-s1"
SID = "opencode:s1"

# Vocabulario léxicamente disjunto por unidad (el dedup P1-A compara tokens de
# ≥4 letras): cada split necesita su propio léxico para no colapsarse.
_WORDS = ["arranque", "bitácora", "cerrojo", "dintel", "esclusa", "fragua", "galería", "herraje", "incienso", "jardinera", "kermés", "linterna"]


class _Killed(RuntimeError):
	pass


class _Transport:
	"""Transporte falso que cuenta llamadas por fase; una idea por unidad (work)."""

	def __init__(self):
		self.extract = 0
		self.score = 0

	def __call__(self, system, user, max_tokens):
		if system in (ANNOTATE_WORK_SYSTEM, ANNOTATE_SOCIAL_SYSTEM):
			self.extract += 1
			if system == ANNOTATE_SOCIAL_SYSTEM:
				return "[]"
			m = re.search(r"UNIDAD-(\d+)", user)
			n = int(m.group(1)) if m else 1
			return json.dumps(
				[
					{
						"title": f"Idea {n}",
						"text": f"{_WORDS[n - 1]} {_WORDS[n - 1]}ado",
						"significance": 0.8,
						"emotion": "cyan",
						"intensity": 0.5,
						"theme": f"t{n}",
						"relics": [],
					}
				]
			)
		if system == DUAL_SCORE_SYSTEM:
			self.score += 1
			idxs = [int(m) for m in re.findall(r"^\[(\d+)\]", user, re.M)]
			return json.dumps([{"i": i, "work_score": 0.9, "social_score": 0.1} for i in idxs])
		return "[]"


@pytest.fixture(autouse=True)
def _pin_runtime(monkeypatch):
	"""engine/prompt_version deterministas: entran en la clave de reuso.

	También se fija el pipeline a la configuración de fábrica (voice_rewrite y
	dedup post-rewrite OFF) para que el reuso sea determinista e independiente del
	`.env` del puesto.
	"""
	monkeypatch.setattr(agentic_runtime, "engine_id", lambda: "granite-test")
	monkeypatch.setattr(agentic_runtime, "annotate_prompt_version", lambda: "pv-1")
	monkeypatch.setattr(agentic_runtime, "model_trust", lambda: "full")
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_VOICE_REWRITE", False)
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_POST_REWRITE_DEDUP", False)


@pytest.fixture
def reuse_on(monkeypatch):
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_REUSE_ENABLED", True)


def _build_session(tmp_path, splits):
	"""`splits`: list[(prefix, rango, body)]. Crea memento/NNN-mensajes-RANGO.md."""
	root = tmp_path
	memento_dir = root / DIR_REL / "memento"
	memento_dir.mkdir(parents=True, exist_ok=True)
	for prefix, rng, body in splits:
		fname = f"{prefix}-mensajes-{rng}.md"
		(memento_dir / fname).write_text(f"> [!ref] memento/{fname}#l1-10\n{body}\n", encoding="utf-8")
	return root, DIR_REL, SID


def _three(tmp_path):
	return _build_session(
		tmp_path,
		[
			("001", "0001-0100", "UNIDAD-1"),
			("002", "0201-0300", "UNIDAD-2"),
			("003", "0401-0500", "UNIDAD-3"),
		],
	)


def _meta(tmp_path):
	return json.loads((tmp_path / DIR_REL / "annotate" / "_meta.json").read_text(encoding="utf-8"))


# ── P4.1 sesión que crece → solo se extraen las unidades nuevas ──


def test_growing_session_reuses_unchanged_units(tmp_path, reuse_on):
	root, dir_rel, sid = _three(tmp_path)

	t1 = _Transport()
	annotate_session(root, dir_rel, sid, "opencode", t1)
	assert t1.extract == 6  # 3 unidades × (work + social)

	# crece por la cola: un mensaje nuevo en la ÚLTIMA unidad.
	last = sorted((root / dir_rel / "memento").glob("003-*.md"))[0]
	last.write_text(last.read_text(encoding="utf-8") + "mensaje nuevo\n", encoding="utf-8")

	t2 = _Transport()
	annotate_session(root, dir_rel, sid, "opencode", t2)
	assert t2.extract == 2, "solo la unidad nueva se extrae (1 × work + social)"
	meta = _meta(tmp_path)
	assert meta["splits"] == 3
	assert meta["notas"] == 3
	assert len(meta["units"]) == 3


# ── P4.2 kill a mitad → `_partial.json` sigue funcionando (flag ON incluido) ──


def test_kill_midway_resume_uses_partial_with_reuse(tmp_path, reuse_on):
	root, dir_rel, sid = _build_session(
		tmp_path, [(f"{i:03d}", f"{i:04d}-{i:04d}", f"UNIDAD-{i}") for i in range(1, 5)]
	)
	t = _Transport()

	def crashing(system, user, max_tokens):
		if system in (ANNOTATE_WORK_SYSTEM, ANNOTATE_SOCIAL_SYSTEM) and t.extract >= 4:
			raise _Killed("kill a mitad de extract")
		return t(system, user, max_tokens)

	with pytest.raises(_Killed):
		annotate_session(root, dir_rel, sid, "opencode", crashing)
	partial = json.loads((root / dir_rel / "annotate" / "_partial.json").read_text(encoding="utf-8"))
	assert sorted(partial["splits"]) == ["0001-0001", "0002-0002"]

	t2 = _Transport()
	annotate_session(root, dir_rel, sid, "opencode", t2)
	assert t2.extract == 4, "solo las 2 unidades que faltaban se extraen; las del parcial se reusan"
	meta = _meta(tmp_path)
	assert meta["splits"] == 4
	assert len(meta["units"]) == 4


# ── P4.3 cambio de `annotate_prompt_version` → re-anota todo (no mezcla estratos) ──


def test_prompt_version_change_reannotates_all(tmp_path, reuse_on):
	root, dir_rel, sid = _three(tmp_path)
	annotate_session(root, dir_rel, sid, "opencode", _Transport())

	monkeypatch = pytest.MonkeyPatch()
	monkeypatch.setattr(agentic_runtime, "annotate_prompt_version", lambda: "pv-2")
	try:
		t = _Transport()
		annotate_session(root, dir_rel, sid, "opencode", t)
		assert t.extract == 6, "cambiar la versión de prompt invalida todo el reuso"
	finally:
		monkeypatch.undo()


# ── P4.4 notas y `_meta.json` finales idénticos en estructura; métricas sin cambio ──


def test_reuse_preserves_notes_and_metrics(tmp_path, reuse_on):
	root, dir_rel, sid = _three(tmp_path)

	t1 = _Transport()
	annotate_session(root, dir_rel, sid, "opencode", t1)
	notes1 = {f.name: f.read_text(encoding="utf-8") for f in (root / dir_rel / "annotate").glob("*.md")}
	meta1 = _meta(tmp_path)

	# re-run sobre la MISMA sesión (nada cambió): puro reuso, cero llamadas.
	t2 = _Transport()
	annotate_session(root, dir_rel, sid, "opencode", t2)
	assert t2.extract == 0
	assert t2.score == 0

	notes2 = {f.name: f.read_text(encoding="utf-8") for f in (root / dir_rel / "annotate").glob("*.md")}
	meta2 = _meta(tmp_path)

	assert notes1 == notes2, "las notas reusadas son byte-idénticas a las originales"
	assert meta1["max_significance"] == meta2["max_significance"]
	assert meta1["metrics"] == meta2["metrics"]
	assert meta1["notas"] == meta2["notas"]
	assert meta1["routes"] == meta2["routes"]
	assert meta1["flags"] == meta2["flags"]
	assert meta1["units"] == meta2["units"]


def test_reuse_manifest_records_unit_fields(tmp_path, reuse_on):
	root, dir_rel, sid = _three(tmp_path)
	annotate_session(root, dir_rel, sid, "opencode", _Transport())
	units = _meta(tmp_path)["units"]
	assert set(units) == {"0001-0100", "0201-0300", "0401-0500"}
	for key, entry in units.items():
		assert set(entry) == {"content_hash", "annotate_prompt_version", "engine", "degraded", "files"}
		assert entry["annotate_prompt_version"] == "pv-1"
		assert entry["engine"] == "granite-test"
		assert entry["degraded"] is False
		assert entry["files"], "cada unidad tiene su lista de notas"


# ── unidad `degraded` → nunca se reusa (coherente con P3) ──


def test_degraded_unit_is_never_reused(tmp_path, reuse_on):
	root, dir_rel, sid = _three(tmp_path)

	def degrading(system, user, max_tokens):
		if system in (ANNOTATE_WORK_SYSTEM, ANNOTATE_SOCIAL_SYSTEM):
			if system == ANNOTATE_SOCIAL_SYSTEM:
				return "[]"
			n = int(re.search(r"UNIDAD-(\d+)", user).group(1))
			raw = json.dumps(
				[
					{
						"title": f"Idea {n}",
						"text": f"{_WORDS[n - 1]} {_WORDS[n - 1]}ado",
						"significance": 0.8,
						"emotion": "cyan",
						"intensity": 0.5,
						"theme": f"t{n}",
						"relics": [],
					}
				]
			)
			return raw + DEGRADED_MARKER if n == 2 else raw
		if system == DUAL_SCORE_SYSTEM:
			idxs = [int(m) for m in re.findall(r"^\[(\d+)\]", user, re.M)]
			return json.dumps([{"i": i, "work_score": 0.9, "social_score": 0.1} for i in idxs])
		return "[]"

	annotate_session(root, dir_rel, sid, "opencode", degrading)
	units = _meta(tmp_path)["units"]
	assert units["0201-0300"]["degraded"] is True

	# re-run limpio: la unidad degraded se re-extrae; las otras dos se reusan.
	t2 = _Transport()
	annotate_session(root, dir_rel, sid, "opencode", t2)
	assert t2.extract == 2, "solo la unidad degraded se re-extrae, nunca se reusa"
	assert _meta(tmp_path)["units"]["0201-0300"]["degraded"] is False


# ── renombrado: un split insertado en medio no rompe el enlace nota→unidad ──


def test_insert_split_renames_and_keeps_unit_key(tmp_path, reuse_on):
	root, dir_rel, sid = _three(tmp_path)
	annotate_session(root, dir_rel, sid, "opencode", _Transport())

	# Inserta un split entre A(0001-0100) y B(0201-0300): B y C pasan de nnn 002/003
	# a 003/004; sus rangos (unit_key) NO cambian.
	memento_dir = root / dir_rel / "memento"
	(memento_dir / "002-mensajes-0201-0300.md").rename(memento_dir / "003-mensajes-0201-0300.md")
	(memento_dir / "003-mensajes-0401-0500.md").rename(memento_dir / "004-mensajes-0401-0500.md")
	(memento_dir / "002-mensajes-0101-0200.md").write_text(
		"> [!ref] memento/002-mensajes-0101-0200.md#l1-10\nUNIDAD-4\n", encoding="utf-8"
	)

	t = _Transport()
	annotate_session(root, dir_rel, sid, "opencode", t)
	# A (0001-0100) y el nuevo X (0101-0200) se extraen; B/C se reusan (0 extract
	# para ellas). X es un split nuevo: 2 llamadas (work+social).
	assert t.extract == 2

	annotate_dir = root / dir_rel / "annotate"
	files = {f.name for f in annotate_dir.glob("*.md")}
	# B y C conservan su rango (unit_key) y adoptan el nnn nuevo (003/004).
	assert any(n.startswith("003-idea-2") for n in files), "B renombrado a nnn 003"
	assert any(n.startswith("004-idea-3") for n in files), "C renombrado a nnn 004"
	# sin huérfanos: 4 notas, ninguna con el nnn viejo de B/C.
	assert len(files) == 4
	assert not any(n.startswith(("002-idea-2", "003-idea-3")) for n in files)


# ── P4.5 flag OFF → comportamiento actual exacto (sin manifest, sin units) ──


def test_flag_off_is_full_annotate_without_manifest(tmp_path, monkeypatch):
	# La palanca se fija: es el test del comportamiento APAGADO, no del env.
	# (Mismo falso rojo que F2a/F3 si el día que se encienda F2b alguien corre
	# la suite con el `.env` real.)
	monkeypatch.setattr(cfg, "MEMENTO_ANNOTATE_REUSE_ENABLED", False, raising=False)
	root, dir_rel, sid = _three(tmp_path)

	t1 = _Transport()
	annotate_session(root, dir_rel, sid, "opencode", t1)
	assert t1.extract == 6

	t2 = _Transport()
	annotate_session(root, dir_rel, sid, "opencode", t2)
	assert t2.extract == 6, "sin reuso: se extrae todo de nuevo"

	meta = _meta(tmp_path)
	assert "units" not in meta, "sin flag no hay manifest de reuso"
	assert not (root / dir_rel / "annotate" / "_partial.json").exists()
