"""Actas del teatro y suspensión de tareas (AD-095 §teatro).

Qué se prueba, y por qué importa cada cosa:

- **Tres formas, un mecanismo**: nota suelta, suspensión con TTL, suspensión sin
  TTL. Es lo que el Operador pidió y lo que evita inventar tres sistemas.
- **Suspender no es apagar**: el despertar autónomo **no llama al modelo** cuando
  hay acta, pero el proceso sigue vivo y deja rastro (aquí, el mensaje se marca
  procesado y queda el warning). Es el caso real de hoy: el pulso horario es a la
  vez ritual y despertar; apagar el timer para callar al vigilante le miente.
- **Una excepción sin sujeto no se escribe**: no la puede obedecer nadie.
- **Visible sin buscarla**: el digest del handshake cuenta las actas (si no sale
  ahí, es el cajón que nadie abre).
"""

from __future__ import annotations

import time

import pytest

from red_pill.session import theatre
from red_pill.session.store import SessionRegistry


@pytest.fixture
def db(tmp_path, monkeypatch):
	"""`session.db` temporal: el resolvedor canónico apunta ahí."""
	path = str(tmp_path / "session.db")
	monkeypatch.setattr("red_pill.session.store.get_session_db", lambda: path)
	monkeypatch.setattr("red_pill.core.paths.get_session_db", lambda: path)
	SessionRegistry(path)
	return path


def _session(soul: str = "01a00000-0000-7000-8000-00000000000a") -> dict:
	return {
		"originator": "opencode:ses_a",
		"continuity_id": soul,
		"mission_id": "repo:next",
		"campaign_id": None,
		"role": "task",
	}


class TestActas:
	def test_nota_suelta_no_obedece_a_nadie(self, db):
		note = theatre.post_note(type="notice", summary="el pulso se tocó ayer")
		assert note["subject"] is None
		assert theatre.suspended("task:awakening", db_path=db) is None
		assert len(theatre.list_notes(db_path=db)) == 1

	def test_suspension_con_ttl_y_sin_ttl(self, db):
		theatre.post_note(type="suspension", summary="no despertar", subject="task:awakening")
		assert theatre.suspended("task:awakening", db_path=db)["summary"] == "no despertar"
		otra = theatre.post_note(
			type="suspension",
			summary="mantenimiento hasta el viernes",
			subject="task:pulse.wake.auto_heal",
			expires_at=time.time() + 86400,
		)
		assert otra["expires_at"]
		assert theatre.suspended("task:pulse.wake.auto_heal", db_path=db) is not None
		assert theatre.suspended("task:otra.cosa", db_path=db) is None

	def test_una_suspension_caducada_ya_no_suspende(self, db):
		theatre.post_note(
			type="suspension",
			summary="pasó",
			subject="task:awakening",
			expires_at=time.time() - 1,
		)
		assert theatre.suspended("task:awakening", db_path=db) is None
		assert len(theatre.list_notes(active_only=False, db_path=db)) == 1, "caduca, no se borra"

	def test_revocar_levanta_la_suspension(self, db):
		note = theatre.post_note(type="suspension", summary="x", subject="task:awakening")
		assert theatre.revoke(note["note_id"], reason="ya no hace falta", db_path=db)
		assert theatre.suspended("task:awakening", db_path=db) is None
		raw = theatre.list_notes(active_only=False, db_path=db)[0]
		assert raw["revoked_at"] and raw["revoked_reason"] == "ya no hace falta"

	def test_excepcion_sin_sujeto_se_rechaza(self, db):
		with pytest.raises(ValueError, match="subject"):
			theatre.post_note(type="suspension", summary="sin sujeto")
		with pytest.raises(ValueError, match="subject"):
			theatre.post_note(type="waiver", summary="sin señal")

	def test_sujeto_con_prefijo_desconocido_se_rechaza(self, db):
		with pytest.raises(ValueError, match="sujeto"):
			theatre.post_note(type="suspension", summary="x", subject="loquesea")

	def test_conteo_para_el_digest(self, db):
		theatre.post_note(type="suspension", summary="a", subject="task:awakening")
		theatre.post_note(type="decision", summary="b")
		theatre.post_note(type="decision", summary="c", expires_at=time.time() - 1)
		assert theatre.counts(db_path=db) == {"suspension": 1, "decision": 1, "total": 2}


