"""NB-001 F2a (P3): reuso incremental por unidad en distill.

Contrato (PLAN-NB-001 §3 F2 / D-NB-03/08/09/11):
- La unidad es el RANGO de mensajes (`memento/NNN-mensajes-XXXX-YYYY.md`), no la sesión.
- Manifest persistente `distill/_meta.json` por `unit_key` (rango): `content_hash`
  del cuerpo, `prompt_version`, `engine`, `fragment_max_chars`, `fragment_overlap`,
  `degraded`, `files[]`.
- Reuso solo si coinciden TODOS los campos y `degraded` es falso; refresca
  `source_lines`/`nnn`, renombra si cambió `nnn`, sin perder fragmentos.
- Huérfanos se retiran al final, tras escribir el manifest.
- Flag `MEMENTO_DISTILL_REUSE_ENABLED` (RULE 4, default OFF): OFF → borrar y rehacer.
"""

import json
import re

import pytest

import red_pill.config as cfg
from red_pill.memento.agentic import DEGRADED_MARKER, distill_session
from red_pill.memento.agentic import runtime as agentic_runtime

DIR_REL = "2026-10/opencode/opencode-s1"
SID = "opencode:s1"


@pytest.fixture(autouse=True)
def _pin_runtime(monkeypatch):
	"""engine/prompt_version deterministas: entran en la clave de reuso."""
	monkeypatch.setattr(agentic_runtime, "engine_id", lambda: "granite-test")
	monkeypatch.setattr(agentic_runtime, "distill_prompt_version", lambda: "pv-1")
	monkeypatch.setattr(agentic_runtime, "model_trust", lambda: "full")


@pytest.fixture
def reuse_on(monkeypatch):
	monkeypatch.setattr(cfg, "MEMENTO_DISTILL_REUSE_ENABLED", True)


def _build_session(tmp_path, splits):
	"""`splits`: list[(prefix, rango, body)]. Crea memento/NNN-mensajes-RANGO.md."""
	root = tmp_path / "memento"
	memento_dir = root / DIR_REL / "memento"
	memento_dir.mkdir(parents=True, exist_ok=True)
	for prefix, rng, body in splits:
		fname = f"{prefix}-mensajes-{rng}.md"
		(memento_dir / fname).write_text(f"> [!ref] memento/{fname}#l1-10\n{body}\n", encoding="utf-8")
	return root, DIR_REL, SID


def _tag_from(user: str) -> str:
	m = re.search(r"UNIDAD-(\d+)", user)
	return m.group(1) if m else "?"


def _fake_transport(calls=None):
	def transport(system, user, max_tokens):
		if calls is not None:
			calls.append(user)
		tag = _tag_from(user)
		return json.dumps({"title": f"titulo-{tag}", "summary": f"resumen-{tag}", "keywords": ["t"]})

	return transport


def _meta(tmp_path):
	return json.loads((tmp_path / "memento" / DIR_REL / "distill" / "_meta.json").read_text(encoding="utf-8"))


def _three(tmp_path):
	return _build_session(
		tmp_path,
		[
			("001", "0001-0100", "UNIDAD-1"),
			("002", "0201-0300", "UNIDAD-2"),
			("003", "0401-0500", "UNIDAD-3"),
		],
	)


# ── P3.1 kill a mitad → relanzar reusa N y no re-procesa ──


def test_kill_midway_relaunch_reuses_done_units(tmp_path, reuse_on):
	root, dir_rel, sid = _build_session(
		tmp_path, [(f"{i:03d}", f"{i:04d}-{i:04d}", f"UNIDAD-{i}") for i in range(1, 6)]
	)

	calls1 = []

	def crashing(system, user, max_tokens):
		if len(calls1) >= 2:  # reventa al tercer unit (tras 2 destilados)
			raise RuntimeError("kill")
		calls1.append(user)
		return json.dumps({"title": f"t-{len(calls1)}", "summary": f"r-{len(calls1)}", "keywords": ["t"]})

	with pytest.raises(RuntimeError):
		distill_session(root, dir_rel, sid, "opencode", crashing)

	calls2 = []
	sections = distill_session(root, dir_rel, sid, "opencode", _fake_transport(calls2))
	assert len(calls2) == 3, "solo las 3 unidades que quedaban se re-destilan"
	assert len(sections) == 5
	assert len(_meta(tmp_path)["units"]) == 5


# ── P3.2 sesión que crece por la cola → 64/65 reusadas ──


