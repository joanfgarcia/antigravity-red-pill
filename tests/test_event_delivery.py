"""Fase 5 (C2): adaptador de entrega de eventos del tablón al arnés opencode.

Contrato que se prueba (en el orden del módulo):
- **Entrega correcta**: un evento dirigido a un alma se convierte en un nudge en
	su cuerpo vivo, pasando por el seam `_TRANSPORTS` de `soul_notify` — no por un
	segundo mecanismo.
- **Degradación a pull**: sin sesión viva, o en un arnés sin punto de inyección,
	el evento **se queda** en el tablón (append-only) y el estado de entrega no se
	toca. Nada se pierde.
- **No duplicado**: el CAS de `claim_delivery` y el estado terminal impiden
	empujar dos veces lo mismo; el pull (cursor del digest) gana y cierra el push.
- **Sin bucles**: tras `MAX_PUSH_ATTEMPTS` el evento cierra como `given_up` y
	deja de reintentarse; el eco al propio autor se marca `skipped`.

Los tests usan una BD temporal (`db_path`) y un transporte fake: ninguno lanza
`opencode run` de verdad (las guardas de `conftest` lo bloquearían).
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from red_pill.core import soul_notify
from red_pill.session import delivery
from red_pill.session.store import SessionRegistry


@pytest.fixture
def reg(tmp_path):
	"""Registro con dos almas vivas (una por cuerpo de opencode).

	Desde AD-095 la entrega resuelve **emisor y destinatario** contra
	`session_registry` (D-07): sin fila no hay rol ni misión, y ese mensaje
	espera al pull. El emisor se resuelve por su **cuerpo** (`originator`), no por
	el alma del evento (que es el destinatario): por eso se siembra también el leg
	del job, que es quien publica en el caso canónico.
	"""
	r = SessionRegistry(str(tmp_path / "session.db"))
	for soul, originator in (("alma-1", "opencode:ses_a"), ("alma-2", "opencode:ses_b")):
		r.upsert_session(originator=originator, continuity_id=soul, mission_id="repo:next")
	r.upsert_session(originator="dag:job-1", continuity_id="job-1", mission_id="repo:next", role="orchestrator")
	return r


@pytest.fixture
def db(reg):
	return reg.db_path


@pytest.fixture
def push(monkeypatch):
	"""Aviso encendido + transporte fake en el seam. Devuelve lo que se empujó."""
	monkeypatch.setenv(soul_notify.ENV_DISABLE, "0")
	calls: list = []

	def fake(session_id, text):
		calls.append((session_id, text))
		return True

	with patch.dict(soul_notify._TRANSPORTS, {"cli": fake}):
		yield calls


def _event(reg, *, continuity="alma-1", originator="dag:job-1", kind="phase_done", summary="etapa c2 hecha", sealed=False, ref=None):
	"""Evento dirigido al alma `continuity` (AD-095: el destinatario va en el evento).

	El caso canónico es el de AD-090: el cuerpo es un job (`dag:job-1`) que publica
	en nombre del alma que lo lanzó; la dirección sigue siendo el alma.
	"""
	return reg.add_event(
		event_type=kind,
		mission_id="repo:next",
		summary=summary,
		continuity_id=continuity,
		originator=originator,
		global_turn=1,
		sealed=sealed,
		ref=ref,
		to_continuity=continuity,
	)


class TestEntregaCorrecta:
	def test_empuja_el_evento_al_cuerpo_vivo(self, reg, db, push):
		ev = _event(reg)
		report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert len(push) == 1, "el nudge no llegó al transporte"
		assert push[0][0] == "ses_a"
		assert "etapa c2 hecha" in push[0][1]
		assert report["handed_off"][0]["event_id"] == ev["event_id"]
		assert delivery.get_delivery(ev["event_id"], "alma-1", db_path=db)["state"] == delivery.STATE_HANDED_OFF

	def test_el_nudge_es_dato_no_orden(self, reg, db, push):
		"""D-09: avisar no es mandar. El texto no puede pedir nada al receptor."""
		_event(reg, kind="blocked", summary="etapa c3 bloqueada", ref="job-9")
		delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		text = push[0][1]
		assert "DATO, no orden" in text
		assert "No requiere respuesta" in text
		assert "blocked" in text
		assert "job-9" in text

	def test_la_direccion_es_el_alma_no_la_sesion(self, reg, db, push):
		"""Dos almas con eventos: entregar a una no empuja nada a la otra (D-05)."""
		_event(reg, continuity="alma-1", summary="para el alma uno")
		_event(reg, continuity="alma-2", summary="para el alma dos")
		delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert len(push) == 1
		assert "para el alma uno" in push[0][1]

	def test_el_cuerpo_se_resuelve_por_presencia(self, reg, db, push):
		"""Sin `originator` explícito: el leg lo decide `soul_notify` (idle también)."""
		_event(reg)
		with patch.object(soul_notify, "resolve_live_leg", return_value="opencode:ses_idle"):
			report = delivery.deliver_events("alma-1", db_path=db)
		assert report["leg"] == "opencode:ses_idle"
		assert push[0][0] == "ses_idle"

	def test_no_abre_otro_canal_de_transporte(self, db):
		"""El adaptador solo usa seams que existen en `soul_notify` (AD-090)."""
		assert set(delivery.INJECTION_POINTS.values()) <= set(soul_notify._TRANSPORTS)

	def test_claude_code_se_empuja_por_su_socket(self, reg, db, monkeypatch):
		"""F6: un cuerpo claude_code va por `claude_socket`, no por el CLI de opencode."""
		monkeypatch.setenv(soul_notify.ENV_DISABLE, "0")
		monkeypatch.delenv(soul_notify.ENV_TRANSPORT, raising=False)
		por_cli, por_socket = [], []
		ev = _event(reg)
		with patch.dict(
			soul_notify._TRANSPORTS,
			{"cli": lambda sid, txt: por_cli.append(sid) or True, "claude_socket": lambda sid, txt: por_socket.append(sid) or True},
		):
			report = delivery.deliver_events("alma-1", originator="claude_code:uuid-c1", db_path=db)
		assert por_cli == []
		assert por_socket == ["uuid-c1"]
		assert delivery.get_delivery(ev["event_id"], "alma-1", db_path=db)["reason"] == "handed_to_transport:claude_socket"
		assert report["handed_off"]

	def test_varios_eventos_en_una_pasada_respetran_el_orden(self, reg, db, push):
		_event(reg, summary="primero")
		_event(reg, summary="segundo")
		delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert len(push) == 2
		assert "primero" in push[0][1] and "segundo" in push[1][1]


class TestDegradacionPull:
	def test_sin_sesion_viva_el_evento_se_queda_en_el_tablon(self, reg, db, push):
		"""Fail-closed: sin cuerpo no se empuja, no se escribe estado y no se pierde."""
		ev = _event(reg)
		with patch.object(soul_notify, "resolve_live_leg", return_value=None):
			report = delivery.deliver_events("alma-1", db_path=db)
		assert push == [], "no hay a quién empujar"
		assert [item["reason"] for item in report["deferred"]] == ["no_live_body"]
		assert delivery.get_delivery(ev["event_id"], "alma-1", db_path=db) is None
		assert [e["event_id"] for e in delivery.pending_for_soul("alma-1", db_path=db)] == [ev["event_id"]]
		# El evento sigue en el registro (append-only). No se busca en la vista del
		# tablón: desde AD-095 la correspondencia no se renderiza en él.
		assert reg.get_event(ev["event_id"]) is not None, "el tablón no se toca"

	def test_arnes_sin_punto_de_inyeccion_degrada_a_pull(self, reg, db, push):
		"""pi/telegram no tienen inyección aquí: no se empuja nada."""
		_event(reg)
		for provider in ("pi", "telegram"):
			report = delivery.deliver_events("alma-1", originator=f"{provider}:ses_x", db_path=db)
			assert push == []
			assert report["handed_off"] == []
			assert report["deferred"][0]["reason"] == f"no_injection_point:{provider}"
		assert len(delivery.pending_for_soul("alma-1", db_path=db)) == 1, "sigue pendiente por si migra a opencode"

	def test_el_pull_gana_y_el_push_no_duplica(self, reg, db, push):
		"""Si el cursor del digest ya lo anunció, empujarlo después es duplicarlo."""
		ev = _event(reg)
		assert delivery.reconcile_pulled("alma-1", until_seq=ev["event_seq"], db_path=db) == 1
		report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert push == []
		assert report["handed_off"] == []
		assert delivery.get_delivery(ev["event_id"], "alma-1", db_path=db)["state"] == delivery.STATE_PULLED

	def test_reconcile_no_cierra_lo_que_el_cursor_no_pasa(self, reg, db):
		ev = _event(reg)
		assert delivery.reconcile_pulled("alma-1", until_seq=ev["event_seq"] - 1, db_path=db) == 0
		assert len(delivery.pending_for_soul("alma-1", db_path=db)) == 1

	def test_el_cursor_cierra_el_push_aunque_el_reconcile_no_corra(self, reg, db, push):
		"""Defensa en profundidad: el filtro del cursor no depende de que el
		handshake lograra llamar a `reconcile_pulled`."""
		ev = _event(reg)
		reg.upsert_session(
			originator="opencode:ses_a",
			continuity_id="alma-1",
			mission_id="repo:next",
			role="task",
			affinity=[],
			last_seen_event_seq=ev["event_seq"],
		)
		report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert push == []
		assert report["handed_off"] == []
		assert delivery.pending_for_soul("alma-1", db_path=db) == []

	def test_leg_mal_formado_no_empuja(self, reg, db, push):
		_event(reg)
		report = delivery.deliver_events("alma-1", originator="sinseparador", db_path=db)
		assert push == []
		assert report["deferred"][0]["reason"] == "no_live_body"


class TestNoDuplicado:
	def test_dos_pasadas_un_solo_empuje(self, reg, db, push):
		_event(reg)
		delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		segunda = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert len(push) == 1, "el mismo evento se empujó dos veces"
		assert segunda["handed_off"] == []
		assert delivery.pending_for_soul("alma-1", db_path=db) == []

	def test_otro_entregador_no_lo_roba(self, reg, db, push):
		"""CAS (D13): un `in_flight` ajeno en curso no se puede reclamar."""
		ev = _event(reg)
		assert delivery.claim_delivery(event_id=ev["event_id"], continuity_id="alma-1", holder="otro", db_path=db) is True
		report = delivery.deliver_events("alma-1", originator="opencode:ses_a", holder="yo", db_path=db)
		assert push == []
		assert report["deferred"][0]["reason"] == "claimed_by_other"

	def test_in_flight_colgado_se_reclama(self, reg, db, push):
		"""El entregador murió: pasado el TTL el evento no queda en tierra de nadie."""
		ev = _event(reg)
		t0 = time.time()
		delivery.claim_delivery(event_id=ev["event_id"], continuity_id="alma-1", holder="muerto", db_path=db, now=t0)
		report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db, now=t0 + delivery.CLAIM_TTL_S + 1)
		assert len(push) == 1
		assert report["handed_off"][0]["event_id"] == ev["event_id"]

	def test_el_eco_al_propio_autor_no_se_empuja(self, reg, db, push):
		"""El cuerpo que publica ya sabe lo que publicó; devolvérselo es un bucle."""
		ev = _event(reg, originator="opencode:ses_a")
		report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert push == []
		assert report["skipped"][0]["reason"] == "self_authored"
		assert delivery.get_delivery(ev["event_id"], "alma-1", db_path=db)["state"] == delivery.STATE_SKIPPED
		assert delivery.pending_for_soul("alma-1", db_path=db) == [], "omitido no se reintenta"

	def test_agotados_los_intentos_deja_de_reintentarse(self, reg, db, monkeypatch):
		"""Sin bucles: `given_up` es terminal y el evento queda para el pull."""
		monkeypatch.setenv(soul_notify.ENV_DISABLE, "0")
		ev = _event(reg)
		attempts = []

		def failing(session_id, text):
			attempts.append(text)
			return False

		with patch.dict(soul_notify._TRANSPORTS, {"cli": failing}):
			for _ in range(3):
				delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
			cuarta = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert len(attempts) == delivery.MAX_PUSH_ATTEMPTS
		assert cuarta["given_up"] == [] and cuarta["handed_off"] == []
		assert delivery.pending_for_soul("alma-1", db_path=db) == []
		row = delivery.get_delivery(ev["event_id"], "alma-1", db_path=db)
		assert row["state"] == delivery.STATE_GIVEN_UP
		assert row["attempts"] == delivery.MAX_PUSH_ATTEMPTS
		assert reg.get_event(ev["event_id"]) is not None, "rendirse no borra el tablón"


class TestPoliticaDeEntrada:
	"""C3: el destinatario manda. `refuse` es terminal; `hold` difiere (pull)."""

	def test_refuse_no_se_empuja_y_es_terminal(self, reg, db, push):
		from red_pill.session import wake_policy

		ev = _event(reg)
		assert wake_policy.set_inbound("alma-1", wake_policy.INBOUND_REFUSE, db_path=db) is True
		report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert push == []
		assert report["skipped"] == [{"event_id": ev["event_id"], "reason": wake_policy.REASON_INBOUND_REFUSE}]
		row = delivery.get_delivery(ev["event_id"], "alma-1", db_path=db)
		assert row["state"] == delivery.STATE_SKIPPED
		assert delivery.pending_for_soul("alma-1", db_path=db) == [], "refuse no se reintenta"

	def test_hold_difiere_y_el_evento_sigue_pendiente(self, reg, db, push):
		from red_pill.session import wake_policy

		ev = _event(reg)
		assert wake_policy.set_inbound("alma-1", wake_policy.INBOUND_HOLD, db_path=db) is True
		report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert push == []
		assert report["deferred"] == [{"event_id": ev["event_id"], "reason": wake_policy.REASON_INBOUND_HOLD}]
		assert delivery.get_delivery(ev["event_id"], "alma-1", db_path=db) is None, "no se escribe estado al diferir"
		assert [e["event_id"] for e in delivery.pending_for_soul("alma-1", db_path=db)] == [ev["event_id"]]

	def test_accept_es_el_default_y_no_estorba(self, reg, db, push):
		from red_pill.session import wake_policy

		ev = _event(reg)
		assert wake_policy.get_inbound("alma-1", originator="opencode:ses_a", db_path=db) == wake_policy.INBOUND_ACCEPT
		report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert len(push) == 1
		assert report["handed_off"][0]["event_id"] == ev["event_id"]


class TestFallos:
	def test_transporte_que_explota_no_tumba_al_llamante(self, reg, db, monkeypatch):
		monkeypatch.setenv(soul_notify.ENV_DISABLE, "0")

		def boom(*_a):
			raise RuntimeError("transporte roto")

		_event(reg)
		with patch.dict(soul_notify._TRANSPORTS, {"cli": boom}):
			report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		# El motivo lleva ahora el porqué del transporte (`transport_refused:<detalle>`):
		# "no salió" a secas dejó al Operador sin saber qué mirar (2026-10-30).
		assert report["deferred"][0]["reason"].startswith("transport_refused")
		assert len(delivery.pending_for_soul("alma-1", db_path=db)) == 1

	def test_kill_switch_no_empuja_nada(self, reg, db, monkeypatch):
		calls = []
		monkeypatch.setenv(soul_notify.ENV_DISABLE, "1")
		_event(reg)
		with patch.dict(soul_notify._TRANSPORTS, {"cli": lambda *a: calls.append(a) or True}):
			report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert calls == []
		assert report["deferred"] == [{"event_id": "*", "reason": "kill_switch"}]

	def test_sin_continuity_no_se_busca_nada(self, db):
		assert delivery.deliver_events("", db_path=db)["handed_off"] == []
		assert delivery.pending_for_soul("", db_path=db) == []

	def test_bd_inaccesible_es_non_fatal(self, tmp_path, monkeypatch):
		"""Un fallo de BD degrada a pull: no lanza, no marca nada como entregado."""
		monkeypatch.setenv(soul_notify.ENV_DISABLE, "0")
		blocker = tmp_path / "blocker"
		blocker.write_text("no es un directorio")
		bad = str(blocker / "session.db")
		assert delivery.pending_for_soul("alma-1", db_path=bad) == []
		assert delivery.claim_delivery(event_id="e", continuity_id="a", holder="h", db_path=bad) is False
		assert delivery.set_delivery_state(event_id="e", continuity_id="a", state=delivery.STATE_HANDED_OFF, db_path=bad) is False
		assert delivery.reconcile_pulled("alma-1", until_seq=5, db_path=bad) == 0
		report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=bad)
		assert report["handed_off"] == []

	def test_estado_desconocido_no_se_escribe(self, reg, db):
		assert delivery.set_delivery_state(event_id="x", continuity_id="a", state="inventado", db_path=db) is False


class TestFiltrosDelTablon:
	def test_sealed_no_se_empuja(self, reg, db, push):
		"""Un evento sealed es privado del cuerpo que lo publicó."""
		_event(reg, originator="opencode:ses_otra", kind="intent_updated", summary="nota privada", sealed=True)
		delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert push == []

	def test_auditoria_interna_de_decisiones_no_se_empuja(self, reg, db, push):
		"""`decision_*` es auditoría de D23-SCORE, no noticia para un alma."""
		note = _event(reg, continuity="alma-9", kind="phase_done", summary="nota objetada")
		reg.open_decision(subject_event_id=note["event_id"], claim="está mal", created_by="alma-9", mission_id="repo:next")
		kinds = [e["type"] for e in delivery.pending_for_soul("alma-9", db_path=db)]
		assert kinds == ["phase_done"], f"la auditoría interna se coló en la cola de empuje: {kinds}"

	def test_nota_oculta_o_retactada_no_se_empuja(self, reg, db, push):
		ev = _event(reg, summary="nota retirada")
		with reg._connect() as conn:
			conn.execute(
				"INSERT INTO note_status (event_id, mission_id, status, updated_at, updated_by, reason)"
				" VALUES (?, ?, 'hidden', ?, 'operator', 'prueba')",
				(ev["event_id"], "repo:next", time.time()),
			)
			conn.commit()
		assert delivery.pending_for_soul("alma-1", db_path=db) == []


class TestEsquemaYDiagnostico:
	def test_ensure_schema_es_idempotente(self, db):
		delivery.ensure_schema(db)
		delivery.ensure_schema(db)
		assert delivery.pending_for_soul("alma-1", db_path=db) == []

	def test_resumen_cuenta_por_estado(self, reg, db, push):
		_event(reg, summary="uno")
		_event(reg, summary="dos")
		delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert delivery.delivery_summary("alma-1", db_path=db) == {delivery.STATE_HANDED_OFF: 2}

	def test_tabla_de_honestidad_declarada_y_veraz(self):
		"""El docstring debe decir qué arneses NO tienen inyección, no solo cuáles sí.

		Regla de la etapa: la tabla es la defensa contra el marketing. Si el código
		y la prosa discrepan, esta aserción falla antes que un humano se lo crea.
		"""
		doc = delivery.__doc__ or ""
		assert "TABLA DE HONESTIDAD" in doc
		for harness in ("opencode", "claude_code", "pi", "telegram"):
			assert harness in doc, f"el arnés {harness} no está en la tabla de honestidad"
		# Inyectan opencode (seam de AD-090) y claude_code (socket de mensajería, F6).
		assert delivery.INJECTION_POINTS == {"opencode": "cli", "claude_code": "claude_socket"}
		assert set(delivery.INJECTION_POINTS.values()) <= set(soul_notify._TRANSPORTS)

	def test_el_estado_entregado_significa_entregado_al_transporte(self, reg, db, monkeypatch):
		"""Honestidad: el seam devuelve True al lanzar, no al leerse."""
		monkeypatch.setenv(soul_notify.ENV_DISABLE, "0")
		ev = _event(reg)
		with patch.dict(soul_notify._TRANSPORTS, {"cli": lambda *a: True}):
			delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		row = delivery.get_delivery(ev["event_id"], "alma-1", db_path=db)
		assert row["reason"].startswith("handed_to_transport")


class TestWiringEnElHandshake:
	"""El punto de integración: lo que el digest anunció ya no se empuja."""

	def test_reconcile_pull_first_cierra_lo_anunciado(self, reg):
		"""Se llama con la BD por defecto del handshake: la ruta real, no un mock."""
		from pathlib import Path

		from red_pill.mcp_server import _reconcile_pull_first

		ev = _event(reg, continuity="alma-handshake")
		with patch("red_pill.core.paths.get_session_db", return_value=Path(reg.db_path)):
			_reconcile_pull_first({"continuity_id": "alma-handshake"}, ev["event_seq"])
			row = delivery.get_delivery(ev["event_id"], "alma-handshake")
		assert row is not None and row["state"] == delivery.STATE_PULLED

	def test_reconcile_pull_first_no_lanza_con_identidad_rara(self):
		from red_pill.mcp_server import _reconcile_pull_first

		_reconcile_pull_first({}, 0)
		_reconcile_pull_first({"continuity_id": None}, None)


class TestLlamanteEfimero:
	"""La CLI es un proceso corto: la entrega no puede depender de que siga viva
	(antes el hilo daemon moría con ella y el estado decía "entregado")."""

	def _args(self, **kw):
		import argparse

		base = {
			"session_cmd": "deliver",
			"continuity": "alma-1",
			"originator": "opencode:ses_a",
			"limit": 20,
			"dry_run": False,
			"summary": False,
			"json": False,
		}
		base.update(kw)
		return argparse.Namespace(**base)

	def test_la_entrega_no_hereda_la_vida_de_la_cli(self, reg, monkeypatch, capsys):
		"""El hijo `opencode run` arranca en su propia sesión y sin timeout: la CLI
		sale enseguida y el turno del receptor sigue vivo. Queda rastro legible."""
		from pathlib import Path

		from red_pill.cli_services import handle_session
		from red_pill.core import soul_notify

		monkeypatch.setenv(soul_notify.ENV_DISABLE, "0")
		monkeypatch.setenv("REDPILL_OPERATOR", "1")
		ev = _event(reg)
		launched = []

		class FakeProc:
			def __init__(self, cmd, **kw):
				launched.append((cmd, kw))

			def wait(self):
				return 0

		with patch("red_pill.core.paths.get_session_db", return_value=Path(reg.db_path)), patch(
			"red_pill.core.paths.find_harness_binary", return_value="/usr/bin/true"
		), patch("red_pill.core.soul_notify.subprocess.Popen", FakeProc):
			handle_session(self._args())
		out = capsys.readouterr().out
		cmd, kw = launched[0]
		assert cmd[:3] == ["/usr/bin/true", "run", "--session"]
		assert kw.get("start_new_session") is True, "el hijo debe sobrevivir al llamante"
		assert "timeout" not in kw, "nadie corta el turno del receptor"
		assert ev["event_id"][:8] not in out  # el resumen no vuelca ids largos
		assert "al_transporte=1" in out
		row = delivery.get_delivery(ev["event_id"], "alma-1", db_path=reg.db_path)
		assert row["state"] == delivery.STATE_HANDED_OFF
		trace = row["reason"].split("rastro=", 1)[1]
		assert Path(trace).read_text(encoding="utf-8").startswith("# soul-notify cli → opencode:ses_a")

	def test_la_cli_sin_operador_no_empuja(self, reg, monkeypatch, capsys):
		from pathlib import Path

		from red_pill.cli_services import handle_session
		from red_pill.core import soul_notify

		monkeypatch.setenv(soul_notify.ENV_DISABLE, "0")
		monkeypatch.delenv("REDPILL_OPERATOR", raising=False)
		_event(reg)
		calls = []
		with patch("red_pill.core.paths.get_session_db", return_value=Path(reg.db_path)), patch.dict(
			soul_notify._TRANSPORTS, {"cli": lambda *a: calls.append(a) or True}
		):
			handle_session(self._args())
		assert calls == []
		assert "solo Operador" in capsys.readouterr().out
		assert len(delivery.pending_for_soul("alma-1", db_path=reg.db_path)) == 1

	def test_dry_run_lista_sin_empujar(self, reg, monkeypatch, capsys):
		from pathlib import Path

		from red_pill.cli_services import handle_session
		from red_pill.core import soul_notify

		monkeypatch.setenv(soul_notify.ENV_DISABLE, "0")
		monkeypatch.delenv("REDPILL_OPERATOR", raising=False)
		_event(reg, summary="pendiente de ver")
		calls = []
		with patch("red_pill.core.paths.get_session_db", return_value=Path(reg.db_path)), patch.dict(
			soul_notify._TRANSPORTS, {"cli": lambda *a: calls.append(a) or True}
		):
			handle_session(self._args(dry_run=True))
		assert calls == []
		out = capsys.readouterr().out
		assert "PENDIENTES DE ENTREGA" in out and "pendiente de ver" in out


class TestMatrizEnLaEntrega:
	"""D-07 aplicada donde de verdad importa: el momento de empujar (no solo al entrar).

	`next` ya resolvía emisor y destinatario contra el registro (`_wake_verdict`),
	pero no había ni un test que lo fijara: esta clase es la red que impide que el
	fail-closed por identidad desconocida se pierda en un refactor.
	"""

	def _config(self, monkeypatch, policy: str) -> None:
		from types import SimpleNamespace

		import red_pill.config as cfg

		monkeypatch.setattr(cfg, "get_config", lambda: SimpleNamespace(WAKE_POLICY=policy))

	def test_par_de_otra_mision_no_se_despierta(self, reg, db, push, monkeypatch):
		self._config(monkeypatch, "orchestrator:chain,*:same_mission")
		reg.upsert_session(originator="dag:otra", continuity_id="job-2", mission_id="mission:otra", role="orchestrator")
		_event(reg, originator="dag:otra")
		report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert report["handed_off"] == []
		assert [d["reason"] for d in report["deferred"]] == ["no_rule"]
		# Nada se marca: el evento sigue pendiente y el pull del siguiente turno lo ve.
		assert len(delivery.pending_for_soul("alma-1", db_path=db)) == 1

	def test_orquestrador_despierta_a_su_cadena(self, reg, db, push, monkeypatch):
		self._config(monkeypatch, "orchestrator:chain")
		reg.upsert_session(originator="dag:job-9", continuity_id="job-9", mission_id="repo:next", role="orchestrator")
		_event(reg, originator="dag:job-9")
		report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert len(report["handed_off"]) == 1
		assert len(push) == 1

	def test_emisor_sin_registro_espera_al_pull(self, reg, db, push):
		_event(reg, originator="dag:fantasma")
		report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert report["handed_off"] == []
		assert report["deferred"][0]["reason"] == "no_rule"
		assert len(delivery.pending_for_soul("alma-1", db_path=db)) == 1

	def test_politica_invalida_no_despierta_y_lo_dice(self, reg, db, push, monkeypatch):
		self._config(monkeypatch, "orchestrator:inventada")
		_event(reg)
		report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert report["handed_off"] == []
		assert report["deferred"][0]["reason"].startswith("rules_invalid")

	def test_any_del_operador_abre_el_circulo_sin_tocar_codigo(self, reg, db, push, monkeypatch):
		self._config(monkeypatch, "*:any")
		_event(reg, originator="dag:desconocido")
		report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert len(report["handed_off"]) == 1

	def test_el_refuse_del_destinatario_gana_a_la_matriz(self, reg, db, push, monkeypatch):
		from red_pill.session import wake_policy

		self._config(monkeypatch, "*:any")
		wake_policy.set_inbound("alma-1", state=wake_policy.INBOUND_REFUSE, originator="opencode:ses_a", db_path=db)
		_event(reg, originator="dag:job-9")
		report = delivery.deliver_events("alma-1", originator="opencode:ses_a", db_path=db)
		assert report["handed_off"] == []
		assert [s["reason"] for s in report["skipped"]] == [wake_policy.REASON_INBOUND_REFUSE]
		assert delivery.pending_for_soul("alma-1", db_path=db) == []
