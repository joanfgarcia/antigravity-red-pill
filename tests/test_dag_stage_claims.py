"""F4-E3 — el `DagJobDriver` reclama la etapa antes de ejecutarla.

Contrato (STAGE_CLAIMS.md §4 + decisión del Operador 2026-10-28):

- Una etapa reclamada por otra alma **no se ejecuta**. Se difiere el step con
  `JobDeferred`: preserva lo que las hermanas paralelas ya completaron, no
  consume intentos y el runner reentra cuando el claim expire. **Nunca se marca
  completada una etapa que no se ha ejecutado.**
- El claim se suelta al terminar (finally), también si la etapa difiere o pausa.
- Sin alma (`continuity_id`) no hay claim: comportamiento legacy intacto (D-02).
- `stage_claims: false` en el payload lo desactiva (escape hatch operativo).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from red_pill.jobs.drivers.base import JobDeferred
from red_pill.jobs.drivers.dag import DagJobDriver
from red_pill.session.stage_claims import ClaimResult


class _StubDriver(DagJobDriver):
	"""Driver mínimo: no toca GPU ni el worktree real."""

	short_id = "test1"
	job_id = "job-test-1"
	_RENEW_KEYS = DagJobDriver._RENEW_KEYS
	_RELEASE_KEYS = DagJobDriver._RELEASE_KEYS

	def _workdir(self, payload):  # type: ignore[override]
		return "/ws"

	def _stage_timeout(self, stage, payload):  # type: ignore[override]
		return 30

	def _preflight_stage_gpu(self, stage, stage_path, payload):  # type: ignore[override]
		return None


_STAGE = {"type": "command", "minion": "sleep_ritual", "command": "true"}
_PAYLOAD = {"continuity_id": "alma-a", "mission_id": "repo:next", "branch": "next", "title": "misión de prueba"}


class TestStageClaimGate:
	def test_etapa_reclamada_por_otra_alma_no_se_ejecuta(self):
		"""Lo esencial: si el claim no es nuestro, el minion NO corre."""
		driver = _StubDriver()
		ejecutado = []
		with patch("red_pill.session.stage_claims.try_claim_stage", return_value=ClaimResult(False, "alma-b", "held_by_other")), patch(
			"red_pill.swarm.factory.MinionFactory.create", side_effect=lambda *a, **k: ejecutado.append(a) or None
		):
			with pytest.raises(JobDeferred) as exc:
				driver._run_atomic(_PAYLOAD, _STAGE, "dag:m/stage:x")
		assert "reclamada por otra alma" in str(exc.value)
		assert ejecutado == [], "no debe ni construir el minion si la etapa está reclamada"

	def test_claim_ganado_ejecuta_y_suelta(self):
		driver = _StubDriver()
		soltados = []
		with patch("red_pill.session.stage_claims.try_claim_stage", return_value=ClaimResult(True, "alma-a", "acquired")), patch(
			"red_pill.session.stage_claims.release_claim", side_effect=lambda **k: soltados.append(k["stage_path"]) or True
		), patch.object(_StubDriver, "_run_atomic_inner", return_value="ok") as inner:
			driver._run_atomic(_PAYLOAD, _STAGE, "dag:m/stage:x")
		assert inner.called, "con el claim ganado la etapa se ejecuta"
		assert soltados == ["dag:m/stage:x"], "el claim debe soltarse al terminar"

	def test_claim_se_suelta_tambien_si_la_etapa_falla(self):
		"""Un fallo no puede dejar el claim colgado (bloquearía a los demás)."""
		driver = _StubDriver()
		soltados = []
		with patch("red_pill.session.stage_claims.try_claim_stage", return_value=ClaimResult(True, "alma-a", "acquired")), patch(
			"red_pill.session.stage_claims.release_claim", side_effect=lambda **k: soltados.append(1) or True
		), patch.object(_StubDriver, "_run_atomic_inner", side_effect=RuntimeError("boom")):
			with pytest.raises(RuntimeError):
				driver._run_atomic(_PAYLOAD, _STAGE, "dag:m/stage:x")
		assert soltados == [1]

	def test_sin_alma_no_hay_claim(self):
		"""Job sin `continuity_id`: comportamiento legacy, no se reclama nada."""
		driver = _StubDriver()
		llamado = []
		payload = {k: v for k, v in _PAYLOAD.items() if k != "continuity_id"}
		with patch("red_pill.session.stage_claims.try_claim_stage", side_effect=lambda **k: llamado.append(k)), patch.object(
			_StubDriver, "_run_atomic_inner", return_value="ok"
		):
			driver._run_atomic(payload, _STAGE, "dag:m/stage:x")
		assert llamado == [], "sin alma no se inventa un dueño (D18)"

	def test_se_puede_desactivar_por_payload(self):
		driver = _StubDriver()
		llamado = []
		payload = dict(_PAYLOAD, stage_claims=False)
		with patch("red_pill.session.stage_claims.try_claim_stage", side_effect=lambda **k: llamado.append(k)), patch.object(
			_StubDriver, "_run_atomic_inner", return_value="ok"
		):
			driver._run_atomic(payload, _STAGE, "dag:m/stage:x")
		assert llamado == []

	def test_fallo_del_subsistema_de_claims_no_bloquea_el_dag(self):
		"""El claim es cooperativo: si el almacén falla, el DAG sigue (fail-open)."""
		driver = _StubDriver()
		with patch("red_pill.session.stage_claims.try_claim_stage", side_effect=RuntimeError("db rota")), patch.object(
			_StubDriver, "_run_atomic_inner", return_value="ok"
		) as inner:
			assert driver._run_atomic(_PAYLOAD, _STAGE, "dag:m/stage:x") == "ok"
		assert inner.called


class TestClaimParams:
	def test_la_afinidad_sale_de_la_mision(self):
		driver = _StubDriver()
		params = driver._claim_params(_PAYLOAD, "/ws", "dag:m/stage:x")
		assert params is not None
		assert any("mission:repo:next" == a for a in params["affinity"]), params["affinity"]
		assert params["continuity_id"] == "alma-a"
		assert params["originator"].startswith("dag:")

	def test_la_rama_del_payload_manda(self):
		driver = _StubDriver()
		params = driver._claim_params(_PAYLOAD, "/ws", "x")
		assert params["branch"] == "next"

	def test_sin_rama_en_payload_se_detecta_del_worktree(self):
		driver = _StubDriver()
		payload = {k: v for k, v in _PAYLOAD.items() if k != "branch"}
		with patch("red_pill.jobs.drivers.dag_exec._workdir_branch", return_value="feat/x"):
			params = driver._claim_params(payload, "/ws", "x")
		assert params["branch"] == "feat/x"

	def test_ttl_del_payload_se_respeta(self):
		driver = _StubDriver()
		params = driver._claim_params(dict(_PAYLOAD, claim_ttl_s=600), "/ws", "x")
		assert params.get("ttl_seconds") == 600


class TestRenovacionPorLatido:
	"""F4-E4 (D9-a): el claim se renueva mientras la etapa corre.

	Sin latido, una etapa de más de `ttl` pierde el claim a mitad y otro driver
	la roba **mientras sigue en vuelo**: dos ejecutando lo mismo. Atarlo a un
	checkpoint no basta — las etapas atómicas pueden no emitir ninguno.
	"""

	def test_el_intervalo_es_un_tercio_del_ttl_con_suelo(self):
		assert _StubDriver._renew_interval(1800) == 600.0
		assert _StubDriver._renew_interval(60) == 20.0
		assert _StubDriver._renew_interval(6) == 5.0, "el suelo evita martillear con TTLs cortos"
		assert _StubDriver._renew_interval(0) > 0, "un TTL 0 cae al default, no a un bucle"

	def test_el_latido_renueva_y_para_al_soltar(self):
		"""El hilo debe renovar durante la etapa y detenerse ANTES del release."""
		import time as _t

		driver = _StubDriver()
		eventos = []
		with patch.object(_StubDriver, "_renew_interval", return_value=0.02), patch(
			"red_pill.session.stage_claims.try_claim_stage", return_value=ClaimResult(True, "alma-a", "acquired")
		), patch(
			"red_pill.session.stage_claims.renew_claim",
			side_effect=lambda **k: eventos.append("renew") or True,
		), patch(
			"red_pill.session.stage_claims.release_claim",
			side_effect=lambda **k: eventos.append("release") or True,
		), patch.object(
			_StubDriver, "_run_atomic_inner", side_effect=lambda *a, **k: _t.sleep(0.12) or "ok"
		):
			driver._run_atomic(_PAYLOAD, _STAGE, "dag:m/stage:x")

		assert eventos.count("renew") >= 2, f"esperaba varios latidos, hubo {eventos.count('renew')}"
		assert eventos[-1] == "release", "el último evento debe ser el release"
		# Y el latido no puede seguir renovando DESPUÉS del release.
		n = eventos.count("renew")
		_t.sleep(0.06)
		assert eventos.count("renew") == n, "el latido siguió vivo tras soltar el claim"

	def test_sin_claim_ganado_no_hay_latido(self):
		driver = _StubDriver()
		renovado = []
		with patch.object(_StubDriver, "_renew_interval", return_value=0.01), patch(
			"red_pill.session.stage_claims.try_claim_stage", return_value=ClaimResult(False, "alma-b", "held_by_other")
		), patch("red_pill.session.stage_claims.renew_claim", side_effect=lambda **k: renovado.append(1) or True):
			with pytest.raises(JobDeferred):
				driver._run_atomic(_PAYLOAD, _STAGE, "dag:m/stage:x")
		assert renovado == []

	def test_una_renovacion_fallida_no_tira_la_etapa(self):
		"""Si el claim expira, la etapa continúa: tirar el trabajo sería peor."""
		import time as _t

		driver = _StubDriver()
		with patch.object(_StubDriver, "_renew_interval", return_value=0.01), patch(
			"red_pill.session.stage_claims.try_claim_stage", return_value=ClaimResult(True, "alma-a", "acquired")
		), patch("red_pill.session.stage_claims.renew_claim", return_value=False), patch(
			"red_pill.session.stage_claims.release_claim", return_value=True
		), patch.object(
			_StubDriver, "_run_atomic_inner", side_effect=lambda *a, **k: _t.sleep(0.05) or "ok"
		):
			assert driver._run_atomic(_PAYLOAD, _STAGE, "dag:m/stage:x") == "ok"


class TestIntegracionSinMocks:
	"""El E2E de F4-E5 (2026-10-28) cazó un fallo que los mocks tapaban.

	`_claim_params` devuelve el conjunto completo; pasarlo tal cual a
	`renew_claim`/`release_claim` lanzaba `TypeError` por kwargs de más. Los
	tests anteriores mockeaban con `lambda **k`, que se traga cualquier firma:
	verdes, y el latido no renovaba ni el release soltaba. Estos tests hablan con
	las funciones REALES contra una BD temporal.
	"""

	@pytest.fixture
	def sesion_temporal(self, tmp_path, monkeypatch):
		db = str(tmp_path / "session.db")
		monkeypatch.setattr("red_pill.core.paths.get_session_db", lambda: db)
		return db

	def test_firmas_compatibles_con_las_claves_que_envia_el_driver(self):
		"""Test estructural: habría cazado el TypeError al instante."""
		import inspect

		from red_pill.session.stage_claims import release_claim, renew_claim

		renew_args = set(inspect.signature(renew_claim).parameters)
		release_args = set(inspect.signature(release_claim).parameters)
		assert set(_StubDriver._RENEW_KEYS) <= renew_args, f"renew_claim no acepta {set(_StubDriver._RENEW_KEYS) - renew_args}"
		assert set(_StubDriver._RELEASE_KEYS) <= release_args, f"release_claim no acepta {set(_StubDriver._RELEASE_KEYS) - release_args}"

	def test_claim_se_suelta_de_verdad(self, sesion_temporal):
		"""Sin mocks: la fila DESAPARECE al soltarla con las claves del driver.

		Ojo con el detalle que hacía este test inútil al principio: importar
		`try_claim_stage` DENTRO de un `patch(...)` devuelve el mock, así que el
		claim nunca se creaba y la aserción pasaba en el vacío. Aquí se usa la
		función real, importada fuera de cualquier parche.
		"""
		from red_pill.session.stage_claims import get_claim
		from red_pill.session.stage_claims import try_claim_stage as real_claim

		driver = _StubDriver()
		kw = dict(stage_path="dag:m/stage:x", affinity=["mission:repo:next"], branch="next", worktree="/ws")
		assert real_claim(**kw, continuity_id="alma-a", originator="dag:job-test-1").claimed
		assert get_claim(**kw) is not None, "el claim debe existir antes de soltarlo"

		driver._release_stage_claim(_PAYLOAD, "dag:m/stage:x", "/ws")

		assert get_claim(**kw) is None, "el release real debe borrar la fila"

	def test_el_latido_renueva_el_claim_real(self, sesion_temporal):
		"""Con el reloj acelerado, el latido mantiene vivo el claim real."""
		import time as _t

		from red_pill.session.stage_claims import get_claim
		from red_pill.session.stage_claims import try_claim_stage as real_claim

		kw = dict(stage_path="dag:m/largo", affinity=["mission:repo:next"], branch="next", worktree="/ws")
		real_claim(**kw, continuity_id="alma-a", originator="dag:job-test-1", ttl_seconds=3)
		driver = _StubDriver()
		with patch.object(_StubDriver, "_renew_interval", return_value=0.05), patch.object(
			_StubDriver, "_claim_params", wraps=driver._claim_params
		):
			stop = driver._start_claim_renewer(dict(_PAYLOAD, claim_ttl_s=3), "dag:m/largo", "/ws")
			_t.sleep(0.35)  # el TTL es 3 s: sin renovar seguiría vivo, así que miramos el claimed_at
			antes = get_claim(**kw)["claimed_at"]
			_t.sleep(0.3)
			despues = get_claim(**kw)["claimed_at"]
			stop.set()
		assert despues > antes, "el latido debe mover claimed_at (renovar de verdad)"
