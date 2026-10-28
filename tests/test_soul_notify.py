"""AD-090 — aviso de fin de job al alma (MVP TEMPORAL).

Contrato: tras depositar el reporte en el MinionInbox, el runner avisa al alma
que lanzó el job. Sin esto, el reporte solo se ve si alguien mira el buzón
("nadie lo abre"), y la única salida para una tarea larga era un `nohup &` que
ni tiene alma ni puede avisar.

Se prueba: resolución alma→cuerpo vivo, gating (sin cuerpo vivo no hay push),
el seam de transporte (repunte a neon-link = cambiar el default), el apagado
por env, y que la entrega NO bloquea.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from red_pill.core import soul_notify
from red_pill.core.session_liveness import SessionSignal
from red_pill.session.store import SessionRegistry


def _seed_leg(tmp_path, originator: str, continuity: str, *, active: bool):
	"""Registra un leg y devuelve los patches de entorno."""
	reg = SessionRegistry(db_path=str(tmp_path / "session.db"))
	reg.upsert_session(
		originator=originator,
		continuity_id=continuity,
		mission_id="repo:test",
		role="task",
		affinity=["mission:repo:test"],
	)
	sig = SessionSignal(
		provider=originator.split(":")[0],
		session_id=originator.split(":", 1)[1],
		start_mtime=(__import__("time").time() - 2) if active else 1.0,
		end_mtime=None if active else 2.0,
	)
	return reg, sig


class TestResolveLiveLeg:
	def test_alma_con_cuerpo_vivo(self, tmp_path):
		reg, sig = _seed_leg(tmp_path, "opencode:ses_a", "alma-1", active=True)
		with patch("red_pill.session.store.SessionRegistry", return_value=reg), patch(
			"red_pill.core.session_liveness.list_sessions", return_value=[sig]
		):
			assert soul_notify.resolve_live_leg("alma-1") == "opencode:ses_a"

	def test_alma_sin_latido_pero_fresca_se_despierta(self, tmp_path):
		"""Cambio de diseño 2026-10-28: idle NO es motivo para no avisar.

		Antes se exigía `is_active()`; pero un job terminado entre turnos es el
		caso normal, y `opencode run --session` despierta la sesión. Se prefiere
		una activa, y si no hay, se despierta la que tiene `ttl_state='active'`.
		"""
		reg, sig = _seed_leg(tmp_path, "opencode:ses_a", "alma-1", active=False)
		with patch("red_pill.session.store.SessionRegistry", return_value=reg), patch(
			"red_pill.core.session_liveness.list_sessions", return_value=[sig]
		):
			assert soul_notify.resolve_live_leg("alma-1") == "opencode:ses_a"

	def test_alma_desconocida(self, tmp_path):
		reg, _ = _seed_leg(tmp_path, "opencode:ses_a", "alma-1", active=True)
		with patch("red_pill.session.store.SessionRegistry", return_value=reg), patch(
			"red_pill.core.session_liveness.list_sessions", return_value=[]
		):
			assert soul_notify.resolve_live_leg("alma-inexistente") is None

	def test_sin_continuity_no_busca(self):
		assert soul_notify.resolve_live_leg("") is None


class TestNotifySoul:
	def test_push_cuando_hay_cuerpo_vivo(self):
		delivered = []

		def fake_cli(session_id, text):
			delivered.append((session_id, text))
			return True

		with patch.dict(soul_notify._TRANSPORTS, {"cli": fake_cli}), patch.object(
			soul_notify, "_resolve_transport", return_value="cli"
		), patch.dict(os.environ, {soul_notify.ENV_DISABLE: "0"}):
			ok = soul_notify.notify_soul("alma-1", "hola", originator="opencode:ses_a")
		assert ok is True
		assert delivered == [("ses_a", "hola")]

	def test_sin_cuerpo_vivo_no_entrega(self):
		calls = []
		with patch.object(soul_notify, "resolve_live_leg", return_value=None), patch.dict(
			soul_notify._TRANSPORTS, {"cli": lambda *a: calls.append(a) or True}
		):
			assert soul_notify.notify_soul("alma-1", "hola") is False
		assert calls == [], "sin cuerpo vivo no se debe intentar entregar"

	def test_disable_por_env(self):
		calls = []
		with patch.dict(soul_notify._TRANSPORTS, {"cli": lambda *a: calls.append(a) or True}), patch.dict(
			os.environ, {soul_notify.ENV_DISABLE: "1"}
		):
			assert soul_notify.notify_soul("alma-1", "hola", originator="opencode:ses_a") is False
		assert calls == []

	def test_transporte_que_falla_no_lanza(self):
		def boom(*_a):
			raise RuntimeError("transporte roto")

		with patch.dict(soul_notify._TRANSPORTS, {"cli": boom}), patch.object(
			soul_notify, "_resolve_transport", return_value="cli"
		):
			assert soul_notify.notify_soul("alma-1", "x", originator="opencode:ses_a") is False


class TestTransportSeam:
	def test_default_es_cli_temporal(self):
		"""El default es el transporte TEMPORAL; el repunte a neon-link es cambiarlo."""
		with patch.dict(os.environ, {soul_notify.ENV_TRANSPORT: ""}):
			assert soul_notify._resolve_transport() == "cli"

	def test_override_a_neon_link(self):
		with patch.dict(os.environ, {soul_notify.ENV_TRANSPORT: "neon_link"}):
			assert soul_notify._resolve_transport() == "neon_link"

	def test_neon_link_placeholder_no_entrega_aun(self):
		"""Hasta que neon-link mire hacia dentro, el canal no entrega (honesto)."""
		assert soul_notify._deliver_neon_link("ses_a", "x") is False

	def test_transporte_inexistente_no_rompe(self):
		with patch.dict(os.environ, {soul_notify.ENV_TRANSPORT: "inventado"}):
			assert soul_notify._resolve_transport() == "cli"


class TestNoticeText:
	def test_el_aviso_es_dato_no_orden(self):
		"""D-09: el aviso no debe pedir nada al receptor."""
		text = soul_notify.build_job_notice("suite", "script_job", "success", "todo verde", "/r.json")
		assert "DATO, no orden" in text
		assert "No requiere respuesta" in text
		assert "/r.json" in text


class TestReportJobIntegration:
	"""`_report_job` avisa DESPUÉS de dejar el reporte en el MinionInbox."""

	def _task(self, continuity="alma-1", originator="opencode:ses_a"):
		return {
			"payload": {"title": "suite completa", "originator": originator},
			"source": "script_job",
			"continuity_id": continuity,
		}

	def test_report_job_avisa_al_alma(self, tmp_path):
		from red_pill.core import queue_worker

		calls = {}
		with patch("red_pill.core.inbox.MinionInbox") as inbox_cls, patch(
			"red_pill.jobs.artifacts.write_job_result", return_value={"paths": {}}
		), patch("red_pill.core.soul_notify.notify_soul", side_effect=lambda *a, **k: calls.setdefault("args", a) or True):
			inbox_cls.return_value.drop_report.return_value = None
			queue_worker._report_job("job12345", self._task(), "success", "todo verde")
		# El primer argumento es el alma; el segundo, el texto del aviso.
		assert calls.get("args"), "no se avisó al alma tras el reporte"
		assert calls["args"][0] == "alma-1"
		assert "todo verde" in calls["args"][1]

	def test_job_sin_alma_no_avisa(self):
		from red_pill.core import queue_worker

		calls = []
		with patch("red_pill.core.inbox.MinionInbox"), patch(
			"red_pill.jobs.artifacts.write_job_result", return_value={"paths": {}}
		), patch("red_pill.core.soul_notify.notify_soul", side_effect=lambda *a, **k: calls.append(a) or True):
			queue_worker._report_job("job12345", self._task(continuity=""), "success", "ok")
		assert calls == [], "un job sin alma no puede avisar a nadie (D-02)"

	def test_reporte_sigue_yendo_al_inbox_aunque_falle_el_aviso(self):
		"""El aviso es aditivo: si falla, el pull del inbox sigue funcionando."""
		from red_pill.core import queue_worker

		with patch("red_pill.core.inbox.MinionInbox") as inbox_cls, patch(
			"red_pill.jobs.artifacts.write_job_result", return_value={"paths": {}}
		), patch("red_pill.core.soul_notify.notify_soul", side_effect=RuntimeError("boom")):
			queue_worker._report_job("job12345", self._task(), "failed", "explotó")
		assert inbox_cls.return_value.drop_report.called, "el reporte debe llegar al inbox aunque el aviso falle"


class TestSafetyNet:
	def test_la_suite_no_lanza_procesos_reales(self, tmp_path):
		"""conftest desactiva el aviso: ni con un leg vivo se lanza `opencode run`."""
		import subprocess as _sp

		reg, sig = _seed_leg(tmp_path, "opencode:ses_a", "alma-1", active=True)
		spawned = []
		with patch("red_pill.session.store.SessionRegistry", return_value=reg), patch(
			"red_pill.core.session_liveness.list_sessions", return_value=[sig]
		), patch("red_pill.core.soul_notify.subprocess.run", side_effect=lambda *a, **k: spawned.append(a)):
			# El fixture autouse ya puso REDPILL_SOUL_NOTIFY_DISABLE=1.
			assert soul_notify.notify_soul("alma-1", "x") is False
		assert spawned == [], "la suite no debe lanzar entregas reales"
		assert _sp is not None


class TestIdleSeDespierta:
	"""Regresión 2026-10-28: un alma IDLE debe poder despertarse.

	El primer MVP exigía `is_active()`; el job terminó a las 12:34 con el turno
	cerrado a las 12:31 → el aviso nunca llegó. `opencode run --session`
	DESPIERTA, así que exigir turno en vuelo era ponerse una puerta a sí misma.
	"""

	def _leg(self, tmp_path, updated_at):

		reg = SessionRegistry(db_path=str(tmp_path / "s.db"))
		reg.upsert_session(
			originator="opencode:ses_idle",
			continuity_id="alma-idle",
			mission_id="repo:t",
			role="task",
			affinity=["mission:repo:t"],
		)
		# El upsert real sella `updated_at`; lo forzamos para simular antigüedad.
		with reg._connect() as conn:
			conn.execute("UPDATE session_registry SET updated_at = ? WHERE originator = ?", (updated_at, "opencode:ses_idle"))
			conn.commit()
		return reg

	def test_alma_idle_y_fresca_se_despierta(self, tmp_path):
		import time as _t

		reg = self._leg(tmp_path, _t.time() - 600)  # 10 min: idle pero fresca
		with patch("red_pill.session.store.SessionRegistry", return_value=reg), patch(
			"red_pill.core.session_liveness.list_sessions", return_value=[]
		):
			assert soul_notify.resolve_live_leg("alma-idle") == "opencode:ses_idle"

	def test_leg_viejo_pero_activo_se_despierta(self, tmp_path):
		"""La EDAD no gobierna el aviso: un leg de hace 48 h con ttl_state=active
		sigue siendo el cuerpo vigente del alma y se despierta.

		Caso de uso que lo motivó: pausar un DAG para entrenar BIT y retomarlo dos
		días después. Un TTL por horas castigaba justo ese uso (decisión del
		Operador, 2026-10-28). La alcanzabilidad la decide la PRESENCIA
		(`ttl_state`), no el tiempo.
		"""
		import time as _t

		reg = self._leg(tmp_path, _t.time() - 48 * 3600)  # 48 h de antigüedad
		with patch("red_pill.session.store.SessionRegistry", return_value=reg), patch(
			"red_pill.core.session_liveness.list_sessions", return_value=[]
		):
			assert soul_notify.resolve_live_leg("alma-idle") == "opencode:ses_idle"

	def test_leg_expirado_no_se_despierta(self, tmp_path):
		"""`ttl_state=expired` = el alma migró de cuerpo: no se despierta el viejo."""
		import time as _t

		reg = self._leg(tmp_path, _t.time() - 600)
		with reg._connect() as conn:
			conn.execute("UPDATE session_registry SET ttl_state='expired' WHERE originator='opencode:ses_idle'")
			conn.commit()
		with patch("red_pill.session.store.SessionRegistry", return_value=reg), patch(
			"red_pill.core.session_liveness.list_sessions", return_value=[]
		):
			assert soul_notify.resolve_live_leg("alma-idle") is None

	def test_activo_gana_a_idle(self, tmp_path):
		import time as _t

		reg = SessionRegistry(db_path=str(tmp_path / "s2.db"))
		for orig in ("opencode:ses_viejo", "opencode:ses_activo"):
			reg.upsert_session(
				originator=orig, continuity_id="alma-2", mission_id="repo:t", role="task", affinity=["mission:repo:t"]
			)
		with reg._connect() as conn:
			conn.execute(
				"UPDATE session_registry SET updated_at = ? WHERE originator = 'opencode:ses_viejo'", (_t.time() - 60,)
			)
			conn.commit()
		sig = SessionSignal(provider="opencode", session_id="ses_activo", start_mtime=_t.time() - 2, end_mtime=None)
		with patch("red_pill.session.store.SessionRegistry", return_value=reg), patch(
			"red_pill.core.session_liveness.list_sessions", return_value=[sig]
		):
			assert soul_notify.resolve_live_leg("alma-2") == "opencode:ses_activo"


class TestWarningNoDespierta:
	def test_warning_solo_queda_en_el_inbox(self):
		"""Un reintento no es un desenlace: no debe interrumpir a nadie."""
		from red_pill.core import queue_worker

		calls = []
		task = {"payload": {"title": "t"}, "source": "script_job", "continuity_id": "alma-1"}
		with patch("red_pill.core.inbox.MinionInbox"), patch(
			"red_pill.jobs.artifacts.write_job_result", return_value={"paths": {}}
		), patch("red_pill.core.soul_notify.notify_soul", side_effect=lambda *a, **k: calls.append(a) or True):
			queue_worker._report_job("job12345", task, "warning", "reintento con cota duplicada")
		assert calls == [], "un warning no debe despertar al alma"

	def test_terminal_si_despierta(self):
		from red_pill.core import queue_worker

		for st in ("success", "failed", "killed"):
			calls = []
			task = {"payload": {"title": "t"}, "source": "script_job", "continuity_id": "alma-1"}
			with patch("red_pill.core.inbox.MinionInbox"), patch(
				"red_pill.jobs.artifacts.write_job_result", return_value={"paths": {}}
			), patch("red_pill.core.soul_notify.notify_soul", side_effect=lambda *a, **k: calls.append(a) or True):
				queue_worker._report_job("job12345", task, st, "fin")
			assert calls, f"el estado terminal {st} debe despertar al alma"


class TestLegNoEntregable:
	"""Regresión 2026-10-28 (job e328f02f): el aviso se perdió porque se pasó el
	leg del JOB (`dag:<uuid>`) como si fuera el cuerpo del alma.

	Síntoma real en el log del runner:
	[soul-notify] entrega falló (rc=1): Error: Expected a string starting with "ses"

	El dag_job escribe su propio `leg_originator` en el checkpoint y
	`job_identity` lo devuelve como `originator`; pasarlo a `opencode run
	--session` revienta. La dirección es el ALMA: hay que resolver el cuerpo.
	"""

	def test_leg_de_job_no_se_usa_como_cuerpo(self):
		"""`dag:<uuid>` no es entregable: se resuelve por alma."""
		entregas = []
		with patch.object(soul_notify, "resolve_live_leg", return_value="opencode:ses_real") as resolver, patch.dict(
			soul_notify._TRANSPORTS, {"cli": lambda sid, txt: entregas.append(sid) or True}
		), patch.object(soul_notify, "_resolve_transport", return_value="cli"), patch.dict(
			os.environ, {soul_notify.ENV_DISABLE: "0"}
		):
			ok = soul_notify.notify_soul("alma-1", "hola", originator="dag:e328f02f-e11d-40d0")
		assert ok is True
		assert entregas == ["ses_real"], "debía entregar al cuerpo del arnés, no al leg del job"
		assert resolver.called, "con un leg no entregable hay que resolver por alma"

	def test_leg_de_arnes_si_se_usa(self):
		"""Contraprueba: un cuerpo opencode explícito se respeta (sin resolver)."""
		entregas = []
		with patch.object(soul_notify, "resolve_live_leg") as resolver, patch.dict(
			soul_notify._TRANSPORTS, {"cli": lambda sid, txt: entregas.append(sid) or True}
		), patch.object(soul_notify, "_resolve_transport", return_value="cli"), patch.dict(
			os.environ, {soul_notify.ENV_DISABLE: "0"}
		):
			ok = soul_notify.notify_soul("alma-1", "hola", originator="opencode:ses_directa")
		assert ok is True
		assert entregas == ["ses_directa"]
		assert not resolver.called

	def test_sin_cuerpo_entregable_no_entrega(self):
		"""Ni leg de job ni alma resoluble → pudre en el inbox (pull), sin error."""
		entregas = []
		with patch.object(soul_notify, "resolve_live_leg", return_value=None), patch.dict(
			soul_notify._TRANSPORTS, {"cli": lambda sid, txt: entregas.append(sid) or True}
		), patch.object(soul_notify, "_resolve_transport", return_value="cli"), patch.dict(
			os.environ, {soul_notify.ENV_DISABLE: "0"}
		):
			ok = soul_notify.notify_soul("alma-1", "hola", originator="job:abc")
		assert ok is False
		assert entregas == []

	def test_tabla_de_entregabilidad_por_transporte(self):
		assert soul_notify._is_deliverable_leg("opencode:ses_x", "cli")
		assert not soul_notify._is_deliverable_leg("dag:uuid", "cli")
		assert not soul_notify._is_deliverable_leg("job:abc", "cli")
		assert not soul_notify._is_deliverable_leg("claude_code:c1", "cli"), "el CLI solo habla opencode"
		assert soul_notify._is_deliverable_leg("claude_code:c1", "neon_link")
		assert not soul_notify._is_deliverable_leg("", "cli")
		assert not soul_notify._is_deliverable_leg("opencode", "cli"), "sin id no hay cuerpo"
