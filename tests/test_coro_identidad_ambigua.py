"""Identidad del coro con gemelas en el mismo branch (incidente 2026-11-14).

Tres sesiones de opencode trabajando en el MISMO workspace y la misma rama. El
proxy MCP es uno para toda la app, así que la correlación por cwd no puede decir
qué pestaña hace cada llamada. El backend caía entonces al bridge GLOBAL ("el
último que escribió") y atribuía el turno a otra alma. Resultado real:

- el `post` de una hermana quedó firmado por la OTRA;
- el `send park` a la hermana se rechazó con «te estarías escribiendo a ti misma».

Contrato que fijan estos tests:

1. Con 2+ sesiones vivas en el cwd, la correlación es AMBIGUA: ni el bridge
   per-sesión ni `opencode.db` "desempatan" una pestaña (el `directory` es el
   workspace, no la sesión).
2. Con el proxy delante, el backend NO cae al bridge global.
3. El cuerpo se recupera de forma determinista: el diario del turno
   (`external_turns/current`) casa el `user_prompt` con UNA sesión viva.
4. Si no hay match, se acepta `caller_leg` (el `leg=` del tag `<session …/>`)
   SOLO verificado contra el registro: fila viva, latido reciente, mismo
   workspace.
5. Sin cuerpo verificado, el coro pide `caller_leg` en vez de atribuir a ciegas.
"""

from __future__ import annotations

import json
import sqlite3
import time
from unittest.mock import patch

import pytest

import red_pill.mcp_server as srv
from red_pill.core import bridge
from red_pill.core.session_liveness import SessionSignal
from red_pill.session.store import SessionRegistry

WS = "/ws/compartido"
LEG_A = "opencode:ses_gemela_a"
LEG_B = "opencode:ses_gemela_b"
SOUL_A = "01a1d8e6-b277-70fd-86ad-9c3f2155ea91"
SOUL_B = "01a1d914-3b6c-76c0-92f6-9b9cfb68b328"


def _write_bridge(state, sid: str, workdir: str = WS) -> None:
	directory = state / "sessions" / "bridge"
	directory.mkdir(parents=True, exist_ok=True)
	directory.joinpath(f"opencode__{sid}.json").write_text(
		json.dumps({"provider": "opencode", "session_id": sid, "workdir": workdir, "updated_at": time.time()})
	)


def _live(*sids: str) -> list[SessionSignal]:
	now = time.time()
	return [SessionSignal(provider="opencode", session_id=s, start_mtime=now - 5, end_mtime=None) for s in sids]


def _patch_bridge(state, live):
	return [
		patch("red_pill.core.bridge.get_state_dir", return_value=state),
		patch("red_pill.core.session_liveness.list_sessions", lambda: live),
		patch("red_pill.core.bridge._opencode_db_path", return_value=state / "nope.db"),
	]


@pytest.fixture
def gemelas():
	"""Dos legs vivos en el MISMO workspace, cada uno con su alma."""
	registry = SessionRegistry()
	registry.upsert_session(originator=LEG_A, continuity_id=SOUL_A, mission_id="repo:sharing", worktree=WS)
	registry.upsert_session(originator=LEG_B, continuity_id=SOUL_B, mission_id="repo:sharing", worktree=WS)
	return registry


def _ambigua(**extra):
	"""Identidad del proxy tal como la manda `identity_payload` con 2+ vivas."""
	payload = {"originator": "", "workdir": WS, "harness": "opencode", "ambiguous": True}
	payload.update(extra)
	return payload


