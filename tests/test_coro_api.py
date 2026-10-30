"""`coro_api` — el coro como una sola puerta (AD-095, slice S1).

Qué se prueba, en el orden del contrato (`docs/TECHNICAL/CORO_PROTOCOL.md`):

- **Tablón vs correspondencia**: `post` escribe una nota sin destinatario; `send`
  escribe un mensaje dirigido a un alma. El mensaje **no** aparece en el tablón de
  la misión para terceros (solo para su destinatario y su autor).
- **La dirección es el alma**: el buzón (`inbox`) se consulta por `continuity_id`
  y sobrevive a que el cuerpo esté muerto (`park`).
- **Verbos (D-02/D-12)**: `ask` espera respuesta por defecto, `notify` no, `reply`
  exige `reply_to` y **no consume salto**, el rebote degrada a `park`.
- **Purga**: las tools viejas no están en el catálogo (sin alias).
- **D-07**: despertar lo decide la política (matriz de roles + entrada), no el
  emisor: un mensaje de un alma sin fila en el registro no despierta a nadie.

Unit tests del servicio (`service.*` con sesión inyectada) + dos tests de la
superficie MCP real para probar que el registro de la tool funciona.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from red_pill.core import soul_notify
from red_pill.session import delivery
from red_pill.session.store import SessionRegistry

# UUIDv7 realistas: se distinguen pronto, como los de verdad (los sintéticos que
# compartían 20 caracteres hacían imposible probar la resolución por prefijo).
A = "01a187ba-a9f6-718d-b9e1-d531b8d7a947"
B = "01a186e6-f48d-7491-a1d0-7ec130fa1a68"
C = "01a186ac-e466-7449-b463-eace57555982"


@pytest.fixture
def reg(tmp_path, monkeypatch):
	"""Registro con tres almas: A y B en la misma misión, C en otra.

	Se apunta el resolvedor de rutas a una BD temporal (el servicio construye
	`SessionRegistry()` sin ruta: la identidad la pone el canal, no la BD).
	"""
	path = str(tmp_path / "session.db")
	monkeypatch.setattr("red_pill.session.store.get_session_db", lambda: path)
	monkeypatch.setattr("red_pill.core.paths.get_session_db", lambda: path)
	r = SessionRegistry(path)
	r.upsert_session(originator="opencode:ses_a", continuity_id=A, mission_id="repo:next")
	r.upsert_session(originator="opencode:ses_b", continuity_id=B, mission_id="repo:next")
	r.upsert_session(originator="opencode:ses_c", continuity_id=C, mission_id="repo:otra")
	return r


def _session(soul: str, originator: str, mission: str = "repo:next") -> dict:
	return {"originator": originator, "continuity_id": soul, "mission_id": mission, "campaign_id": None, "role": "task"}


@pytest.fixture
def push(monkeypatch):
	"""Aviso encendido y transporte fake en el seam (nunca `opencode run` real)."""
	monkeypatch.setenv(soul_notify.ENV_DISABLE, "0")
	calls: list = []

	def fake(session_id, text):
		calls.append((session_id, text))
		return True

	with patch.dict(soul_notify._TRANSPORTS, {"cli": fake}):
		yield calls


# ── Tablón vs correspondencia ────────────────────────────────────────────────


class TestTablónYCorrespondencia:
	async def test_post_escribe_nota_sin_destinatario(self, reg):
		from red_pill.coro import service

		out = await service.post(_session(A, "opencode:ses_a"), {"summary": "fase 1 hecha", "type": "phase_done"})
		assert "CORO post" in out
		events = reg.fetch_events("repo:next")
		assert [e["type"] for e in events] == ["phase_done"]
		assert events[0]["to_continuity"] is None

	async def test_un_mensaje_no_sale_en_el_tablon_de_la_mision(self, reg, push):
		from red_pill.coro import service

		# Un cuarto par en la MISMA misión: tiene que seguir sin ver la carta ajena.
		D = "01a00000-0000-7000-8000-00000000000d"
		reg.upsert_session(originator="opencode:ses_d", continuity_id=D, mission_id="repo:next")
		await service.send(_session(A, "opencode:ses_a"), {"to": B, "verb": "park", "body": "esto es privado"})
		# El tablón de la misión no renderiza correspondencia: solo la ven su
		# destinatario (también por `inbox`) y su autor.
		assert reg.fetch_events("repo:next", viewer_continuity_id=D) == []
		assert reg.fetch_events("repo:next", viewer_continuity_id=C) == []
		assert [e["to_continuity"] for e in reg.fetch_inbox(B)] == [B]
		# El autor sí lo ve en su propio registro (auditoría de lo que envió).
		assert [e["type"] for e in reg.fetch_events("repo:next", viewer_continuity_id=A)] == ["message"]

	async def test_inbox_es_por_alma_y_no_por_sesion(self, reg):
		from red_pill.coro import service

		await service.send(_session(A, "opencode:ses_a"), {"to": B, "verb": "park", "body": "para B"})
		assert len(reg.fetch_inbox(B)) == 1
		assert reg.fetch_inbox(A) == []
		out = await service.inbox(_session(A, "opencode:ses_a"), {})
		assert "sin mensajes" in out


# ── Verbos ───────────────────────────────────────────────────────────────────


class TestVerbos:
	async def test_park_no_despierta_y_queda_queued(self, reg, push):
		from red_pill.coro import service

		out = await service.send(_session(A, "opencode:ses_a"), {"to": B, "verb": "park", "body": "cuando puedas"})
		assert "estado=queued" in out
		assert push == [], "park no despierta a nadie"

	async def test_notify_despierta_una_vez(self, reg, push):
		from red_pill.coro import service

		out = await service.send(_session(A, "opencode:ses_a"), {"to": B, "verb": "notify", "body": "he cerrado X"})
		assert "estado=delivered" in out
		assert len(push) == 1 and push[0][0] == "ses_b"
		assert "respuesta: NO" in push[0][1], "D-13: el silencio tiene que verse"

	async def test_ask_espera_respuesta_por_defecto(self, reg, push):
		from red_pill.coro import service

		out = await service.send(_session(A, "opencode:ses_a"), {"to": B, "verb": "ask", "body": "¿qué ruta uso?"})
		assert "respuesta: SÍ" in out
		assert "respuesta: SÍ" in push[0][1]

	async def test_reply_no_consume_salto_y_hereda_hilo(self, reg, push):
		from red_pill.coro import service

		out = await service.send(_session(A, "opencode:ses_a"), {"to": B, "verb": "ask", "body": "¿sigues?"})
		parent_id = out.split("msg=")[1].split()[0].strip()
		reply = await service.send(
			_session(B, "opencode:ses_b"),
			{"verb": "reply", "reply_to": parent_id, "body": "sigo"},
		)
		assert "salto 0/2" in reply, "la réplica no salta (D-02)"
		assert "salto 0/2" in out
		# El hilo se heredó del mensaje contestado.
		assert out.split("hilo ")[1].split()[0] == reply.split("hilo ")[1].split()[0]

	async def test_reply_exige_reply_to(self, reg):
		from red_pill.coro import service

		with pytest.raises(service.CoroError, match="reply_to"):
			await service.send(_session(B, "opencode:ses_b"), {"verb": "reply", "to": A, "body": "x"})

	async def test_no_puedes_contestar_un_mensaje_que_no_era_para_ti(self, reg):
		from red_pill.coro import service

		out = await service.send(_session(A, "opencode:ses_a"), {"to": B, "verb": "ask", "body": "privado"})
		parent_id = out.split("msg=")[1].split()[0].strip()
		with pytest.raises(service.CoroError, match="no era para ti"):
			await service.send(_session(C, "opencode:ses_c"), {"verb": "reply", "reply_to": parent_id, "body": "cotilleo"})

	async def test_rebote_degrada_a_park_y_conserva_el_mensaje(self, reg, push):
		from red_pill.coro import service

		# Destinatario registrado pero con `hold`: no se le despierta, pero el
		# mensaje NO se pierde (queda en su inbox para el pull).
		from red_pill.session import wake_policy

		wake_policy.set_inbound(B, state=wake_policy.INBOUND_HOLD)
		out = await service.send(_session(A, "opencode:ses_a"), {"to": B, "verb": "notify", "body": "hola"})
		assert "estado=queued" in out and "park" in out
		assert push == []
		assert len(reg.fetch_inbox(B)) == 1


# ── Fail-closed ──────────────────────────────────────────────────────────────


class TestFailClosed:
	async def test_alma_desconocida_se_rechaza(self, reg):
		from red_pill.coro import service

		with pytest.raises(service.CoroError, match="alma desconocida"):
			await service.send(_session(A, "opencode:ses_a"), {"to": "01a99999-0000-7000-8000-000000000000", "verb": "park", "body": "x"})

	async def test_no_te_escribes_a_ti_misma(self, reg):
		from red_pill.coro import service

		with pytest.raises(service.CoroError, match="a ti misma"):
			await service.send(_session(A, "opencode:ses_a"), {"to": A, "verb": "park", "body": "x"})

	async def test_techo_de_saltos(self, reg):
		from red_pill.coro import service

		with pytest.raises(service.CoroError, match="techo de saltos"):
			await service.send(_session(A, "opencode:ses_a"), {"to": B, "verb": "park", "body": "x", "hop": 3})

	async def test_sin_cuerpo_no_se_publica(self, reg):
		from red_pill.coro import service

		with pytest.raises(service.CoroError, match="cuerpo compuesto"):
			await service.post(_session(A, ""), {"summary": "x"})

	async def test_el_mensaje_caduca(self, reg, monkeypatch):
		from red_pill.coro import protocol, service

		# Presupuesto negativo = ya caducado al nacer (no se puede reescribir el
		# evento: el tablón es append-only, y eso es a propósito).
		monkeypatch.setattr(protocol, "budget_s", lambda *a, **k: -1.0)
		await service.send(_session(A, "opencode:ses_a"), {"to": B, "verb": "park", "body": "x"})
		assert reg.fetch_inbox(B) == []
		assert len(reg.fetch_inbox(B, include_expired=True)) == 1


# ── Ack ──────────────────────────────────────────────────────────────────────


class TestAck:
	async def test_ack_marca_leido_y_el_inbox_lo_dice(self, reg):
		from red_pill.coro import service

		out = await service.send(_session(A, "opencode:ses_a"), {"to": B, "verb": "park", "body": "leeme"})
		event_id = out.split("msg=")[1].split()[0].strip()
		assert delivery.get_delivery(event_id, B) is None
		ack = await service.ack(_session(B, "opencode:ses_b"), {"event_id": event_id})
		assert "leído" in ack
		assert delivery.get_delivery(event_id, B)["state"] == delivery.STATE_READ

	async def test_no_puedes_ackear_un_mensaje_ajeno(self, reg):
		from red_pill.coro import service

		out = await service.send(_session(A, "opencode:ses_a"), {"to": B, "verb": "park", "body": "x"})
		event_id = out.split("msg=")[1].split()[0].strip()
		with pytest.raises(service.CoroError, match="no está en tu inbox"):
			await service.ack(_session(C, "opencode:ses_c"), {"event_id": event_id})


# ── La superficie MCP ────────────────────────────────────────────────────────


class TestMCP:
	@staticmethod
	async def _call(name, arguments):
		from red_pill.mcp_server import handle_call_tool

		return (await handle_call_tool(name, arguments))[0].text

	async def test_la_tool_existe_y_publica(self, tmp_path):
		bridge = {"originator": "opencode:ses_a", "workdir": str(tmp_path)}
		with patch("red_pill.mcp_server._harness_bridge", return_value=bridge):
			with patch("red_pill.mcp_server._current_git_branch", return_value="next"):
				out = await self._call(
					"coro_api",
					{"action": "post", "payload": {"summary": "hola coro", "type": "intent_updated"}},
				)
		assert "CORO post" in out and "repo:next" in out

	async def test_el_catalogo_no_ofrece_dos_caminos(self):
		from red_pill.mcp_server import handle_list_tools

		names = {t.name for t in await handle_list_tools()}
		assert "coro_api" in names
		for purged in ("announce_intent", "fetch_events", "check_parallel_sessions", "session_board"):
			assert purged not in names
		coro = [t for t in await handle_list_tools() if t.name == "coro_api"][0]
		assert set(coro.inputSchema["properties"]["action"]["enum"]) == {
			"post",
			"send",
			"inbox",
			"ack",
			"fetch",
			"board",
			"object",
		}


# ── Migración (la BD real no nace fresca) ────────────────────────────────────


class TestMigracionV8:
	async def test_una_bd_v7_gana_el_destinatario_sin_perder_eventos(self, tmp_path):
		"""La migración se prueba sobre una BD v7 REAL, no sobre una recién creada.

		El fallo que esto cierra: el índice del destinatario vivía en `_SCHEMA`,
		que se ejecuta **antes** de los `ALTER`. En una BD existente la tabla no
		tiene la columna todavía → `no such column: to_continuity`, y el registro
		ni siquiera abría. Los tests con BD fresca no podían verlo.
		"""
		import sqlite3

		path = str(tmp_path / "v7.db")
		con = sqlite3.connect(path)
		con.executescript(
			"""
			CREATE TABLE mission_events (
				event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
				event_id TEXT NOT NULL UNIQUE,
				type TEXT NOT NULL,
				mission_id TEXT NOT NULL,
				campaign_id TEXT,
				continuity_id TEXT,
				originator TEXT,
				global_turn INTEGER NOT NULL DEFAULT 0,
				summary TEXT NOT NULL,
				ref TEXT,
				sealed INTEGER NOT NULL DEFAULT 0,
				created_at REAL NOT NULL
			);
			INSERT INTO mission_events (event_id, type, mission_id, summary, created_at)
				VALUES ('viejo', 'phase_done', 'repo:next', 'nota de antes de v8', 1.0);
			PRAGMA user_version=7;
			"""
		)
		con.commit()
		con.close()

		reg = SessionRegistry(path)
		cols = {row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(mission_events)")}
		assert {"to_continuity", "verb", "thread_id", "hop", "expects_reply", "value_class", "expires_at"} <= cols
		assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == 8
		assert reg.fetch_inbox(A) == [], "ningún evento viejo se convierte en mensaje"
		assert [e["summary"] for e in reg.fetch_events("repo:next")] == ["nota de antes de v8"]


class TestDireccionesQueSePuedenCopiar:
	"""Un protocolo que no deja contestar es un acertijo (incidente 2026-10-30).

	Medido en campo: K2 recibió un mensaje y no pudo responder — el `board` le daba
	el alma truncada a 11 caracteres y el `inbox` le daba el `seq`, no el id.
	"""

	async def test_se_puede_escribir_con_un_prefijo_unico(self, reg, push):
		from red_pill.coro import service

		out = await service.send(_session(A, "opencode:ses_a"), {"to": B[:12], "verb": "park", "body": "hola"})
		assert "estado=queued" in out
		assert reg.fetch_inbox(B)[0]["to_continuity"] == B

	async def test_un_prefijo_ambiguo_se_rechaza(self, reg):
		from red_pill.coro import service

		# Un alma gemela que comparte los 8 primeros caracteres con B.
		reg.upsert_session(originator="opencode:ses_gemela", continuity_id=B[:8] + "-dead-beef-0000-000000000000", mission_id="repo:next")
		with pytest.raises(service.CoroError, match="ambiguo"):
			await service.send(_session(A, "opencode:ses_a"), {"to": B[:8], "verb": "park", "body": "x"})

	async def test_un_prefijo_corto_se_rechaza(self, reg):
		from red_pill.coro import service

		with pytest.raises(service.CoroError, match="demasiado corta"):
			await service.send(_session(A, "opencode:ses_a"), {"to": "01a0", "verb": "park", "body": "x"})

	async def test_reply_acepta_el_prefijo_del_evento(self, reg, push):
		from red_pill.coro import service

		out = await service.send(_session(A, "opencode:ses_a"), {"to": B, "verb": "ask", "body": "¿sigues?"})
		event_id = out.split("msg=")[1].split()[0].strip()
		reply = await service.send(_session(B, "opencode:ses_b"), {"verb": "reply", "reply_to": event_id[:12], "body": "sigo"})
		assert "estado=delivered" in reply, "el prefijo del id resuelve al mensaje"

	async def test_thread_es_alias_de_thread_id(self, reg):
		from red_pill.coro import service

		out = await service.send(_session(A, "opencode:ses_a"), {"to": B, "verb": "park", "body": "x", "thread": "E-777"})
		assert "hilo E-777" in out

	async def test_el_inbox_da_el_id_y_como_contestar(self, reg):
		from red_pill.coro import service

		await service.send(_session(A, "opencode:ses_a"), {"to": B, "verb": "park", "body": "leeme"})
		visto = await service.inbox(_session(B, "opencode:ses_b"), {})
		assert "msg=" in visto and "reply_to=" in visto

	async def test_el_board_muestra_el_alma_completa(self, reg):
		from red_pill.coro import service

		tabla = await service.board(_session(A, "opencode:ses_a"), {"scope": "sesiones"})
		assert B in tabla, "sin el id completo no hay a quién contestar"