def test_growing_session_reuses_64_of_65(tmp_path, reuse_on):
	splits = [(f"{i:03d}", f"{i:04d}-{i:04d}", f"UNIDAD-{i}") for i in range(1, 66)]
	root, dir_rel, sid = _build_session(tmp_path, splits)

	calls1 = []
	distill_session(root, dir_rel, sid, "opencode", _fake_transport(calls1))
	assert len(calls1) == 65

	# crece por la cola: un mensaje nuevo en la ÚLTIMA unidad.
	last = sorted((root / dir_rel / "memento").glob("065-*.md"))[0]
	last.write_text(last.read_text(encoding="utf-8") + "mensaje nuevo\n", encoding="utf-8")

	calls2 = []
	sections = distill_session(root, dir_rel, sid, "opencode", _fake_transport(calls2))
	assert len(calls2) == 1, "solo la cola se re-destila"
	assert len(sections) == 65


# ── P3.3 mensaje editado a mitad → solo las unidades afectadas ──


def test_edited_unit_redistills_only_that_unit(tmp_path, reuse_on):
	root, dir_rel, sid = _three(tmp_path)
	distill_session(root, dir_rel, sid, "opencode", _fake_transport())

	# edita la unidad del medio (002).
	mid = sorted((root / dir_rel / "memento").glob("002-*.md"))[0]
	mid.write_text(mid.read_text(encoding="utf-8") + "edición\n", encoding="utf-8")

	calls = []
	sections = distill_session(root, dir_rel, sid, "opencode", _fake_transport(calls))
	assert len(calls) == 1
	assert len(sections) == 3


# ── P3.4 cambiar prompt_version o fragment_max_chars → re-destila todo ──


def test_prompt_version_change_redistills_all(tmp_path, reuse_on):
	root, dir_rel, sid = _three(tmp_path)
	distill_session(root, dir_rel, sid, "opencode", _fake_transport())

	from red_pill.memento.agentic import runtime as rt

	# la clave cambia al cambiar la versión de prompt.
	monkeypatch = pytest.MonkeyPatch()
	monkeypatch.setattr(rt, "distill_prompt_version", lambda: "pv-2")
	try:
		calls = []
		distill_session(root, dir_rel, sid, "opencode", _fake_transport(calls))
		assert len(calls) == 3
	finally:
		monkeypatch.undo()


def test_fragment_max_chars_change_redistills_all(tmp_path, reuse_on):
	root, dir_rel, sid = _three(tmp_path)
	distill_session(root, dir_rel, sid, "opencode", _fake_transport())

	calls = []
	distill_session(root, dir_rel, sid, "opencode", _fake_transport(calls), max_chars=4000)
	assert len(calls) == 3, "cambiar el tamaño de fragmento invalida todo"


# ── P3.5 sección degraded → nunca se reusa ──


def test_degraded_section_is_never_reused(tmp_path, reuse_on):
	root, dir_rel, sid = _three(tmp_path)

	calls1 = []

	def degrading(system, user, max_tokens):
		calls1.append(user)
		raw = json.dumps({"title": f"titulo-{_tag_from(user)}", "summary": f"resumen-{_tag_from(user)}", "keywords": ["t"]})
		return raw + DEGRADED_MARKER if _tag_from(user) == "2" else raw

	distill_session(root, dir_rel, sid, "opencode", degrading)

	meta = _meta(tmp_path)
	degraded_units = [v for v in meta["units"].values() if v["degraded"]]
	assert len(degraded_units) == 1, "solo la sección truncada queda marcada degraded"
	section_file = [f for f in (root / dir_rel / "distill").glob("*.md") if "degraded: true" in f.read_text(encoding="utf-8")]
	assert len(section_file) == 1

	# re-run: la degraded se re-destila aunque su content_hash coincida.
	calls2 = []
	distill_session(root, dir_rel, sid, "opencode", _fake_transport(calls2))
	assert len(calls2) == 1, "la sección degraded se re-destila, nunca se reusa"


# ── P3.6 insertar un split en medio (cambia nnn) → unit_key estable y enlace no se rompe ──