class TestCorrelacionNoDesempataPestanas:
	"""El proxy no puede elegir pestaña con el cwd: ni por bridge ni por la BD."""

	def test_dos_vivas_mismo_cwd_es_ambiguo_aunque_la_bd_case_una(self, tmp_path):
		"""Regresión exacta del 2026-11-14: la capa 2 de `opencode.db` "desempató"
		una pestaña entre varias vivas del mismo cwd y el turno quedó en el alma
		equivocada."""
		state = tmp_path / "state"
		_write_bridge(state, "a")
		_write_bridge(state, "b")
		patches = _patch_bridge(state, _live("a", "b"))
		# La BD solo conoce (por ahora) a "b": antes ganaba y se atribuía el cuerpo.
		patches.append(patch("red_pill.core.bridge._session_directory", lambda sid: WS if sid == "b" else None))
		for p in patches:
			p.start()
		try:
			assert bridge.resolve_body_by_cwd("opencode", WS) is None
		finally:
			for p in patches:
				p.stop()

	def test_una_sola_viva_sigue_resolviendo(self, tmp_path):
		"""Contraprueba: la correlación honesta no se rompe (1 viva = se resuelve)."""
		state = tmp_path / "state"
		_write_bridge(state, "a")
		patches = _patch_bridge(state, _live("a"))
		for p in patches:
			p.start()
		try:
			entry = bridge.resolve_body_by_cwd("opencode", WS)
		finally:
			for p in patches:
				p.stop()
		assert entry is not None and entry["session_id"] == "a"


class TestSinMentiraDelBridgeGlobal:
	"""Con el proxy delante, el global (último escritor) no firma por nadie."""

	@pytest.mark.asyncio
	async def test_ambiguo_sin_cuerpo_no_cae_al_global(self, monkeypatch, gemelas):
		monkeypatch.setenv("REDPILL_HARNESS", "opencode")
		# El global apunta a la HERMANA B: si se usara, firmaría por ella.
		monkeypatch.setattr(srv, "_harness_bridge", lambda *_: {"originator": LEG_B, "workdir": WS})
		token = srv._shared_identity_var.set(_ambigua())
		try:
			ident = await srv._resolve_session_identity({"user_prompt": "hola"}, persist=False)
		finally:
			srv._shared_identity_var.reset(token)
		assert ident["originator"] is None, "el global NO puede firmar por otra alma"
		assert ident["identity_source"] is None
		assert ident["continuity_id"] is None, "sin cuerpo no se emite un alma fantasma"

	@pytest.mark.asyncio
	async def test_proxy_resuelto_manda_si_esta_solo(self, monkeypatch, gemelas):
		"""Con UNA sola alma en el workspace, el proxy sigue resolviendo (sin coste)."""
		monkeypatch.setenv("REDPILL_HARNESS", "opencode")
		gemelas.unregister_session(LEG_B)  # queda una sola alma en este workspace
		token = srv._shared_identity_var.set({"originator": LEG_A, "workdir": WS, "harness": "opencode", "ambiguous": False})
		try:
			ident = await srv._resolve_session_identity({"user_prompt": "hola"}, persist=False)
		finally:
			srv._shared_identity_var.reset(token)
		assert ident["originator"] == LEG_A
		assert ident["continuity_id"] == SOUL_A
		assert ident["identity_source"] == "proxy"

	@pytest.mark.asyncio
	async def test_con_dos_almas_el_proxy_no_basta(self, monkeypatch, gemelas):
		"""Dos almas en el workspace y sin cuerpo declarado/deducido: el proxy no
		firma (su correlación por cwd es una heurística sobre un directorio que
		comparten; ya atribuyó turnos a la hermana)."""
		monkeypatch.setenv("REDPILL_HARNESS", "opencode")
		token = srv._shared_identity_var.set({"originator": LEG_B, "workdir": WS, "harness": "opencode", "ambiguous": False})
		try:
			with patch("red_pill.core.bridge.recent_session_by_activity", return_value=None):
				ident = await srv._resolve_session_identity({"user_prompt": "x"}, persist=False)
		finally:
			srv._shared_identity_var.reset(token)
		assert ident["originator"] is None
		assert ident["continuity_id"] is None

	@pytest.mark.asyncio
	async def test_cuerpo_declarado_manda_sobre_el_proxy(self, monkeypatch, gemelas):
		"""El proxy es una heurística de un cwd COMPARTIDO: si el agente declara su
		cuerpo (y la fila verifica), su declaración manda (incidente 2026-11-14: el
		proxy resolvió a la hermana viva y el turno se firmó con el alma de ella)."""
		monkeypatch.setenv("REDPILL_HARNESS", "opencode")
		token = srv._shared_identity_var.set({"originator": LEG_B, "workdir": WS, "harness": "opencode", "ambiguous": False})
		try:
			ident = await srv._resolve_session_identity({"user_prompt": "hola", "caller_leg": LEG_A}, persist=False)
		finally:
			srv._shared_identity_var.reset(token)
		assert ident["originator"] == LEG_A
		assert ident["continuity_id"] == SOUL_A
		assert ident["identity_source"] == "declared"

	@pytest.mark.asyncio
	async def test_env_de_job_no_se_pisa_por_la_declaracion(self, monkeypatch, gemelas):
		"""Un job lleva su cuerpo en env (canal de confianza): no se pisa."""
		monkeypatch.setenv("REDPILL_HARNESS", "opencode")
		monkeypatch.setenv("REDPILL_ORIGINATOR", "job:abc")
		token = srv._shared_identity_var.set({"originator": "", "workdir": WS, "harness": "opencode", "ambiguous": True})
		try:
			ident = await srv._resolve_session_identity({"caller_leg": LEG_A}, persist=False)
		finally:
			srv._shared_identity_var.reset(token)
		assert ident["originator"] == "job:abc"
		assert ident["identity_source"] == "env"


