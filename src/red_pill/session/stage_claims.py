"""Claims de etapa — coordinación federada entre almas (Fase 4).

Qué resuelve
------------
Varias sesiones (y drivers `dag_job`) pueden estar trabajando el MISMO proyecto
en la misma rama/worktree. Sin coordinación, dos ejecutan la misma etapa y se
pisan. Este módulo da el lock ligero del RFC (`RFC_CONSCIENCIA_MULTISESION.md`
§6, Fase 4): **quién está haciendo qué etapa**, con expiración y robo.

Decisiones que implementa (no inventa ninguna)
----------------------------------------------
- **D12 — `claim_key` canonizada.** La clave es
	`sha256(afinidad_canónica | branch | worktree | stage_path)`, con la afinidad
	en forma canónica (`lower/trim` + `sorted(dedup)`, `canonize_affinity`). No se
	serializa JSON crudo: dos representaciones equivalentes de la misma afinidad
	deben producir la MISMA clave, o el claim no protege nada.
- **D13 — atomicidad obligatoria.** Envolver el check de TTL-expirado + el robo
	en `BEGIN IMMEDIATE` con **re-lectura dentro** de la transacción. Un
	`SELECT` y luego escribir fuera de transacción tiene carrera entre dos
	drivers: los dos ven "expirado" y los dos roban.
- **D18 — el claim es del ALMA.** `owner_continuity_id` es el dueño; un
	`switch_model` a mitad de etapa NO pierde el claim (el leg nuevo renueva con
	la misma alma). `owner_originator` es informativo: dice qué cuerpo lo sostiene
	ahora mismo.
- **D9-a — TTL renovable.** Un claim nace con `ttl_seconds`; las etapas largas lo
	renuevan por checkpoint (`renew_claim`) en vez de pedir un TTL infinito.
	Pasado el TTL sin renovación, el claim se considera abandonado y otro puede
	robarlo.
- **D14 — purga.** `purge_expired` retira claims caducados (la llama el job de
	purga; aquí solo se expone).

Por qué no hay "esperar" aquí
-----------------------------
`try_claim_stage` es **CAS puro**: dice sí o no y por qué. Decidir si el driver
salta, espera o reintenta es política del llamante (`DagJobDriver`), no del
almacén. Meter la espera dentro convertiría el lock en un punto de bloqueo y
haría imposible razonar sobre los timeouts.

Non-fatal por diseño en las lecturas: un fallo de BD no debe tumbar el trabajo,
pero un fallo al ADQUIRIR sí debe ser explícito (`claimed=False`), nunca
"suponer que sí".
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import List, Optional

from red_pill.core.affinity import canonize_affinity
from red_pill.session.store import connect_session_db

logger = logging.getLogger(__name__)

# TTL por defecto de un claim. Deliberadamente corto: una etapa que no ha dejado
# checkpoint en 30 min probablemente murió (apagón, kill). Las etapas largas
# RENUEVAN (D9-a) — el TTL no es una promesa de duración.
DEFAULT_TTL_S = 1800

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS stage_claims (
	claim_key TEXT PRIMARY KEY,
	stage_path TEXT NOT NULL,
	affinity_json TEXT NOT NULL,
	branch TEXT NOT NULL,
	worktree TEXT NOT NULL,
	owner_continuity_id TEXT NOT NULL,
	owner_originator TEXT NOT NULL,
	claimed_at REAL NOT NULL,
	ttl_seconds INTEGER NOT NULL,
	intent TEXT
)
"""

_INDEX_DDL = "CREATE INDEX IF NOT EXISTS idx_stage_claims_owner ON stage_claims(owner_continuity_id)"


# ── Clave canónica (D12) ─────────────────────────────────────────────────────


def canonical_affinity(affinity: object) -> List[str]:
	"""Afinidad en forma canónica D19: `lower/trim` + `sorted(dedup)`.

	Acepta lista o CSV; descarta vacíos. Es la MISMA función que usa el registro
	para persistir, de modo que `claim_key` no depende de cómo llegó el dato.
	"""
	if affinity is None:
		return []
	if isinstance(affinity, str):
		values = [part for part in affinity.split(",")]
	else:
		values = [str(v) for v in affinity]  # type: ignore[attr-defined]
	return canonize_affinity([str(v) for v in values])