def test_insert_split_renames_and_keeps_unit_key(tmp_path, reuse_on):
	root, dir_rel, sid = _three(tmp_path)
	distill_session(root, dir_rel, sid, "opencode", _fake_transport())

	# Inserta un split entre A(0001-0100) y B(0201-0300): B y C pasan de nnn 002/003
	# a 003/004; sus rangos (unit_key) NO cambian. Se renombran los ficheros de memento.
	memento_dir = root / dir_rel / "memento"
	(memento_dir / "002-mensajes-0201-0300.md").rename(memento_dir / "003-mensajes-0201-0300.md")
	(memento_dir / "003-mensajes-0401-0500.md").rename(memento_dir / "004-mensajes-0401-0500.md")
	(memento_dir / "002-mensajes-0101-0200.md").write_text(
		"> [!ref] memento/002-mensajes-0101-0200.md#l1-10\nUNIDAD-X\n", encoding="utf-8"
	)

	calls = []
	sections = distill_session(root, dir_rel, sid, "opencode", _fake_transport(calls))
	assert len(calls) == 1, "solo el split nuevo se destila; B y C se reusan"
	assert len(sections) == 4

	distill_dir = root / dir_rel / "distill"
	files = {f.name: f.read_text(encoding="utf-8") for f in distill_dir.glob("*.md")}
	# cada sección conserva su unit_key (rango) y adopta el nnn nuevo.
	by_unit_key = {}
	for name, text in files.items():
		uk = re.search(r"unit_key: (\S+)", text).group(1)
		section = re.search(r"section: (\d+)", text).group(1)
		by_unit_key[uk] = (name, section)
	assert by_unit_key["0201-0300"][0].startswith("003-"), "B renombrado a nnn 003"
	assert by_unit_key["0401-0500"][0].startswith("004-"), "C renombrado a nnn 004"
	assert by_unit_key["0101-0200"][0].startswith("002-"), "X nuevo en nnn 002"
	# el cuerpo de B (resumen-2) se conservó tras el renombrado.
	assert "resumen-2" in files[by_unit_key["0201-0300"][0]]
	# sin huérfanos: 4 ficheros, ninguno con el nnn viejo de B/C.
	assert len(files) == 4
	assert not any(n.startswith(("002-titulo-2", "003-titulo-3")) for n in files)


# ── P3.7 flag OFF → comportamiento actual exacto (borrar y rehacer) ──


def test_flag_off_is_full_redo_without_manifest(tmp_path, monkeypatch):
	# flag OFF (fijado): sin manifest, sin unit_key, borrar y rehacer.
	# Se fija porque el `.env` real trae MEMENTO_DISTILL_REUSE_ENABLED=true
	# desde el 2026-11-10: sin pin, un proceso con ese env da un falso rojo.
	monkeypatch.setattr(cfg, "MEMENTO_DISTILL_REUSE_ENABLED", False, raising=False)
	root, dir_rel, sid = _three(tmp_path)

	calls1 = []
	distill_session(root, dir_rel, sid, "opencode", _fake_transport(calls1))
	assert len(calls1) == 3

	calls2 = []
	distill_session(root, dir_rel, sid, "opencode", _fake_transport(calls2))
	assert len(calls2) == 3, "sin reuso: re-destila todo"

	assert not (root / dir_rel / "distill" / "_meta.json").exists()
	for f in (root / dir_rel / "distill").glob("*.md"):
		assert "unit_key" not in f.read_text(encoding="utf-8")


# ── Siembra (D-NB-11): primera noche sin manifest adopta secciones con prompt_version/engine vigentes ──


def test_seeding_adopts_existing_sections_with_matching_prompt_version(tmp_path, monkeypatch):
	# Primera corrida: flag OFF → secciones SIN unit_key, con prompt_version/engine.
	root, dir_rel, sid = _three(tmp_path)
	distill_session(root, dir_rel, sid, "opencode", _fake_transport())

	# Primera noche F2a: sin manifest → siembra. prompt_version/engine vigentes → adopta.
	monkeypatch.setattr(cfg, "MEMENTO_DISTILL_REUSE_ENABLED", True)
	calls = []
	sections = distill_session(root, dir_rel, sid, "opencode", _fake_transport(calls))
	assert len(calls) == 0, "la siembra adopta sin re-destilar"
	assert len(sections) == 3

	meta = _meta(tmp_path)
	assert len(meta["units"]) == 3
	for f in (root / dir_rel / "distill").glob("*.md"):
		assert "unit_key" in f.read_text(encoding="utf-8")


def test_seeding_redistills_sections_with_stale_prompt_version(tmp_path, monkeypatch):
	root, dir_rel, sid = _three(tmp_path)
	distill_session(root, dir_rel, sid, "opencode", _fake_transport())

	# prompt_version distinto al vigente → la siembra NO adopta; re-destila todo.
	monkeypatch.setattr(cfg, "MEMENTO_DISTILL_REUSE_ENABLED", True)
	monkeypatch.setattr(agentic_runtime, "distill_prompt_version", lambda: "pv-stale")
	calls = []
	sections = distill_session(root, dir_rel, sid, "opencode", _fake_transport(calls))
	assert len(calls) == 3, "prompt_version viejo → todo se re-destila"
	assert len(sections) == 3