class TestDiarioDelTurno:
	"""El prompt casa con UNA sesión viva: cuerpo determinista, sin tocar el arnés."""

	def _journal(self, state, sid: str, prompt: str, *, cwd: str = WS, status: str = "pending", originator: str | None = None, started_at: float | None = None):
		directory = state / "external_turns" / "current"
		directory.mkdir(parents=True, exist_ok=True)
		directory.joinpath(f"opencode__{sid}.json").write_text(
			json.dumps(
				{
					"provider": "opencode",
					"session_id": sid,
					"originator": originator or f"opencode:{sid}",
					"prompt": prompt,
					"cwd": cwd,
					"status": status,
					"started_at": time.time() if started_at is None else started_at,
				}
			)
		)

	def test_prompt_unico_resuelve_el_cuerpo(self, tmp_path):
		state = tmp_path / "state"
		self._journal(state, "a", "arregla la suite que rompe el yaml de la hermana")
		self._journal(state, "b", "otra cosa completamente distinta que hacer")
		with patch("red_pill.core.paths.get_state_dir", return_value=state):
			assert srv._leg_from_turn_prompt("arregla la suite que rompe el yaml de la hermana", WS) == "opencode:a"

	def test_dos_gemelas_con_el_mismo_prompt_no_se_adivina(self, tmp_path):
		"""Dos "sí, dale" simultáneos: no hay match único → None (el coro pedirá leg)."""
		state = tmp_path / "state"
		self._journal(state, "a", "si, dale")
		self._journal(state, "b", "si, dale")
		with patch("red_pill.core.paths.get_state_dir", return_value=state):
			assert srv._leg_from_turn_prompt("si, dale", WS) is None

	def test_prompt_de_otro_workspace_no_casa(self, tmp_path):
		state = tmp_path / "state"
		self._journal(state, "a", "trabajo largo en otro repositorio distinto", cwd="/ws/otro")
		with patch("red_pill.core.paths.get_state_dir", return_value=state):
			assert srv._leg_from_turn_prompt("trabajo largo en otro repositorio distinto", WS) is None

	def test_turno_cerrado_no_casa(self, tmp_path):
		state = tmp_path / "state"
		self._journal(state, "a", "un prompt suficientemente largo para casar", status="completed")
		with patch("red_pill.core.paths.get_state_dir", return_value=state):
			assert srv._leg_from_turn_prompt("un prompt suficientemente largo para casar", WS) is None

	def test_turno_rancio_no_casa(self, tmp_path):
		"""Un `current/` pendiente de hace horas es un turno que murió sin sellar."""
		state = tmp_path / "state"
		self._journal(
			state, "a", "un prompt suficientemente largo para casar", started_at=time.time() - 4 * 3600
		)
		with patch("red_pill.core.paths.get_state_dir", return_value=state):
			assert srv._leg_from_turn_prompt("un prompt suficientemente largo para casar", WS) is None

	def test_prompt_recortado_casa_por_contencion(self, tmp_path):
		state = tmp_path / "state"
		self._journal(state, "a", "necesito que revises el fichero de la hermana y me digas si rompe la suite")
		with patch("red_pill.core.paths.get_state_dir", return_value=state):
			assert srv._leg_from_turn_prompt("necesito que revises el fichero de la hermana", WS) == "opencode:a"

	@pytest.mark.asyncio
	async def test_handshake_ambiguo_usa_el_diario(self, monkeypatch, gemelas, tmp_path):
		"""La cadena completa: proxy ambiguo + diario del turno → cuerpo correcto."""
		monkeypatch.setenv("REDPILL_HARNESS", "opencode")
		monkeypatch.setattr(srv, "_harness_bridge", lambda *_: {"originator": LEG_B, "workdir": WS})
		state = tmp_path / "state"
		self._journal(state, LEG_A.split(":", 1)[1], "revisa el yaml de la hermana que rompe la suite")
		token = srv._shared_identity_var.set(_ambigua())
		try:
			with patch("red_pill.core.paths.get_state_dir", return_value=state):
				ident = await srv._resolve_session_identity(
					{"user_prompt": "revisa el yaml de la hermana que rompe la suite"}, persist=False
				)
		finally:
			srv._shared_identity_var.reset(token)
		assert ident["originator"] == LEG_A
		assert ident["continuity_id"] == SOUL_A
		assert ident["identity_source"] == "turn_journal"


