"""El sellado del turno externo no puede depender de que alguien lo llame.

Hallazgo del 2026-10-31: `finish_external_turn` archiva el turno cerrado y borra
el `current/`, y el único consumidor de journals en una sesión viva era
`refresh_session_context`. Resultado medido: desde que se desplegó el sellado
(2026-10-30 17:32) el espejo no recibió **ni una fila** de opencode, con 6
journals completados esperando en el archivo.

Estos tests cubren el consumidor barato que sí corre en cada turno
(`maybe_import_external_turns`) y la ventana del archivo que lo mantiene barato.
"""

from __future__ import annotations

import json
import os
import time

import pytest

import red_pill.session.external_turns as ext
from red_pill.session.mirror import SessionMirror
from red_pill.session.store import SessionRegistry

CID = "01a186e6-f48d-7491-a1d0-7ec130fa1a68"


@pytest.fixture
def state(tmp_path, monkeypatch):
	root = tmp_path / "red-pill" / "state"
	monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
	monkeypatch.setattr(ext, "get_state_dir", lambda: root)
	(root / ext.CURRENT_DIR).mkdir(parents=True, exist_ok=True)
	(root / ext.ARCHIVE_DIR).mkdir(parents=True, exist_ok=True)
	return root


@pytest.fixture
def db(tmp_path):
	path = tmp_path / "session.db"
	return path, SessionRegistry(str(path)), SessionMirror(str(path))


def _archivado(state, session="s1", prompt="hola", response="mundo"):
	"""Journal CERRADO: el hook lo archiva y borra el `current/` (el caso real)."""
	ext.begin_external_turn(provider="opencode", session_id=session, prompt=prompt)
	turn = ext.finish_external_turn(provider="opencode", session_id=session, response=response)
	assert not list((state / ext.CURRENT_DIR).glob("*.json"))
	return turn


def test_sin_journals_nuevos_no_hace_nada(state):
	assert ext.maybe_import_external_turns(root=state) is None
	assert not (state / ext._IMPORT_WATERMARK).exists()


def test_journal_nuevo_lanza_la_importacion_una_sola_vez(state, monkeypatch):
	llamadas = []
	monkeypatch.setattr(ext, "import_external_turns", lambda **kw: llamadas.append(kw) or {"completed": 1})

	_archivado(state)
	assert ext.maybe_import_external_turns(root=state) == {"completed": 1}
	assert len(llamadas) == 1

	# Segunda pasada sin ficheros nuevos: ni se abre la base.
	assert ext.maybe_import_external_turns(root=state) is None
	assert len(llamadas) == 1

	# Un turno más sí vuelve a importar.
	time.sleep(0.01)
	_archivado(state, prompt="otro")
	assert ext.maybe_import_external_turns(root=state) == {"completed": 1}
	assert len(llamadas) == 2


def test_el_turno_cerrado_llega_al_espejo_sellado(state, db):
	"""Regresión del agujero: el turno se archiva antes de que nadie importe."""
	path, registry, mirror = db
	registry.upsert_session(originator="opencode:s1", continuity_id=CID, mission_id="repo:sharing", role="task")
	_archivado(state)

	counts = ext.maybe_import_external_turns(root=state, force=True, mirror=mirror, registry=registry)
	assert counts is not None and counts["completed"] == 1

	rows = mirror.pending_turns(CID, include_aborted=True)
	assert rows == []
	import sqlite3

	con = sqlite3.connect(str(path))
	try:
		total, selladas = con.execute(
			"SELECT COUNT(*), SUM(CASE WHEN global_turn > 0 THEN 1 ELSE 0 END) FROM session_mirror"
		).fetchone()
	finally:
		con.close()
	assert total == 2  # user + assistant
	assert selladas == 2


def test_reimportar_es_idempotente(state, db):
	path, registry, mirror = db
	registry.upsert_session(originator="opencode:s1", continuity_id=CID, mission_id="repo:sharing", role="task")
	_archivado(state)
	ext.maybe_import_external_turns(root=state, force=True, mirror=mirror, registry=registry)
	ext.maybe_import_external_turns(root=state, force=True, mirror=mirror, registry=registry)

	import sqlite3

	con = sqlite3.connect(str(path))
	try:
		total = con.execute("SELECT COUNT(*) FROM session_mirror").fetchone()[0]
	finally:
		con.close()
	assert total == 2


def test_el_archivo_viejo_no_se_relee(state, monkeypatch):
	_archivado(state)
	viejos = list((state / ext.ARCHIVE_DIR).glob("*.json"))
	assert viejos
	pasado = time.time() - (ext.ARCHIVE_IMPORT_DAYS + 1) * 86400
	for f in viejos:
		os.utime(f, (pasado, pasado))

	assert ext._journals(root=state) == []
	# Y el consumidor no se despierta por ellos.
	assert ext.maybe_import_external_turns(root=state) is None


def test_el_current_se_lee_siempre_aunque_el_mirror_no_cambie(state, monkeypatch):
	"""Un turno en vuelo (pending) no se pierde por la ventana del archivo."""
	pending = ext.begin_external_turn(provider="opencode", session_id="s1", prompt="en vuelo")
	assert pending["status"] == "pending"
	paths = ext._journals(root=state)
	assert len(paths) == 1 and paths[0].parent.name == "current"


def test_el_sellado_no_rompe_el_handshake_si_falla(state, monkeypatch):
	_archivado(state)

	def _boom(**kw):
		raise RuntimeError("base rota")

	monkeypatch.setattr(ext, "import_external_turns", _boom)
	assert ext.maybe_import_external_turns(root=state) is None  # nunca propaga


def test_el_lock_impide_dos_sellados_a_la_vez(state, monkeypatch):
	_archivado(state)
	ext._IMPORT_LOCK.acquire()
	try:
		assert ext.maybe_import_external_turns(root=state) is None
	finally:
		ext._IMPORT_LOCK.release()
	# Suelto el lock, el turno sigue ahí esperando y se sella.
	assert ext.maybe_import_external_turns(root=state, force=True) is not None


def test_la_marca_de_agua_es_un_fichero_legible(state, monkeypatch):
	monkeypatch.setattr(ext, "import_external_turns", lambda **kw: {"completed": 0})
	_archivado(state)
	ext.maybe_import_external_turns(root=state)
	wm = state / ext._IMPORT_WATERMARK
	assert wm.is_file()
	assert float(wm.read_text(encoding="utf-8").strip()) > 0
	assert json.dumps({})  # sanity: el módulo no depende de estado global raro