def _norm_worktree(worktree: str) -> str:
	"""Forma canónica de un worktree: el MISMO sitio no puede dar dos claves.

	`/ws`, `/ws/` y un symlink a `/ws` son la misma etapa lógica. Sin
	normalizar, dos drivers adquieren la misma etapa con claves distintas y se
	pisan — que es justo lo que F4 debe impedir (hallazgo del coro, 2026-10-28).
	"""
	raw = str(worktree or "").strip()
	if not raw:
		return ""
	return os.path.normpath(os.path.realpath(os.path.expanduser(raw)))


def _claim_key_from_canon(canon: List[str], branch: str, worktree: str, stage_path: str) -> str:
	"""Clave sin ambigüedad de separadores (D12).

	Se serializa como **JSON de una tupla**, no concatenando con `|`/`,`. Con
	concatenación, `["m|a"], "b", ...` y `["m"], "a", "b|w", ...` producían la
	MISMA cadena, y `["a,b"]` colisionaba con `["a","b"]`: dos etapas distintas
	compartían claim y una bloqueaba/robaba a la otra (hallazgo del coro,
	2026-10-28). JSON escapa y delimita, así que la codificación es inyectiva.
	"""
	payload = json.dumps(
		[list(canon), str(branch or "").strip(), _norm_worktree(worktree), str(stage_path or "").strip()],
		separators=(",", ":"),
		ensure_ascii=False,
	)
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def claim_key(affinity: object, branch: str, worktree: str, stage_path: str) -> str:
	"""`sha256(canonical_affinity | branch | worktree | stage_path)` — D12."""
	return _claim_key_from_canon(canonical_affinity(affinity), branch, worktree, stage_path)


# ── Resultado ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ClaimResult:
	"""Resultado de un intento de claim. `reason` es el porqué, no un adorno.

	Razones posibles:
	- `acquired`        — no había claim; se adquirió.
	- `owned`           — ya era de esta alma; se renovó (idempotente).
	- `held_by_other`   — vivo y de otra alma: NO se toca.
	- `stolen_expired`  — expirado; se robó (el anterior se considera muerto).
	- `error`           — no se pudo comprobar (fail-closed: `claimed=False`).
	"""

	claimed: bool
	owner: Optional[str]
	reason: str
	expires_at: Optional[float] = None

	@property
	def ok(self) -> bool:
		return self.claimed


def _connect(db_path: Optional[str]):
	return connect_session_db(str(db_path)) if db_path else connect_session_db(_default_db_path())


def _default_db_path() -> str:
	from red_pill.core.paths import get_session_db

	return str(get_session_db())


def ensure_schema(db_path: Optional[str] = None) -> None:
	"""Crea tabla e índice si no existen. Idempotente y non-fatal."""
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			conn.execute(_INDEX_DDL)
			conn.commit()
	except Exception as e:
		logger.warning(f"[stage-claims] no se pudo asegurar el esquema: {e}")


# ── Claim (D12 + D13 + D18) ─────────────────────────────────────────────────


