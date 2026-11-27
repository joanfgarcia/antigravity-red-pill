"""AD-148: pase de títulos (batches, reanudable, renombrado, sin título no asciende)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import red_pill.config as cfg
from red_pill.memento.agentic import titles


def _note(dir_path: Path, name: str, text: str, title: str = "provisional", version: str = "") -> Path:
	path = dir_path / name
	path.parent.mkdir(parents=True, exist_ok=True)
	fm = {
		"session_id": "opencode:s1",
		"source": "opencode",
		"source_lines": "memento/index.md#l1-20",
		"split_ref": "memento/index.md#l1-20",
		"title": title,
		"title_version": version,
		"significance": 0.9,
		"emotion": "gray",
		"intensity": 0.5,
		"ascended": False,
		"dual_route": "work",
		"work_score": 0.9,
		"social_score": 0.05,
	}
	path.write_text(f"---\n{yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)}---\n\n{text}\n", encoding="utf-8")
	return path


@pytest.fixture(autouse=True)
def _pin(monkeypatch):
	monkeypatch.setattr(titles, "title_prompt_version", lambda: "t:test-v1")
	monkeypatch.setattr(titles.runtime, "served_engine", lambda: "bonsai-test")
	monkeypatch.setattr(cfg, "MEMENTO_TITLES_BATCH", 12)


def _dir(tmp_path: Path) -> Path:
	d = tmp_path / "2026-09" / "opencode" / "s1" / "annotate"
	d.mkdir(parents=True)
	(d / "_meta.json").write_text(json.dumps({"notas": 2}), encoding="utf-8")
	return d


def test_titula_renombra_y_sella(tmp_path):
	d = _dir(tmp_path)
	_note(d, "001-provisional-a.md", "El daemon perdía VRAM en el arranque.")
	_note(d, "001-provisional-b.md", "Joan decidió dejar el slug con acentos.")
	calls = []

	def transport(system, user, max_tokens):
		calls.append(len(user))
		return json.dumps([{"i": 0, "title": "Pérdida de VRAM al arrancar"}, {"i": 1, "title": "Decisión sobre el slug con acentos"}])

	res = titles.run_titles(tmp_path, "2026-09/opencode/s1", "opencode:s1", "opencode", transport)

	assert res == {"titled": 2, "skipped": 0, "pending": 0}
	assert len(calls) == 1  # 2 notas en un batch
	names = sorted(p.name for p in d.glob("*.md"))
	assert names == ["001-decisi-n-sobre-el-slug-con-acentos.md", "001-p-rdida-de-vram-al-arrancar.md"]
	fm = yaml.safe_load(names and (d / names[0]).read_text(encoding="utf-8").split("---")[1])
	assert fm["title_version"] == "t:test-v1"
	assert fm["title_engine"] == "bonsai-test"
	assert not (d / "_titles.json").exists()
	meta = json.loads((d / "_meta.json").read_text(encoding="utf-8"))
	assert meta["titles"]["notas"] == 2 and meta["titles"]["sin_titulo"] == 0


def test_reanudar_no_vuelve_a_llamar(tmp_path):
	d = _dir(tmp_path)
	_note(d, "001-a.md", "Primera nota.")
	_note(d, "001-b.md", "Segunda nota.")

	def transport(system, user, max_tokens):
		return json.dumps([{"i": 0, "title": "Título A"}, {"i": 1, "title": "Título B"}])

	titles.run_titles(tmp_path, "2026-09/opencode/s1", "opencode:s1", "opencode", transport)

	def no_llamar(system, user, max_tokens):
		raise AssertionError("no debe llamar al modelo si ya está titulado")

	res = titles.run_titles(tmp_path, "2026-09/opencode/s1", "opencode:s1", "opencode", no_llamar)
	assert res["titled"] == 0 and res["skipped"] == 2 and res["pending"] == 0


def test_titulo_invalido_queda_pendiente_sin_renombrar(tmp_path):
	d = _dir(tmp_path)
	before = _note(d, "001-a.md", "Nota sobre el bug del registry.")
	_note(d, "001-b.md", "Nota sobre el DAG del sueño.")

	def transport(system, user, max_tokens):
		# Primer índice inválido (prohibido), segundo válido; el reintento no arregla.
		return json.dumps([{"i": 0, "title": "Conversación sobre el registry"}, {"i": 1, "title": "DAG del sueño"}])

	res = titles.run_titles(tmp_path, "2026-09/opencode/s1", "opencode:s1", "opencode", transport)
	assert res["pending"] == 1
	assert before.exists()  # la inválida conserva su nombre provisional
	meta = json.loads((d / "_meta.json").read_text(encoding="utf-8"))
	assert meta["titles"]["sin_titulo"] == 1


def test_colision_de_slug_no_pisa(tmp_path):
	d = _dir(tmp_path)
	_note(d, "001-a.md", "Nota uno sobre el compactor.")
	_note(d, "001-b.md", "Nota dos sobre el compactor.")

	def transport(system, user, max_tokens):
		return json.dumps([{"i": 0, "title": "El compactor"}, {"i": 1, "title": "El compactor"}])

	titles.run_titles(tmp_path, "2026-09/opencode/s1", "opencode:s1", "opencode", transport)
	files = sorted(p.name for p in d.glob("*.md"))
	assert len(files) == 2
	assert any(f.endswith("-2.md") for f in files)


def test_anonimiza_texto_hash(tmp_path):
	"""El checkpoint usa el hash del cuerpo: si el texto cambia, se re-titula."""
	assert titles._text_hash("hola") == titles._text_hash(" hola ")
	assert titles._text_hash("hola") != titles._text_hash("hola.")


def test_titulo_hasta_120_se_acepta_sin_truncar():
	"""Decisión 2026-11-27: límite 120, sin truncar. 110 chars pasan íntegros."""
	t110 = "x" * 110
	parsed = titles._parse_titles(json.dumps([{"i": 0, "title": t110}]))
	assert parsed.get(0) == t110


def test_titulo_de_mas_de_120_es_fallo_duro():
	""">120 no se trunca ni se descarta en silencio: error explícito."""
	with pytest.raises(titles.TitleTooLongError):
		titles._parse_titles(json.dumps([{"i": 0, "title": "y" * 121}]))
