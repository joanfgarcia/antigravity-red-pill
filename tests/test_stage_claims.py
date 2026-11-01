"""F4-E2 — claims de etapa: clave canónica, atomicidad y propiedad por alma.

Contrato del RFC (`RFC_CONSCIENCIA_MULTISESION.md` §6) más las decisiones:
D12 (claim_key canónica), D13 (atomicidad con BEGIN IMMEDIATE + re-lectura),
D18 (el claim es del ALMA; sobrevive a switch_model), D9-a (TTL renovable),
D14 (purga).

El test que más importa es el de CARRERA: si el CAS no es atómico, dos drivers
reclaman la misma etapa y los dos creen tenerla. Es la misma clase de bug que
A4 (kill↔claim) y por eso se prueba con hilos reales, no con mocks.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from red_pill.session.stage_claims import (
	DEFAULT_TTL_S,
	claim_key,
	get_claim,
	purge_expired,
	release_claim,
	renew_claim,
	try_claim_stage,
)


@pytest.fixture
def db(tmp_path):
	return str(tmp_path / "session.db")


def _claim(db, *, alma="alma-a", originator="opencode:ses_a", stage="dag:m1/stage:e2", affinity=("mission:m1",), branch="next", worktree="/ws", ttl=DEFAULT_TTL_S, now=None, intent=None):
	return try_claim_stage(
		stage_path=stage,
		affinity=list(affinity),
		branch=branch,
		worktree=worktree,
		continuity_id=alma,
		originator=originator,
		ttl_seconds=ttl,
		intent=intent,
		db_path=db,
		now=now,
	)


# ── D12: la clave es canónica ───────────────────────────────────────────────


class TestClaimKey:
	def test_orden_y_caja_no_cambian_la_clave(self):
		"""Dos representaciones equivalentes de la afinidad → MISMA clave."""
		a = claim_key(["mission:m1", "ws:/ws"], "next", "/ws", "st")
		b = claim_key(["WS:/WS", "Mission:M1"], "next", "/ws", "st")
		assert a == b

	def test_duplicados_no_cambian_la_clave(self):
		a = claim_key(["mission:m1"], "next", "/ws", "st")
		b = claim_key(["mission:m1", "mission:m1"], "next", "/ws", "st")
		assert a == b

	def test_etapa_distinta_clave_distinta(self):
		assert claim_key(["m"], "next", "/ws", "st1") != claim_key(["m"], "next", "/ws", "st2")

	def test_rama_o_worktree_distintos_clave_distinta(self):
		base = claim_key(["m"], "next", "/ws", "st")
		assert base != claim_key(["m"], "main", "/ws", "st")
		assert base != claim_key(["m"], "next", "/otro", "st")

	def test_afinidad_csv_equivale_a_lista(self):
		assert claim_key("mission:m1,ws:/ws", "next", "/ws", "st") == claim_key(["ws:/ws", "mission:m1"], "next", "/ws", "st")


# ── Adquisición y exclusión ─────────────────────────────────────────────────


class TestClaimBasic:
	def test_primera_adquisicion(self, db):
		r = _claim(db)
		assert r.claimed and r.reason == "acquired"
		assert r.owner == "alma-a"
		assert r.expires_at is not None

	def test_otra_alma_no_puede(self, db):
		assert _claim(db).claimed
		r = _claim(db, alma="alma-b", originator="opencode:ses_b")
		assert not r.claimed
		assert r.reason == "held_by_other"
		assert r.owner == "alma-a"

	def test_la_misma_alma_renueva(self, db):
		assert _claim(db).claimed
		r = _claim(db)
		assert r.claimed and r.reason == "owned"

	def test_stage_distinta_no_bloquea(self, db):
		assert _claim(db, stage="dag:m1/stage:e2").claimed
		r = _claim(db, alma="alma-b", originator="opencode:ses_b", stage="dag:m1/stage:e3")
		assert r.claimed and r.reason == "acquired"

	def test_etapas_de_otra_mision_no_se_pisan(self, db):
		assert _claim(db, affinity=("mission:m1",)).claimed
		r = _claim(db, alma="alma-b", originator="opencode:ses_b", affinity=("mission:m2",))
		assert r.claimed, "afinidad distinta = clave distinta = etapa distinta"


# ── D18: el claim es del alma, no del cuerpo ────────────────────────────────


class TestOwnershipBySoul:
	def test_switch_model_conserva_el_claim(self, db):
		"""Mismo continuity_id, otro originator (cambio de modelo/cuerpo) → sigue."""
		assert _claim(db, originator="opencode:ses_a").claimed
		r = _claim(db, originator="opencode:ses_a_v2")
		assert r.claimed, "un switch_model no puede perder el claim (D18)"
		assert r.reason == "owned"
		assert get_claim(stage_path="dag:m1/stage:e2", affinity=["mission:m1"], branch="next", worktree="/ws", db_path=db)["owner_originator"] == "opencode:ses_a_v2"

	def test_otra_alma_es_otro_dueno(self, db):
		assert _claim(db, alma="alma-a").claimed
		assert not _claim(db, alma="alma-b", originator="opencode:ses_b").claimed


# ── D9-a: TTL y robo ────────────────────────────────────────────────────────


class TestTTL:
	def test_expirado_se_roba_con_razon_explicita(self, db):
		assert _claim(db, ttl=60, now=1000.0).claimed
		r = _claim(db, alma="alma-b", originator="opencode:ses_b", ttl=60, now=1000.0 + 61)
		assert r.claimed and r.reason == "stolen_expired"
		assert r.owner == "alma-b"

	def test_justo_antes_de_expirar_no_se_roba(self, db):
		assert _claim(db, ttl=60, now=1000.0).claimed
		r = _claim(db, alma="alma-b", originator="opencode:ses_b", ttl=60, now=1000.0 + 59)
		assert not r.claimed and r.reason == "held_by_other"

	def test_renovar_propio(self, db):
		assert _claim(db, ttl=60, now=1000.0).claimed
		assert renew_claim(
			stage_path="dag:m1/stage:e2", affinity=["mission:m1"], branch="next", worktree="/ws",
			continuity_id="alma-a", originator="opencode:ses_a", ttl_seconds=600, db_path=db, now=1000.0 + 50,
		)
		# Con la renovación no expira a los 61 s.
		r = _claim(db, alma="alma-b", originator="opencode:ses_b", ttl=60, now=1000.0 + 61)
		assert not r.claimed

	def test_no_se_renueva_lo_ajeno(self, db):
		assert _claim(db).claimed
		assert not renew_claim(
			stage_path="dag:m1/stage:e2", affinity=["mission:m1"], branch="next", worktree="/ws",
			continuity_id="alma-b", originator="opencode:ses_b", db_path=db,
		), "renovar lo ajeno sería un robo silencioso"

	def test_ttl_no_positivo_cae_al_default(self, db):
		r = _claim(db, ttl=0, now=1000.0)
		assert r.claimed
		assert r.expires_at == 1000.0 + DEFAULT_TTL_S


# ── Liberación y purga ──────────────────────────────────────────────────────


class TestReleaseAndPurge:
	def test_libera_el_dueno(self, db):
		assert _claim(db).claimed
		assert release_claim(stage_path="dag:m1/stage:e2", affinity=["mission:m1"], branch="next", worktree="/ws", continuity_id="alma-a", db_path=db)
		assert get_claim(stage_path="dag:m1/stage:e2", affinity=["mission:m1"], branch="next", worktree="/ws", db_path=db) is None

	def test_no_libera_lo_ajeno(self, db):
		assert _claim(db).claimed
		assert not release_claim(
			stage_path="dag:m1/stage:e2", affinity=["mission:m1"], branch="next", worktree="/ws",
			continuity_id="alma-b", db_path=db,
		)
		assert get_claim(stage_path="dag:m1/stage:e2", affinity=["mission:m1"], branch="next", worktree="/ws", db_path=db) is not None

	def test_purga_solo_los_caducados(self, db):
		assert _claim(db, stage="s1", ttl=60, now=1000.0).claimed
		assert _claim(db, stage="s2", ttl=6000, now=1000.0).claimed
		assert purge_expired(db, now=1000.0 + 61) == 1
		assert get_claim(stage_path="s1", affinity=["mission:m1"], branch="next", worktree="/ws", db_path=db) is None
		assert get_claim(stage_path="s2", affinity=["mission:m1"], branch="next", worktree="/ws", db_path=db) is not None


# ── Fail-closed ─────────────────────────────────────────────────────────────


class TestFailClosed:
	def test_sin_alma_no_hay_claim(self, db):
		r = _claim(db, alma="")
		assert not r.claimed and r.reason == "error", "sin alma el claim no sobreviviría a switch_model (D18)"

	def test_sin_etapa_no_hay_claim(self, db):
		assert not _claim(db, stage="").claimed


# ── D13: la carrera (el test que de verdad importa) ─────────────────────────


class _SlowConn:
	"""Proxy de conexión que ENSANCHA la ventana SELECT→escritura.

	Sin esto el test de carrera es una tautología: los hilos no llegan a
	solaparse y el test pasa incluso SIN `BEGIN IMMEDIATE` (verificado con
	mutación el 2026-10-28). Con la pausa después del SELECT, la ventana es real:

	- Con `BEGIN IMMEDIATE`: el lock se toma ANTES de leer, los demás esperan y
	ven el claim → `held_by_other`. Correcto.
	- Sin él: todos leen "no hay fila", todos intentan INSERT, y el conflicto de
	PK sale como `error` → el test FALLA. Discrimina.
	"""

	def __init__(self, conn, delay_s: float):
		self._conn = conn
		self._delay = delay_s

	def execute(self, sql, *args):
		cursor = self._conn.execute(sql, *args)
		if "SELECT owner_continuity_id" in str(sql):
			import time as _t

			_t.sleep(self._delay)
		return cursor

	def __getattr__(self, name):
		return getattr(self._conn, name)


@pytest.fixture
def slow_db(db, monkeypatch):
	"""`db` con la ventana de carrera abierta (solo para los tests de carrera)."""
	import contextlib
	import sqlite3 as _sq

	from red_pill.session import stage_claims as sc

	@contextlib.contextmanager
	def _connect(_db=None):
		conn = _sq.connect(db, timeout=30.0)
		conn.row_factory = _sq.Row
		conn.execute("PRAGMA busy_timeout=5000")
		try:
			yield _SlowConn(conn, 0.03)
		finally:
			conn.close()

	monkeypatch.setattr(sc, "_connect", _connect)
	return db


class TestRace:
	def test_diez_almas_a_la_vez_solo_una_gana(self, slow_db):
		db = slow_db
		"""Sin atomicidad, varios drivers creen tener la misma etapa.

		Se lanzan 10 hilos a la vez sobre la MISMA etapa. Debe haber exactamente
		un `acquired`; el resto `held_by_other`. Es el criterio de aceptación de
		F4 ("sin pisada ni robo con carrera").
		"""

		def attempt(i: int):
			return _claim(db, alma=f"alma-{i}", originator=f"opencode:ses_{i}", now=2000.0)

		with ThreadPoolExecutor(max_workers=10) as pool:
			results = list(pool.map(attempt, range(10)))

		ganadores = [r for r in results if r.reason == "acquired"]
		assert len(ganadores) == 1, f"debía ganar exactamente una alma, ganaron {len(ganadores)}"
		assert all(r.reason in ("acquired", "held_by_other") for r in results)
		assert sum(1 for r in results if r.claimed) == 1

	def test_carrera_tras_expiracion_solo_un_robo(self, slow_db):
		db = slow_db
		"""Al expirar, varios pueden intentar robar: solo uno debe conseguirlo."""
		assert _claim(db, alma="alma-vieja", originator="opencode:ses_v", ttl=60, now=1000.0).claimed

		def attempt(i: int):
			return _claim(db, alma=f"alma-{i}", originator=f"opencode:ses_{i}", ttl=60, now=1000.0 + 61)

		with ThreadPoolExecutor(max_workers=8) as pool:
			results = list(pool.map(attempt, range(8)))

		robos = [r for r in results if r.claimed]
		assert len(robos) == 1, f"el robo también debe ser único; hubo {len(robos)}"
		assert robos[0].reason == "stolen_expired"


# ── Regresiones del coro (E-006, 2026-10-28) ────────────────────────────────
# Los cinco hallazgos de la segunda lente. Cada uno tenía escenario real; aquí
# queda clavado para que no vuelva.


class TestCoroE006Regresiones:
	def test_separadores_no_colisionan(self):
		"""Hallazgo 1: concatenar con `|`/`,` hacía colisionar etapas distintas."""
		assert claim_key(["m|a"], "b", "w", "s") != claim_key(["m"], "a", "b|w", "s")
		assert claim_key(["a,b"], "x", "w", "s") != claim_key(["a", "b"], "x", "w", "s")

	def test_worktree_equivalente_misma_clave(self):
		"""Hallazgo 3: `/ws` y `/ws/` son la MISMA etapa lógica."""
		assert claim_key(["m"], "next", "/ws", "s") == claim_key(["m"], "next", "/ws/", "s")

	def test_worktree_symlink_misma_clave(self, tmp_path):
		"""Un symlink al mismo sitio no puede crear un claim paralelo."""
		real = tmp_path / "real"
		real.mkdir()
		link = tmp_path / "link"
		link.symlink_to(real)
		assert claim_key(["m"], "next", str(real), "s") == claim_key(["m"], "next", str(link), "s")

	def test_no_se_renueva_un_claim_expirado(self, db):
		"""Hallazgo 2: el docstring decía False si expiró; el código decía True."""
		assert _claim(db, ttl=60, now=1000.0).claimed
		assert not renew_claim(
			stage_path="dag:m1/stage:e2", affinity=["mission:m1"], branch="next", worktree="/ws",
			continuity_id="alma-a", originator="opencode:ses_a", db_path=db, now=1000.0 + 61,
		), "resucitar un claim caducado decide por el que pudo robarlo"

	def test_entradas_malformadas_son_fail_closed(self, db):
		"""Hallazgo 5: canonicalizar/serializar fuera del try lanzaba excepción."""
		for bad in ({"affinity": 42}, {"ttl_seconds": None}, {"now": "x"}):
			args = dict(stage_path="s2", affinity=["m"], branch="next", worktree="/ws", continuity_id="a", originator="o", db_path=db)
			args.update(bad)
			r = try_claim_stage(**args)
			assert not r.claimed and r.reason == "error", f"{bad} debía ser fail-closed"

	def test_generador_de_afinidad_no_se_consume_dos_veces(self, db):
		"""Hallazgo 5b: `affinity` generador se leía dos veces y la 2ª veía vacío."""
		r = try_claim_stage(
			stage_path="sg", affinity=(x for x in ["mission:m1"]), branch="next", worktree="/ws",
			continuity_id="alma-a", originator="o", db_path=db,
		)
		assert r.claimed
		row = get_claim(stage_path="sg", affinity=["mission:m1"], branch="next", worktree="/ws", db_path=db)
		import json as _j
		assert _j.loads(row["affinity_json"]) == ["mission:m1"], "affinity_json no puede quedar vacío"
