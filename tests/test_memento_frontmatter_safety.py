"""AD-151 / AD-152: frontmatter que no puede corromperse y dedup coherente.

Regresión del 2026-11-28 (MEM-009 P0): 34 de 983 notas de la sesión `f839399b`
acabaron con DOBLE frontmatter porque `_frontmatter_block` escribía un título que
empieza por backtick sin comillas, `_split_frontmatter` se tragaba el error de
YAML y `_write_note` envolvía el fichero entero en una cabecera nueva, perdiendo
`session_id`, `scope`, `work_score` y `ascended`.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

import red_pill.config as cfg
from red_pill.memento.agentic import titles
from red_pill.memento.agentic.fragments import _frontmatter_block

BASE_FM = {
	"session_id": "opencode:s1",
	"source": "opencode",
	"source_lines": "memento/index.md#l1-20",
	"split_ref": "memento/index.md#l1-20",
	"title": "provisional",
	"title_version": "",
	"significance": 0.75,
	"emotion": "gray",
	"intensity": 0.7,
	"texture": {"theme": "t", "relics": []},
	"work_score": 0.75,
	"social_score": 0.05,
	"dual_route": "work",
	"scope": "work",
	"quality_flags": [],
	"ascended": False,
}

CORRUPT_TITLES = [
	"`_llm_available()` deriva el endpoint como `<base>/models`",
	"'Cenicienta' fue un apodo puntual, no identidad",
	"Fix: el gate no parsea # 34",
	"- dash inicial y : dos puntos",
	'comillas "dobles" y \\ barra',
]


# ── serialización ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("title", CORRUPT_TITLES)
def test_frontmatter_block_hace_yaml_valido(title):
	"""Cualquier título hostil sale entrecomillado y vuelve idéntico."""
	block = _frontmatter_block([("title", title), ("work_score", 0.75), ("texture", {"theme": "t", "relics": []})])
	fm = yaml.safe_load(block.strip("-\n"))
	assert fm["title"] == title
	assert fm["texture"] == {"theme": "t", "relics": []}


def test_frontmatter_block_conserva_tipos():
	fm = yaml.safe_load(_frontmatter_block(list(BASE_FM.items())).strip("-\n"))
	assert fm["ascended"] is False
	assert fm["significance"] == 0.75
	assert fm["quality_flags"] == []
	assert fm["session_id"] == BASE_FM["session_id"]


# ── parseo con fallback ──────────────────────────────────────────────────────


def _raw_title_note(tmp_path: Path, title: str, name: str = "001-nota.md") -> Path:
	"""Nota escrita como la vieja `_frontmatter_block`: título crudo, sin comillas."""
	fields = dict(BASE_FM, title=title)
	head = "\n".join(["---"] + [f"{k}: {v if not isinstance(v, (dict, list)) else json.dumps(v)}" for k, v in fields.items()] + ["---"])
	path = tmp_path / name
	path.write_text(f"{head}\n\nCuerpo de la nota, intacto.\n", encoding="utf-8")
	return path


@pytest.mark.parametrize("title", CORRUPT_TITLES)
def test_split_frontmatter_recupera_titulo_crudo(tmp_path, title):
	path = _raw_title_note(tmp_path, title)
	fm, body = titles._split_frontmatter(path.read_text(encoding="utf-8"), path)
	assert fm["title"] == title
	assert fm["session_id"] == "opencode:s1"
	assert fm["scope"] == "work"
	assert fm["work_score"] == 0.75
	assert fm["ascended"] is False
	assert body.strip() == "Cuerpo de la nota, intacto."


def test_split_frontmatter_falla_visible_si_no_hay_fallback(tmp_path):
	path = tmp_path / "001-roto.md"
	path.write_text("---\n- lista\n: roto\n---\ncuerpo\n", encoding="utf-8")
	with pytest.raises(titles.FrontmatterError) as exc:
		titles._split_frontmatter(path.read_text(encoding="utf-8"), path)
	assert path.name in str(exc.value)


# ── guardas de escritura ─────────────────────────────────────────────────────


def test_write_note_rechaza_cuerpo_con_frontmatter(tmp_path):
	"""Un cuerpo que empieza por `---` es un bloque sin parsear: nunca se envuelve."""
	path = tmp_path / "001-nota.md"
	path.write_text("---\ntitle: x\n---\n\n---\nsession_id: s1\n---\n\ncuerpo\n", encoding="utf-8")
	with pytest.raises(ValueError):
		titles._write_note(path, {"title": "x"}, "---\nsession_id: s1\n---\n\ncuerpo", "Nuevo", "v", "e")
	# no se ha reescrito nada
	assert "session_id: s1" in path.read_text(encoding="utf-8")
	assert not (tmp_path / "001-nuevo.md").exists()


# ── pase de títulos con títulos hostiles ─────────────────────────────────────


@pytest.fixture
def _pin(monkeypatch):
	monkeypatch.setattr(titles, "title_prompt_version", lambda: "t:v1")
	monkeypatch.setattr(titles.runtime, "served_engine", lambda: "engine-test")
	monkeypatch.setattr(cfg, "MEMENTO_TITLES_BATCH", 12)


def _annotate_dir(tmp_path: Path) -> Path:
	d = tmp_path / "2026-09" / "opencode" / "s1" / "annotate"
	d.mkdir(parents=True)
	(d / "_meta.json").write_text(json.dumps({"notas": 0}), encoding="utf-8")
	return d


def test_run_titles_sella_titulo_con_backtick_sin_perder_campos(tmp_path, _pin):
	d = _annotate_dir(tmp_path)
	path = _raw_title_note(d, "provisional")
	before = path.read_text(encoding="utf-8")

	def transport(system, user, max_tokens):
		return json.dumps([{"i": 0, "title": "`_llm_available()` deriva el endpoint"}])

	res = titles.run_titles(tmp_path, "2026-09/opencode/s1", "opencode:s1", "opencode", transport)
	assert res == {"titled": 1, "skipped": 0, "pending": 0, "corrupt": 0}
	repaired = next(d.glob("001-*.md"))
	text = repaired.read_text(encoding="utf-8")
	fm, body = titles._split_frontmatter(text, repaired)
	assert fm["title"] == "`_llm_available()` deriva el endpoint"
	assert fm["title_version"] == "t:v1"
	for key in ("session_id", "scope", "work_score", "ascended"):
		assert key in fm, key
	assert body.strip() == "Cuerpo de la nota, intacto."
	# el cuerpo es el mismo que antes (solo cambia la cabecera y el nombre)
	assert before.split("---")[-1].strip() == body.strip()


def test_run_titles_segunda_pasada_es_idempotente(tmp_path, _pin):
	d = _annotate_dir(tmp_path)
	for i in range(3):
		_raw_title_note(d, "provisional", f"00{i + 1}-nota.md")

	def transport(system, user, max_tokens):
		return json.dumps([{"i": i, "title": f"Nota número {i} sobre el gate"} for i in range(3)])

	titles.run_titles(tmp_path, "2026-09/opencode/s1", "opencode:s1", "opencode", transport)

	def no_llamar(system, user, max_tokens):
		raise AssertionError("no debe llamar al modelo en la segunda pasada")

	res = titles.run_titles(tmp_path, "2026-09/opencode/s1", "opencode:s1", "opencode", no_llamar)
	assert res == {"titled": 0, "skipped": 3, "pending": 0, "corrupt": 0}


def test_run_titles_no_toca_una_nota_con_doble_frontmatter(tmp_path, _pin):
	"""La nota corrupta se deja como está y se cuenta: no se envuelve otra vez."""
	d = _annotate_dir(tmp_path)
	corrupt = d / "001-corrupta.md"
	original = "---\ntitle: Sellado\ntitle_version: p1:v0\ntitle_engine: old\n---\n\n---\nsession_id: opencode:s1\nscope: work\n---\n\ncuerpo\n"
	corrupt.write_text(original, encoding="utf-8")
	_raw_title_note(d, "provisional", "002-sana.md")

	def transport(system, user, max_tokens):
		return json.dumps([{"i": 0, "title": "Título de la nota sana"}])

	res = titles.run_titles(tmp_path, "2026-09/opencode/s1", "opencode:s1", "opencode", transport)
	assert res["corrupt"] == 1
	assert corrupt.read_text(encoding="utf-8") == original


# ── script de reparación ─────────────────────────────────────────────────────


def _load_script():
	spec = importlib.util.spec_from_file_location(
		"repair_double_frontmatter", Path("scripts/memento_repair_double_frontmatter.py")
	)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


def _double_note(d: Path, name: str, title: str, body: str) -> Path:
	inner = "\n".join(
		["---"] + [f"{k}: {v}" for k, v in dict(BASE_FM, title=title).items() if not isinstance(v, (dict, list))] + ["---"]
	)
	path = d / name
	path.write_text(
		f'---\ntitle: Título sellado\ntitle_version: p1:abc\ntitle_engine: engine\n---\n\n{inner}\n\n{body}\n',
		encoding="utf-8",
	)
	return path


def test_reparacion_dry_run_no_escribe_y_repara_solo_las_dobles(tmp_path):
	mod = _load_script()
	d = tmp_path / "annotate"
	d.mkdir()
	bad = _double_note(d, "001-doble.md", "`backtick` al inicio", "Cuerpo uno.")
	clean = d / "002-limpia.md"
	clean_text = f"---\n{mod.dump_frontmatter(dict(BASE_FM, title='Limpia')).strip('-\n')}\n---\n\nCuerpo dos.\n"
	clean.write_text(clean_text, encoding="utf-8")
	backup = tmp_path / "backup"

	assert mod.main(["--annotate-dir", str(d), "--dry-run", "--backup-dir", str(backup)]) == 0
	assert mod.is_double(bad.read_text(encoding="utf-8"))  # nada escrito
	assert not backup.exists()

	assert mod.main(["--annotate-dir", str(d), "--backup-dir", str(backup)]) == 0
	assert not mod.is_double(bad.read_text(encoding="utf-8"))
	assert (backup / "001-doble.md").exists()
	# la nota limpia no se toca
	assert clean.read_text(encoding="utf-8") == clean_text
	# cuerpo idéntico y campos del interior recuperados, título sellado
	fm, body = titles._split_frontmatter(bad.read_text(encoding="utf-8"), bad)
	assert fm["title"] == "Título sellado"
	assert fm["title_version"] == "p1:abc"
	assert fm["title_engine"] == "engine"
	assert fm["session_id"] == "opencode:s1"
	assert fm["scope"] == "work"
	assert fm["work_score"] == 0.75
	assert fm["ascended"] is False
	assert body.strip() == "Cuerpo uno."
	# idempotente
	assert mod.main(["--annotate-dir", str(d), "--backup-dir", str(backup)]) == 0
	assert mod.find_doubles(d) == []
	assert "Cuerpo uno." in bad.read_text(encoding="utf-8")
