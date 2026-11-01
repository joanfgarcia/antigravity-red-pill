"""D-BRIDGE: resolución del cuerpo (session_id) por correlación de cwd.

El bridge global por arnés atribuye el cuerpo de la ÚLTIMA pestaña que escribió.
Con varias pestañas vivas eso es un alma con el cuerpo de otra. La correlación
cwd-de-instancia → bridge per-sesión (y `opencode.db` como desempate) resuelve
el cuerpo correcto sin depender del último escritor.

Se prueba la unidad (`red_pill.core.bridge`) y la integración con el proxy
(`identity_payload`), que es quien tiene el cwd de la instancia.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from red_pill.core import bridge
from red_pill.core.session_liveness import SessionSignal


def _write_session_bridge(state: Path, sid: str, workdir: str, updated_at: float | None = None):
	dir_ = state / "sessions" / "bridge"
	dir_.mkdir(parents=True, exist_ok=True)
	dir_.joinpath(f"opencode__{sid}.json").write_text(
		json.dumps(
			{
				"provider": "opencode",
				"session_id": sid,
				"workdir": workdir,
				"updated_at": time.time() if updated_at is None else updated_at,
			}
		)
	)


def _live(sids: list[str]) -> list[SessionSignal]:
	now = time.time()
	return [SessionSignal(provider="opencode", session_id=s, start_mtime=now - 5, end_mtime=None) for s in sids]


def _patches(state: Path, live: list[SessionSignal], dirs: dict[str, str]):
	"""state=STATE_DIR; live=señales; dirs={sid: directory de opencode.db}."""
	return [
		patch("red_pill.core.bridge.get_state_dir", return_value=state),
		patch("red_pill.core.session_liveness.list_sessions", lambda: live),
		patch("red_pill.core.bridge._session_directory", lambda sid: dirs.get(sid)),
		patch("red_pill.core.bridge._opencode_db_path", return_value=state / "nope.db"),
	]


class _Ctx:
	def __init__(self, patches):
		self.patches = patches

	def __enter__(self):
		for p in self.patches:
			p.start()
		return self

	def __exit__(self, *exc):
		for p in self.patches:
			p.stop()
		return False


class TestResolveBodyByCwd:
	def test_bridge_propio_por_cwd_resuelve(self, tmp_path):
		"""Capa 1: el bridge per-sesión con workdir == cwd gana, sin opencode.db."""
		state = tmp_path / "state"
		_write_session_bridge(state, "s1", "/ws/a")
		with _Ctx(_patches(state, _live(["s1"]), {})):
			entry = bridge.resolve_body_by_cwd("opencode", "/ws/a")
		assert entry is not None
		assert entry["session_id"] == "s1"
		assert entry["workdir"] == "/ws/a"

	def test_sesion_viva_aun_no_en_db(self, tmp_path):
		"""El caso real: la sesión del turno en curso no está en opencode.db.

		El bridge per-sesión sí existe (lo escribió el hook) → se resuelve igual.
		"""
		state = tmp_path / "state"
		_write_session_bridge(state, "s_live", "/ws/a")
		with _Ctx(_patches(state, _live(["s_live"]), {})):
			entry = bridge.resolve_body_by_cwd("opencode", "/ws/a")
		assert entry is not None and entry["session_id"] == "s_live"

	def test_dos_pestanas_mismo_workspace_una_viva(self, tmp_path):
		"""Dos bridges en el mismo cwd, solo una sesión viva → la viva gana."""
		state = tmp_path / "state"
		_write_session_bridge(state, "s_muerta", "/ws/a")
		_write_session_bridge(state, "s_viva", "/ws/a")
		with _Ctx(_patches(state, _live(["s_viva"]), {})):
			entry = bridge.resolve_body_by_cwd("opencode", "/ws/a")
		assert entry is not None and entry["session_id"] == "s_viva"

	def test_bridge_rancio_no_gana_a_la_sesion_viva(self, tmp_path):
		"""Regresión auditoría 2026-10-28 (HIGH): un bridge RANCIO de una pestaña
		cerrada en el mismo cwd NO puede ganar al bridge fresco de la sesión viva.

		Antes la capa 1 devolvía un bridge por cwd sin mirar latido ni frescura,
		así que una pestaña cerrada podía atribuirse el cuerpo — el mismo bug
		D-BRIDGE, reintroducido por bridges rancios.
		"""
		state = tmp_path / "state"
		# Bridge rancio de una pestaña CERRADA (mismo cwd) + bridge fresco de la VIVA.
		_write_session_bridge(state, "otra_vieja", "/ws/a", updated_at=time.time() - 99999)
		_write_session_bridge(state, "mia", "/ws/a")  # fresco (now)
		with _Ctx(_patches(state, _live(["mia"]), {})):
			entry = bridge.resolve_body_by_cwd("opencode", "/ws/a")
		assert entry is not None and entry["session_id"] == "mia", "el bridge rancio no debe ganar al fresco de la viva"

	def test_solo_bridge_rancio_degrada(self, tmp_path):
		"""Si el único bridge por cwd es rancio, NO se devuelve (degrada a global).

		El proxy caerá al fichero global; nunca se atribuye el cuerpo de una
		pestaña muerta por un bridge viejo.
		"""
		state = tmp_path / "state"
		_write_session_bridge(state, "otra_vieja", "/ws/a", updated_at=time.time() - 99999)
		with _Ctx(_patches(state, _live(["mia"]), {})):
			assert bridge.resolve_body_by_cwd("opencode", "/ws/a") is None

	def test_dos_pestanas_mismo_workspace_ambas_vivas_degrada(self, tmp_path):
		"""Ambigüedad real (dos pestañas vivas, mismo cwd): None → global."""
		state = tmp_path / "state"
		_write_session_bridge(state, "s1", "/ws/a")
		_write_session_bridge(state, "s2", "/ws/a")
		with _Ctx(_patches(state, _live(["s1", "s2"]), {})):
			assert bridge.resolve_body_by_cwd("opencode", "/ws/a") is None

	def test_desempate_por_opencode_db(self, tmp_path):
		"""Capa 2: sin bridge per-sesión, opencode.db decide entre las vivas."""
		state = tmp_path / "state"
		with _Ctx(_patches(state, _live(["s1", "s2"]), {"s1": "/ws/a", "s2": "/ws/b"})):
			entry = bridge.resolve_body_by_cwd("opencode", "/ws/a")
		assert entry is not None and entry["session_id"] == "s1"

	def test_cwd_sin_candidatas_degrada(self, tmp_path):
		state = tmp_path / "state"
		_write_session_bridge(state, "s1", "/ws/a")
		with _Ctx(_patches(state, _live(["s1"]), {})):
			assert bridge.resolve_body_by_cwd("opencode", "/ws/otro") is None

	def test_sin_nada_degrada(self, tmp_path):
		state = tmp_path / "state"
		with _Ctx(_patches(state, [], {})):
			assert bridge.resolve_body_by_cwd("opencode", "/ws/a") is None

	def test_symlink_casa_con_ruta_real(self, tmp_path):
		"""`_norm` resuelve symlinks: el mismo workspace por enlace o ruta real casa."""
		real = tmp_path / "real"
		real.mkdir()
		link = tmp_path / "link"
		link.symlink_to(real)
		assert bridge._norm(str(link)) == bridge._norm(str(real))

	def test_sanitizer_paridad_con_js(self):
		"""`_safe` debe producir el nombre que escribe el JS (`[/:]`→`_`, `__`→`_`)."""
		# Equivale a: String(x).replace(/[/:]/g,"_").replace(/__/g,"_")
		assert bridge._safe("ses:a/b") == "ses_a_b"
		assert bridge._safe("a__b") == "a_b"


class TestProxyIdentityPayload:
	def test_proxy_usa_correlacion_antes_que_el_global(self, tmp_path):
		"""El proxy resuelve su cuerpo por cwd, no por el último escritor global."""
		from red_pill import mcp_proxy

		state = tmp_path / "state"
		state.mkdir(parents=True, exist_ok=True)
		# Global apunta a OTRA pestaña (último escritor): el bug.
		(state / "opencode_session.json").write_text(
			json.dumps({"provider": "opencode", "session_id": "otra", "workdir": "/ws/otra", "updated_at": 10**12})
		)
		_write_session_bridge(state, "mia", "/ws/mia")
		with _Ctx(_patches(state, _live(["mia"]), {})), patch("red_pill.mcp_proxy.state_dir", return_value=state), patch.object(
			mcp_proxy, "_instance_cwd", return_value="/ws/mia"
		):
			payload = mcp_proxy.identity_payload("opencode")
		assert payload["originator"] == "opencode:mia", "el proxy debe resolver SU cuerpo, no el global"
		assert payload["workdir"] == "/ws/mia"


class TestAmbiguedadDeIdentidad:
	"""Regresión 2026-10-28: dos sesiones vivas en el MISMO cwd.

	La correlación no puede decidir y el proxy caía al fichero global ("la última
	que escribió"). Resultado real: un `job_submit` se atribuyó al alma de otra
	sesión y el aviso de fin de job se entregó a quien no era.

	Regla nueva: *atribuir a un alma ajena es peor que no atribuir*.
	- AMBIGUO  → el proxy NO usa el global (se queda sin cuerpo).
	- DESCONOCIDO (0 candidatas) → sí lo usa: es la única información que hay.
	"""

	def _dos_vivas_mismo_cwd(self, state):
		_write_session_bridge(state, "s1", "/ws/a")
		_write_session_bridge(state, "s2", "/ws/a")
		return _live(["s1", "s2"])

	def test_dos_vivas_mismo_cwd_es_ambiguo(self, tmp_path):
		from red_pill.core.bridge import REASON_AMBIGUOUS, resolve_body

		state = tmp_path / "state"
		live = self._dos_vivas_mismo_cwd(state)
		with _Ctx(_patches(state, live, {})):
			entry, reason = resolve_body("opencode", "/ws/a")
		assert entry is None
		assert reason == REASON_AMBIGUOUS

	def test_sin_candidatas_es_desconocido_no_ambiguo(self, tmp_path):
		from red_pill.core.bridge import REASON_UNKNOWN, resolve_body

		state = tmp_path / "state"
		with _Ctx(_patches(state, [], {})):
			entry, reason = resolve_body("opencode", "/ws/a")
		assert entry is None
		assert reason == REASON_UNKNOWN, "sin pistas se puede degradar al global"

	def test_una_sola_viva_resuelve(self, tmp_path):
		from red_pill.core.bridge import REASON_RESOLVED, resolve_body

		state = tmp_path / "state"
		_write_session_bridge(state, "s1", "/ws/a")
		with _Ctx(_patches(state, _live(["s1"]), {})):
			entry, reason = resolve_body("opencode", "/ws/a")
		assert reason == REASON_RESOLVED
		assert entry["session_id"] == "s1"

	def test_el_proxy_no_usa_el_global_si_hay_ambiguedad(self, tmp_path):
		"""El escenario exacto del incidente: global apuntando a OTRA alma."""
		from red_pill import mcp_proxy

		state = tmp_path / "state"
		state.mkdir(parents=True, exist_ok=True)
		(state / "opencode_session.json").write_text(
			json.dumps({"provider": "opencode", "session_id": "otra", "workdir": "/ws/a", "updated_at": 10**12})
		)
		live = self._dos_vivas_mismo_cwd(state)
		with _Ctx(_patches(state, live, {})), patch("red_pill.mcp_proxy.state_dir", return_value=state), patch.object(
			mcp_proxy, "_instance_cwd", return_value="/ws/a"
		):
			payload = mcp_proxy.identity_payload("opencode")
		assert payload["originator"] == "", (
			"con identidad ambigua NO se puede tomar el global: atribuiría el trabajo a un alma ajena"
		)

	def test_el_proxy_si_usa_el_global_sin_pistas(self, tmp_path):
		"""Contraprueba: sin candidatas, el global sigue siendo la degradación."""
		from red_pill import mcp_proxy

		state = tmp_path / "state"
		state.mkdir(parents=True, exist_ok=True)
		(state / "opencode_session.json").write_text(
			json.dumps({"provider": "opencode", "session_id": "unica", "workdir": "/ws/a", "updated_at": 10**12})
		)
		with _Ctx(_patches(state, [], {})), patch("red_pill.mcp_proxy.state_dir", return_value=state), patch.object(
			mcp_proxy, "_instance_cwd", return_value="/ws/a"
		):
			payload = mcp_proxy.identity_payload("opencode")
		assert payload["originator"] == "opencode:unica"
