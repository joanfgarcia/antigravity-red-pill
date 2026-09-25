"""MEM-009 F1: annotate reanudable — parcial por rango, scrub, `--from` con degradado, audit trail.

Y D5: tri-estado `flash_attn` resuelto en `model_runtime`.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest

from red_pill.memento.agentic import ANNOTATE_SOCIAL_SYSTEM, ANNOTATE_WORK_SYSTEM, DUAL_SCORE_SYSTEM, annotate_session
from red_pill.memento.agentic.annotate import _PARTIAL
from red_pill.memento.agentic.prompts import VOICE_REWRITE_SYSTEM

_SECRET = "sk-" + "A" * 32
# Temas léxicamente disjuntos: el dedup P1-A compara tokens de ≥4 letras (los
# números no cuentan), así que cada split necesita su propio vocabulario.
_WORDS = ["arranque", "bitácora", "cerrojo", "dintel", "esclusa", "fragua", "galería", "herraje", "incienso", "jardinera", "kermés", "linterna"]


class _Killed(RuntimeError):
	pass


class _Transport:
	"""Transporte falso que cuenta llamadas por fase y puede 'morir' tras N extracts."""

	def __init__(self, die_after_extracts=None, secret=False):
		self.calls = {"extract": 0, "rewrite": 0, "score": 0}
		self.die_after_extracts = die_after_extracts
		self.secret = secret

	def __call__(self, system, user, max_tokens):
		if system in (ANNOTATE_WORK_SYSTEM, ANNOTATE_SOCIAL_SYSTEM):
			if self.die_after_extracts is not None and self.calls["extract"] >= self.die_after_extracts:
				raise _Killed("kill a mitad de extract")
			self.calls["extract"] += 1
			if system == ANNOTATE_SOCIAL_SYSTEM:
				return "[]"
			m = re.search(r"del split (\d+)", user)
			n = m.group(1) if m else self.calls["extract"]  # la idea depende del CONTENIDO, no del orden de llamada
			extra = f" token {_SECRET}" if self.secret else ""
			return json.dumps(
				[
					{
						"title": f"Idea {n}",
						"text": f"{_WORDS[int(n) - 1]} {_WORDS[int(n) - 1]}ado{extra}",
						"significance": 0.8,
						"emotion": "cyan",
						"intensity": 0.5,
						"theme": f"t{n}",
						"relics": [],
					}
				]
			)
		if system == VOICE_REWRITE_SYSTEM:
			self.calls["rewrite"] += 1
			return "[]"
		if system == DUAL_SCORE_SYSTEM:
			self.calls["score"] += 1
			return json.dumps([{"i": i, "work_score": 0.9, "social_score": 0.1} for i in range(20)])
		return "[]"


def _tree(root: Path, n_splits: int) -> str:
	dir_rel = "2026-09/opencode/s1"
	splits = root / dir_rel / "memento"
	splits.mkdir(parents=True)
	for i in range(n_splits):
		lo, hi = i * 10 + 1, i * 10 + 10
		(splits / f"{i + 1:03d}-mensajes-{lo:04d}-{hi:04d}.md").write_text(
			f"> [!ref] memento/index.md#l{lo}-{hi}\nContenido único del split {i + 1}.\n", encoding="utf-8"
		)
	return dir_rel


def _run(root, dir_rel, transport, **kw):
	return annotate_session(root, dir_rel, "s1", "opencode", transport, voice_rewrite=False, **kw)


def test_kill_a_mitad_de_extract_reanuda_solo_los_restantes(tmp_path):
	"""(a) Kill tras 4 splits (8 llamadas) en una sesión de 10: el reintento extrae solo 6."""
	dir_rel = _tree(tmp_path, 10)
	with pytest.raises(_Killed):
		_run(tmp_path, dir_rel, _Transport(die_after_extracts=8))
	partial = json.loads((tmp_path / dir_rel / "annotate" / _PARTIAL).read_text(encoding="utf-8"))
	assert sorted(partial["splits"]) == ["0001-0010", "0011-0020", "0021-0030", "0031-0040"]
	assert partial["phases"]["extract"] == "pending"
	assert not (tmp_path / dir_rel / "annotate" / "_meta.json").exists()

	retry = _Transport()
	_run(tmp_path, dir_rel, retry)
	assert retry.calls["extract"] == 12  # 6 splits restantes × 2
	assert retry.calls["score"] >= 1
	annotate_dir = tmp_path / dir_rel / "annotate"
	assert not (annotate_dir / _PARTIAL).exists()
	meta = json.loads((annotate_dir / "_meta.json").read_text(encoding="utf-8"))
	assert meta["splits"] == 10


def test_hash_distinto_reextrae_solo_ese_rango(tmp_path):
	"""Revalidación anti-TOCTOU: un split que cambió en disco se reprocesa aunque figure extraído."""
	dir_rel = _tree(tmp_path, 3)
	with pytest.raises(_Killed):
		_run(tmp_path, dir_rel, _Transport(die_after_extracts=4))  # splits 1-2 en el parcial
	split = next((tmp_path / dir_rel / "memento").glob("002-*.md"))
	split.write_text(split.read_text(encoding="utf-8") + "Añadido.\n", encoding="utf-8")
	retry = _Transport()
	_run(tmp_path, dir_rel, retry)
	assert retry.calls["extract"] == 4  # 002 (cambió) + 003 (pendiente); 001 se reutiliza


def test_parcial_pasa_scrub(tmp_path):
	"""(c) La salida cruda del LLM se scrubbea ANTES de tocar el parcial."""
	dir_rel = _tree(tmp_path, 3)
	with pytest.raises(_Killed):
		_run(tmp_path, dir_rel, _Transport(die_after_extracts=4, secret=True))
	raw = (tmp_path / dir_rel / "annotate" / _PARTIAL).read_text(encoding="utf-8")
	assert _SECRET not in raw
	assert "[SECRET_REDACTED]" in raw


def test_from_score_sin_prerrequisitos_degrada_con_aviso(tmp_path, caplog):
	"""(b) `--from=score` sin parcial ni notas → degrada a extract, avisa en log, no falla."""
	dir_rel = _tree(tmp_path, 2)
	t = _Transport()
	with caplog.at_level(logging.WARNING, logger="red_pill.memento.agentic.annotate"):
		_run(tmp_path, dir_rel, t, from_phase="score")
	assert t.calls["extract"] == 4
	assert any("degrado a extract" in r.getMessage() for r in caplog.records)
	meta = json.loads((tmp_path / dir_rel / "annotate" / "_meta.json").read_text(encoding="utf-8"))
	assert meta["from_phase"] == "extract"
	assert meta["from_requested"] == "score"


def test_from_score_con_notas_repuntua_sin_reextraer(tmp_path):
	"""`--from=score` tras completar: el prerrequisito sale de las notas; cero extracts."""
	dir_rel = _tree(tmp_path, 3)
	_run(tmp_path, dir_rel, _Transport())
	t = _Transport()
	_run(tmp_path, dir_rel, t, from_phase="score", reason="umbrales nuevos")
	assert t.calls["extract"] == 0
	assert t.calls["score"] >= 1
	meta = json.loads((tmp_path / dir_rel / "annotate" / "_meta.json").read_text(encoding="utf-8"))
	assert meta["notas"] == 3
	assert meta["from_phase"] == "score"


def test_meta_trae_audit_trail(tmp_path):
	"""(d) Umbrales efectivos + bandera `--from` + motivo en `_meta.json`."""
	dir_rel = _tree(tmp_path, 1)
	_run(tmp_path, dir_rel, _Transport(), reason="piloto MEM-009")
	meta = json.loads((tmp_path / dir_rel / "annotate" / "_meta.json").read_text(encoding="utf-8"))
	assert set(meta["thresholds"]) == {"work", "social", "dead_zone"}
	assert meta["reason"] == "piloto MEM-009"
	assert meta["from_phase"] is None
	assert "/" not in str(meta["identity_bio_source"] or "")


def test_no_borra_al_empezar_y_limpia_huerfanos_al_final(tmp_path):
	"""Las notas viejas sobreviven a un kill; al completar, las huérfanas se van."""
	dir_rel = _tree(tmp_path, 2)
	annotate_dir = tmp_path / dir_rel / "annotate"
	annotate_dir.mkdir(parents=True)
	(annotate_dir / "009-huerfana.md").write_text("---\n---\nvieja", encoding="utf-8")
	with pytest.raises(_Killed):
		_run(tmp_path, dir_rel, _Transport(die_after_extracts=2))
	assert (annotate_dir / "009-huerfana.md").exists()
	_run(tmp_path, dir_rel, _Transport())
	assert not (annotate_dir / "009-huerfana.md").exists()
	assert len(list(annotate_dir.glob("*.md"))) == 2


def test_contrato_distinto_resetea_el_parcial(tmp_path, monkeypatch):
	"""Parcial de otro motor/prompt → reset automático (se re-extrae todo)."""
	from red_pill.memento.agentic import runtime

	dir_rel = _tree(tmp_path, 3)
	with pytest.raises(_Killed):
		_run(tmp_path, dir_rel, _Transport(die_after_extracts=4))
	monkeypatch.setattr(runtime, "engine_id", lambda: "otro_motor")
	retry = _Transport()
	_run(tmp_path, dir_rel, retry)
	assert retry.calls["extract"] == 6


def test_work_units_clave_del_mismo_fichero(tmp_path):
	"""`work_units` es la fuente única: la clave sale del MISMO fichero que el contenido."""
	from red_pill.memento.agentic import work_units

	session = tmp_path / "s"
	(session / "memento").mkdir(parents=True)
	for name, body in (
		("001-mensajes-0001-0030.md", "uno"),
		("002-mensajes-0031-0060.md", "dos"),
		("003-sin-rango.md", "tres"),
		("004-mensajes-0031-0060.md", "cuatro"),  # rango repetido (resto de re-render)
	):
		(session / "memento" / name).write_text(f"> [!ref] memento/index.md#l1-2\n{body}\n", encoding="utf-8")
	units = work_units(session)
	assert [(u.nnn, u.key, u.content) for u in units] == [
		("001", "0001-0030", "uno"),
		("002", "0031-0060", "dos"),
		("003", "003-sin-rango", "tres"),
		("004", "004-mensajes-0031-0060", "cuatro"),
	]
	assert len({u.key for u in units}) == len(units)


def test_work_units_sin_splits_usa_index(tmp_path):
	from red_pill.memento.agentic import work_units

	session = tmp_path / "s"
	(session / "memento").mkdir(parents=True)
	(session / "memento" / "index.md").write_text("---\nid: x\n---\ncuerpo\n", encoding="utf-8")
	(unit,) = work_units(session)
	assert unit.key == "index"
	assert unit.nnn == "001"


def test_renumeracion_de_nnn_no_invalida_el_parcial(tmp_path):
	"""Un split nuevo delante desplaza los NNN; los rangos ya extraídos se reutilizan
	y las notas salen con el NNN nuevo."""
	dir_rel = _tree(tmp_path, 3)
	with pytest.raises(_Killed):
		_run(tmp_path, dir_rel, _Transport(die_after_extracts=4))  # rangos 0001-0010 y 0011-0020
	splits = tmp_path / dir_rel / "memento"
	for old in sorted(splits.glob("*.md"), reverse=True):
		nnn, rest = old.name.split("-", 1)
		old.rename(splits / f"{int(nnn) + 1:03d}-{rest}")
	(splits / "001-mensajes-0000-0000.md").write_text("> [!ref] memento/index.md#l0-0\nContenido único del split 4.\n", encoding="utf-8")
	retry = _Transport()
	_run(tmp_path, dir_rel, retry)
	assert retry.calls["extract"] == 4  # nuevo 0000-0000 + pendiente 0021-0030
	notes = sorted(p.name for p in (tmp_path / dir_rel / "annotate").glob("*.md"))
	assert notes[0].startswith("001-") and notes[1].startswith("002-")  # el reutilizado 0001-0010 ahora es 002


# ── D5: flash_attn tri-estado ──


def test_flash_attn_tri_estado():
	import red_pill.core.model_runtime as mr

	assert mr._normalize_flash_attn(True) == "true"
	assert mr._normalize_flash_attn(False) == "false"
	assert mr._normalize_flash_attn(None) == "auto"
	assert mr._normalize_flash_attn("raro") == "auto"
	r = mr.ResolvedModel(profile_name="x", model_path="/m.gguf", flash_attn="true")
	assert mr.effective_flash_attn(r, "gpu") is True
	assert mr.effective_flash_attn(r, "cpu") is False  # el worker CPU nunca activa FA
	r.flash_attn = "auto"
	assert mr.effective_flash_attn(r, "gpu") is False  # sin fa_capable → conducta previa
	r.extra["fa_capable"] = True
	assert mr.effective_flash_attn(r, "gpu") is True
	r.flash_attn = "false"
	assert mr.effective_flash_attn(r, "gpu") is False