def try_claim_stage(
	*,
	stage_path: str,
	affinity: object,
	branch: str,
	worktree: str,
	continuity_id: str,
	originator: str,
	ttl_seconds: int = DEFAULT_TTL_S,
	intent: Optional[str] = None,
	db_path: Optional[str] = None,
	now: Optional[float] = None,
) -> ClaimResult:
	"""Intenta reclamar `stage_path`. CAS atómico; nunca lanza por carrera.

	Reglas, en una transacción `BEGIN IMMEDIATE` (D13):

	1. Se **relee** la fila DENTRO de la transacción (el `SELECT` previo no vale:
	entre leer y escribir otro driver puede haber robado).
	2. Sin fila → `INSERT` y `claimed=True` (`acquired`).
	3. Misma alma → se renueva (`owned`); un `switch_model` no pierde el claim (D18).
	4. Otra alma y **no** expirado → `claimed=False` (`held_by_other`), sin tocar.
	5. Otra alma y expirado → se roba con `UPDATE` (`stolen_expired`).

	Un fallo de BD es **fail-closed** (`claimed=False`, `reason="error"`): dar por
	adquirido un claim que no se pudo comprobar rompería la exclusión en silencio.
	"""
	if not stage_path:
		return ClaimResult(claimed=False, owner=None, reason="error")
	if not continuity_id:
		# Sin alma no hay dueño posible: el claim no sobreviviría a un switch_model
		# (D18), así que no se concede.
		return ClaimResult(claimed=False, owner=None, reason="error")

	# Fail-closed también aquí: canonicalizar la afinidad, serializarla o
	# convertir `now`/`ttl` puede fallar con tipos malformados, y un claim que
	# revienta a mitad no puede acabar en "supongo que sí" (hallazgo del coro).
	try:
		canon = canonical_affinity(affinity)  # UNA vez: si `affinity` es generador,
		canon_json = json.dumps(canon)  # la segunda lectura lo vería vacío
		key = _claim_key_from_canon(canon, branch, worktree, stage_path)
		stamp = float(now) if now is not None else time.time()
		ttl = int(ttl_seconds) if int(ttl_seconds) > 0 else DEFAULT_TTL_S
		expires = stamp + ttl
	except Exception as e:
		logger.warning(f"[stage-claims] entrada inválida al reclamar {stage_path!r}: {e}")
		return ClaimResult(claimed=False, owner=None, reason="error")

	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			conn.execute(_INDEX_DDL)
			# D13: la transacción empieza ANTES de leer. `BEGIN IMMEDIATE` toma el
			# lock de escritura de una vez: dos drivers no pueden intercalar el
			# check de expiración y el robo.
			conn.execute("BEGIN IMMEDIATE")
			try:
				row = conn.execute(
					"SELECT owner_continuity_id, claimed_at, ttl_seconds FROM stage_claims WHERE claim_key = ?",
					(key,),
				).fetchone()

				if row is None:
					conn.execute(
						"INSERT INTO stage_claims (claim_key, stage_path, affinity_json, branch, worktree, "
						"owner_continuity_id, owner_originator, claimed_at, ttl_seconds, intent) "
						"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
						(key, stage_path, canon_json, str(branch or ""), str(worktree or ""), continuity_id, str(originator or ""), stamp, ttl, intent),
					)
					conn.commit()
					return ClaimResult(claimed=True, owner=continuity_id, reason="acquired", expires_at=expires)

				owner = str(row["owner_continuity_id"] or "")
				if owner == continuity_id:
					# Renovación: el alma sigue siendo dueña aunque haya cambiado de
					# cuerpo (D18). Se actualiza el leg que la sostiene.
					#
					# Se comprueba `rowcount`: este es el único camino que devuelve
					# claimed=True, y hacerlo sin verificar que el UPDATE tocó la fila
					# sería un fail-open latente (hallazgo del coro). Hoy la fila no
					# puede desaparecer con `BEGIN IMMEDIATE`; se blinda igual.
					cur = conn.execute(
						"UPDATE stage_claims SET claimed_at = ?, ttl_seconds = ?, owner_originator = ?, intent = ? WHERE claim_key = ?",
						(stamp, ttl, str(originator or ""), intent, key),
					)
					if cur.rowcount != 1:
						conn.rollback()
						return ClaimResult(claimed=False, owner=owner, reason="error")
					conn.commit()
					return ClaimResult(claimed=True, owner=continuity_id, reason="owned", expires_at=expires)

				prev_expires = float(row["claimed_at"] or 0.0) + float(row["ttl_seconds"] or 0)
				if stamp < prev_expires:
					conn.rollback()
					return ClaimResult(claimed=False, owner=owner, reason="held_by_other", expires_at=prev_expires)

				# Expirado: se roba. El UPDATE re-comprueba la clave (misma TX).
				cursor = conn.execute(
					"UPDATE stage_claims SET owner_continuity_id = ?, owner_originator = ?, claimed_at = ?, "
					"ttl_seconds = ?, intent = ?, stage_path = ?, affinity_json = ?, branch = ?, worktree = ? "
					"WHERE claim_key = ?",
					(continuity_id, str(originator or ""), stamp, ttl, intent, stage_path, canon_json, str(branch or ""), str(worktree or ""), key),
				)
				if cursor.rowcount != 1:
					conn.rollback()
					return ClaimResult(claimed=False, owner=owner, reason="error")
				conn.commit()
				return ClaimResult(claimed=True, owner=continuity_id, reason="stolen_expired", expires_at=expires)
			except Exception:
				conn.rollback()
				raise
	except Exception as e:
		logger.warning(f"[stage-claims] fallo al reclamar {stage_path}: {e}")
		return ClaimResult(claimed=False, owner=None, reason="error")