class TestActividadReciente:
	"""`time_updated` de opencode: la pestaña que acaba de emitir es la que llama.

	Es la señal que la correlación por cwd no tiene y que evita exigirle al agente
	que recuerde pasar `caller_leg` en cada llamada al coro.
	"""

	def _db(self, tmp_path, rows):
		db = tmp_path / "opencode.db"
		con = sqlite3.connect(db)
		con.execute("CREATE TABLE session_v2 (id TEXT, directory TEXT, time_updated INTEGER)")
		con.executemany("INSERT INTO session_v2 VALUES (?, ?, ?)", rows)
		con.commit()
		con.close()
		return db

	def test_la_pestana_que_emite_ahora_es_la_que_llama(self, tmp_path):
		now_ms = int(time.time() * 1000)
		db = self._db(tmp_path, [("mia", WS, now_ms), ("hermana", WS, now_ms - 5 * 60 * 1000)])
		with patch("red_pill.core.bridge._opencode_db_path", return_value=db):
			assert bridge.recent_session_by_activity("opencode", WS) == "mia"

	def test_empate_tecnico_no_elige(self, tmp_path):
		now_ms = int(time.time() * 1000)
		db = self._db(tmp_path, [("mia", WS, now_ms), ("hermana", WS, now_ms - 5 * 1000)])
		with patch("red_pill.core.bridge._opencode_db_path", return_value=db):
			assert bridge.recent_session_by_activity("opencode", WS) is None

	def test_sesion_rancia_no_cuenta(self, tmp_path):
		now_ms = int(time.time() * 1000)
		db = self._db(tmp_path, [("mia", WS, now_ms - 3600 * 1000)])
		with patch("red_pill.core.bridge._opencode_db_path", return_value=db):
			assert bridge.recent_session_by_activity("opencode", WS) is None

	def test_otro_workspace_no_cuenta(self, tmp_path):
		now_ms = int(time.time() * 1000)
		db = self._db(tmp_path, [("mia", "/ws/otro", now_ms)])
		with patch("red_pill.core.bridge._opencode_db_path", return_value=db):
			assert bridge.recent_session_by_activity("opencode", WS) is None

	@pytest.mark.asyncio
	async def test_la_actividad_manda_sobre_el_proxy_sin_caller_leg(self, monkeypatch, gemelas):
		"""El caso medido: el agente NO pasa caller_leg y el proxy resuelve a la
		hermana; la actividad reciente dice quién llama y gana."""
		monkeypatch.setenv("REDPILL_HARNESS", "opencode")
		token = srv._shared_identity_var.set({"originator": LEG_B, "workdir": WS, "harness": "opencode", "ambiguous": False})
		try:
			with patch("red_pill.core.bridge.recent_session_by_activity", return_value="ses_gemela_a"):
				ident = await srv._resolve_session_identity({"user_prompt": "x"}, persist=False)
		finally:
			srv._shared_identity_var.reset(token)
		assert ident["originator"] == LEG_A
		assert ident["continuity_id"] == SOUL_A
		assert ident["identity_source"] == "activity"