class TestLaTareaObedece:
	def test_el_despertar_suspendido_no_llama_al_modelo(self, db, monkeypatch):
		"""El corazón del diseño: el proceso vive, el trabajo caro no ocurre."""
		import sqlite3

		theatre.post_note(type="suspension", summary="parado a drede", subject="task:awakening")

		called: list = []

		from red_pill.core import agent_worker

		worker = agent_worker.IDEWorker.__new__(agent_worker.IDEWorker)
		monkeypatch.setattr(
			agent_worker.IDEWorker,
			"_process_via_bridge",
			lambda self, *a, **k: called.append("bridge"),
			raising=True,
		)

		conn = sqlite3.connect(":memory:")
		conn.execute("CREATE TABLE inbox (id INTEGER PRIMARY KEY, status TEXT)")
		conn.execute("INSERT INTO inbox (id, status) VALUES (1, 'PENDING')")
		conn.commit()
		cursor = conn.cursor()
		worker._process_awakening("SYSTEM: despierta", [1], cursor, conn)
		conn.commit()

		assert called == [], "suspendido: no se llama al modelo"
		status = cursor.execute("SELECT status FROM inbox WHERE id = 1").fetchone()[0]
		assert status == "PROCESSED", "el mensaje se consume: no se reintenta en bucle"

	def test_sin_acta_el_despertar_sigue_su_curso(self, db):
		"""Sin nota, el gate no estorba: devuelve None y el flujo sigue."""
		assert theatre.suspended("task:awakening", db_path=db) is None


class TestSuperficieMCP:
	async def test_post_y_fetch_de_teatro(self, db):
		from red_pill.coro import service

		out = await service.post(
			_session(),
			{
				"scope": "teatro",
				"type": "suspension",
				"subject": "task:awakening",
				"summary": "sin despertares hasta el lunes",
				"expires_in_days": 3,
			},
		)
		assert "CORO teatro" in out and "task:awakening" in out
		assert theatre.suspended("task:awakening", db_path=db) is not None

		listed = await service.fetch(_session(), {"scope": "teatro"})
		assert "TEATRO" in listed and "sin despertares hasta el lunes" in listed
		assert "hasta" in listed, "la caducidad es parte del dato"

	async def test_el_post_normal_sigue_siendo_de_mision(self, db):
		from red_pill.coro import service

		out = await service.post(_session(), {"summary": "fase hecha", "type": "phase_done"})
		assert "CORO post" in out and "repo:next" in out
		assert theatre.list_notes(db_path=db) == [], "sin scope=teatro no toca las actas"

	def test_el_schema_del_payload_es_legible(self):
		"""El registry publica las propiedades: sin ellas el modelo adivina campos."""
		from red_pill.coro import register_coro
		from red_pill.registry import ToolRegistry

		registry = ToolRegistry()

		async def _caller(_args):
			return {}

		register_coro(registry, caller_session=_caller)
		tool = [t for t in registry.get_tools() if t.name == "coro_api"][0]
		props = tool.inputSchema["properties"]["payload"]["properties"]
		assert {"to", "verb", "body", "scope", "subject"} <= set(props)
		assert props["verb"]["enum"] == ["notify", "ask", "reply", "park"]


class TestElDespertarEnElTablon:
	"""El despertar deja de depender solo del desk: lee y anota en el tablón.

	Por qué importa: el log del desk es un fichero que solo se lee si el siguiente
	despertar se acuerda de abrirlo. El acta es el puntero que sale en el digest de
	todas las almas — el 2026-10-29 un fix quedó varado una hora en una rama porque
	nadie supo que existía.
	"""

	def test_el_prompt_le_pide_leer_y_anotar_con_reglas(self):
		from red_pill.core.agent_worker import AWAKENING_THEATRE_INSTRUCTIONS as block

		assert '"scope": "teatro"' in block, "tiene que leer las actas"
		assert '"type": "notice"' in block, "y escribir su handoff como acta"
		assert "task:awakening" in block, "una suspensión activa lo para aunque ya esté corriendo"
		assert "not a diary" in block, "sin esto, cada despertar inunda el digest"
		assert "awakening/<your log file>" in block, "el acta apunta al log: no lo duplica"

	async def test_el_acta_del_despertar_es_legible_por_cualquier_alma(self, db):
		from red_pill.coro import service

		acta = await service.post(
			_session("01a00000-0000-7000-8000-00000000000f"),
			{
				"scope": "teatro",
				"type": "notice",
				"summary": "ruff verde en gguf_info; commit 5f8ef28 en awaken/20261029-2000",
				"ref": "awakening/20261029_2000.log",
			},
		)
		assert "CORO teatro" in acta
		visto = await service.fetch(_session("01a00000-0000-7000-8000-0000000000aa"), {"scope": "teatro"})
		assert "5f8ef28" in visto, "otra alma lo ve sin abrir el desk"