# ── Renovación y liberación ─────────────────────────────────────────────────


def renew_claim(
	*,
	stage_path: str,
	affinity: object,
	branch: str,
	worktree: str,
	continuity_id: str,
	originator: str = "",
	ttl_seconds: int = DEFAULT_TTL_S,
	db_path: Optional[str] = None,
	now: Optional[float] = None,
) -> bool:
	"""Extiende el TTL de un claim propio (D9-a). False si no es nuestro o expiró.

	Renovar un claim ajeno **no** se permite ni siquiera si está expirado: eso
	sería un robo silencioso. Para robar hay que pasar por `try_claim_stage`, que
	deja la razón explícita (`stolen_expired`) y el dueño anterior en el log.

	Y **tampoco se renueva un claim propio ya expirado**: caducó, otro pudo
	robarlo y resucitarlo sería decidir por él. Se devuelve `False` y el llamante
	vuelve a reclamar (donde el robo queda explícito). El `WHERE` comprueba la
	vigencia en la MISMA sentencia: es CAS de una sola escritura, sin ventana
	leer→escribir (los `renew`/`release`/`purge` no necesitan `BEGIN IMMEDIATE`;
	verificado con el coro, 2026-10-28).
	"""
	if not stage_path or not continuity_id:
		return False
	stamp = float(now) if now is not None else time.time()
	try:
		key = claim_key(affinity, branch, worktree, stage_path)
		ttl = int(ttl_seconds) if int(ttl_seconds) > 0 else DEFAULT_TTL_S
	except Exception as e:
		logger.warning(f"[stage-claims] entrada inválida al renovar {stage_path!r}: {e}")
		return False
	try:
		with _connect(db_path) as conn:
			cur = conn.execute(
				"UPDATE stage_claims SET claimed_at = ?, ttl_seconds = ?, owner_originator = ? "
				"WHERE claim_key = ? AND owner_continuity_id = ? AND (claimed_at + ttl_seconds) >= ?",
				(stamp, ttl, str(originator or ""), key, continuity_id, stamp),
			)
			conn.commit()
			return int(cur.rowcount or 0) == 1
	except Exception as e:
		logger.warning(f"[stage-claims] fallo al renovar {stage_path}: {e}")
		return False


def release_claim(
	*,
	stage_path: str,
	affinity: object,
	branch: str,
	worktree: str,
	continuity_id: str,
	db_path: Optional[str] = None,
) -> bool:
	"""Suelta un claim propio. False si no era nuestro (no se roba al liberar)."""
	if not stage_path or not continuity_id:
		return False
	key = claim_key(affinity, branch, worktree, stage_path)
	try:
		with _connect(db_path) as conn:
			cur = conn.execute("DELETE FROM stage_claims WHERE claim_key = ? AND owner_continuity_id = ?", (key, continuity_id))
			conn.commit()
			return int(cur.rowcount or 0) == 1
	except Exception as e:
		logger.warning(f"[stage-claims] fallo al liberar {stage_path}: {e}")
		return False


def get_claim(
	*,
	stage_path: str,
	affinity: object,
	branch: str,
	worktree: str,
	db_path: Optional[str] = None,
) -> Optional[dict]:
	"""Lee el claim de una etapa (para diagnóstico/tablón). None si no hay."""
	key = claim_key(affinity, branch, worktree, stage_path)
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			row = conn.execute("SELECT * FROM stage_claims WHERE claim_key = ?", (key,)).fetchone()
		return dict(row) if row else None
	except Exception as e:
		logger.debug(f"[stage-claims] lectura falló: {e}")
		return None


def purge_expired(db_path: Optional[str] = None, *, now: Optional[float] = None) -> int:
	"""Retira claims caducados (D14). Devuelve cuántos borró."""
	stamp = float(now) if now is not None else time.time()
	try:
		with _connect(db_path) as conn:
			conn.execute(_TABLE_DDL)
			cur = conn.execute("DELETE FROM stage_claims WHERE (claimed_at + ttl_seconds) < ?", (stamp,))
			conn.commit()
			return int(cur.rowcount or 0)
	except Exception as e:
		logger.warning(f"[stage-claims] purga falló: {e}")
		return 0