class TestCuerpoDeclarado:
	"""`caller_leg`: eco del tag, verificado contra el registro (no creído)."""

	def test_leg_vivo_y_del_workspace_se_acepta(self, gemelas):
		row = srv._declared_leg_row(LEG_A, workspace=WS)
		assert row and row["continuity_id"] == SOUL_A

	def test_leg_de_otro_workspace_se_rechaza(self, gemelas):
		assert srv._declared_leg_row(LEG_A, workspace="/ws/ajeno") is None

	def test_subdirectorio_del_workspace_se_acepta(self, gemelas):
		"""`cd` dentro del árbol no invalida el cuerpo: es el mismo workspace."""
		assert srv._declared_leg_row(LEG_A, workspace=f"{WS}/src") is not None

	def test_leg_desconocido_se_rechaza(self, gemelas):
		assert srv._declared_leg_row("opencode:ses_no_existe", workspace=WS) is None

	def test_leg_desnudo_se_rechaza(self, gemelas):
		assert srv._declared_leg_row("opencode", workspace=WS) is None

	def test_leg_rancio_se_rechaza(self, gemelas):
		with patch("red_pill.mcp_server._registry_ttl_s", return_value=0.0):
			assert srv._declared_leg_row(LEG_A, workspace=WS) is None

	@pytest.mark.asyncio
	async def test_caller_leg_resuelve_la_identidad(self, monkeypatch, gemelas):
		monkeypatch.setenv("REDPILL_HARNESS", "opencode")
		monkeypatch.setattr(srv, "_harness_bridge", lambda *_: {"originator": "", "workdir": WS})
		monkeypatch.setenv("REDPILL_MISSION_ID", "repo:sharing")
		token = srv._shared_identity_var.set(_ambigua())
		try:
			session = await srv._caller_session({"caller_leg": LEG_A})
		finally:
			srv._shared_identity_var.reset(token)
		assert session["originator"] == LEG_A
		assert session["continuity_id"] == SOUL_A
		assert session["identity_source"] == "declared"

	@pytest.mark.asyncio
	async def test_sin_leg_el_coro_pide_identidad(self, monkeypatch, gemelas):
		"""Sin cuerpo verificado no hay alma: el coro pedirá `caller_leg`."""
		monkeypatch.setenv("REDPILL_HARNESS", "opencode")
		monkeypatch.setattr(srv, "_harness_bridge", lambda *_: {"originator": "", "workdir": WS})
		token = srv._shared_identity_var.set(_ambigua())
		try:
			session = await srv._caller_session({})
		finally:
			srv._shared_identity_var.reset(token)
		assert session["originator"] is None
		assert session["continuity_id"] is None

	@pytest.mark.asyncio
	async def test_leg_de_otra_mision_se_descarta(self, monkeypatch, gemelas):
		"""Un cuerpo declarado cuya fila es de otra misión no firma aquí."""
		monkeypatch.setenv("REDPILL_HARNESS", "opencode")
		monkeypatch.setattr(srv, "_harness_bridge", lambda *_: {"originator": "", "workdir": WS})
		monkeypatch.setenv("REDPILL_MISSION_ID", "repo:otro-proyecto")
		token = srv._shared_identity_var.set(_ambigua())
		try:
			session = await srv._caller_session({"caller_leg": LEG_A})
		finally:
			srv._shared_identity_var.reset(token)
		assert session["continuity_id"] is None
