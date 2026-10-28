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
