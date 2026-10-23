"""Espejo canónico de turnos (`session_mirror`, Fase 1a).

El registro (`store.SessionRegistry`) dice QUIÉN es cada leg; el espejo guarda
QUÉ se dijo, en formato portable (`role/content/tool_calls/tool_call_id/model/ts`)
para poder reencarnar el alma en otro cuerpo sin re-ejecutar lo hecho.

Poblado desde los transcripts de cada arnés reutilizando `chronicle_sources/*`
(la ruta Memento no cambia: `load_canonical` es aditivo). La idempotencia la da
`(continuity_id, originator, source_ref)`: re-sincronizar el mismo transcript no
duplica turnos.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional

from red_pill.core.paths import get_session_db
from red_pill.session.store import SessionRegistry, _clean_key, connect_session_db

logger = logging.getLogger(__name__)

CANONICAL_ROLES = frozenset({"system", "user", "assistant", "tool"})

# provider → (módulo, clase, kwarg de aislamiento). `opencode` usa `db_path`, no
# `base_dir`: sin este mapa explícito, un `base_dir` pretendido acababa leyendo la
# BD viva del operador (y el `TypeError` se tragaba en silencio).
_SOURCE_CLASSES = {
	"opencode": ("red_pill.chronicle_sources.opencode", "OpencodeSourcePlugin", "db_path"),
	"claude_code": ("red_pill.chronicle_sources.claude_code", "ClaudeCodeSourcePlugin", "base_dir"),
	"pi": ("red_pill.chronicle_sources.pi", "PiSourcePlugin", "base_dir"),
	"antigravity": ("red_pill.chronicle_sources.antigravity", "AntigravitySourcePlugin", None),
}


def _json_tool_calls(value: Any) -> Optional[str]:
	if value is None:
		return None
	if not isinstance(value, list):
		raise ValueError("tool_calls debe ser una lista")
	return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _coerce_ts(value: Any) -> float:
	try:
		ts = float(value)
	except (TypeError, ValueError):
		return 0.0
	return ts if ts > 0 else 0.0


class SessionMirror:
	"""Implementa `contracts.MirrorStore` sobre la misma `session.db` (schema v4)."""

	def __init__(self, db_path: Optional[str] = None):
		self.db_path = str(db_path) if db_path else str(get_session_db())
		SessionRegistry(self.db_path)  # dueño del esquema (migración v4)

	def _insert_turn(self, conn: Any, *, continuity_id: str, seq: int, mission_id: str, role: str, content: Optional[str], tool_calls: Optional[str], tool_call_id: Optional[str], model: Optional[str], ts: float, global_turn: int, originator: str, source: str, source_ref: Optional[str]) -> bool:
		cur = conn.execute(
			"""
			INSERT OR IGNORE INTO session_mirror (
				continuity_id, mission_id, global_turn, seq, role, content, tool_calls,
				tool_call_id, model, ts, originator, source, source_ref
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
			""",
			(
				continuity_id,
				mission_id,
				int(global_turn or 0),
				seq,
				role,
				content,
				tool_calls,
				tool_call_id,
				model,
				ts,
				originator,
				source,
				source_ref,
			),
		)
		return bool(cur.rowcount)

	def append_turn(
		self,
		*,
		continuity_id: str,
		mission_id: str,
		role: str,
		content: Optional[str] = None,
		tool_calls: Optional[List[dict]] = None,
		tool_call_id: Optional[str] = None,
		model: Optional[str] = None,
		ts: Optional[float] = None,
		global_turn: int = 0,
		originator: str = "",
		source: str = "",
		source_ref: Optional[str] = None,
	) -> Optional[dict]:
		"""Añade UN turno al espejo; `None` si ya existía (`source_ref` repetido)."""
		continuity = str(continuity_id or "").strip()
		if not continuity:
			raise ValueError("continuity_id requerido")
		mission = _clean_key(mission_id)
		if not mission:
			raise ValueError("mission_id requerido")
		if role not in CANONICAL_ROLES:
			raise ValueError(f"rol canónico desconocido: {role!r}")
		tool_json = _json_tool_calls(tool_calls)
		stamp = time.time() if ts is None else _coerce_ts(ts)
		with connect_session_db(self.db_path) as conn:
			conn.execute("BEGIN IMMEDIATE")
			row = conn.execute(
				"SELECT COALESCE(MAX(seq), 0) AS m FROM session_mirror WHERE continuity_id = ?",
				(continuity,),
			).fetchone()
			seq = int(row["m"]) + 1
			inserted = self._insert_turn(
				conn,
				continuity_id=continuity,
				seq=seq,
				mission_id=mission,
				role=role,
				content=content,
				tool_calls=tool_json,
				tool_call_id=tool_call_id,
				model=model,
				ts=stamp,
				global_turn=global_turn,
				originator=str(originator or ""),
				source=str(source or ""),
				source_ref=source_ref,
			)
			conn.commit()
		if not inserted:
			return None
		return {
			"continuity_id": continuity,
			"mission_id": mission,
			"global_turn": int(global_turn or 0),
			"seq": seq,
			"role": role,
			"content": content,
			"tool_calls": tool_calls,
			"tool_call_id": tool_call_id,
			"model": model,
			"ts": stamp,
			"originator": str(originator or ""),
			"source": str(source or ""),
			"source_ref": source_ref,
		}

	def append_turns(
		self,
		continuity_id: str,
		turns: List[dict],
		*,
		mission_id: str,
		originator: str = "",
		source: str = "",
		model: Optional[str] = None,
		global_turn: int = 0,
	) -> int:
		"""Añade una lista de turnos canónicos en UNA transacción; devuelve insertados."""
		continuity = str(continuity_id or "").strip()
		if not continuity:
			raise ValueError("continuity_id requerido")
		default_mission = _clean_key(mission_id)
		if not default_mission:
			raise ValueError("mission_id requerido")
		inserted = 0
		with connect_session_db(self.db_path) as conn:
			conn.execute("BEGIN IMMEDIATE")
			row = conn.execute(
				"SELECT COALESCE(MAX(seq), 0) AS m FROM session_mirror WHERE continuity_id = ?",
				(continuity,),
			).fetchone()
			seq = int(row["m"])
			for turn in turns:
				role = str(turn.get("role") or "")
				if role not in CANONICAL_ROLES:
					continue
				seq += 1
				ok = self._insert_turn(
					conn,
					continuity_id=continuity,
					seq=seq,
					mission_id=_clean_key(turn.get("mission_id")) or default_mission,
					role=role,
					content=turn.get("content"),
					tool_calls=_json_tool_calls(turn.get("tool_calls")),
					tool_call_id=turn.get("tool_call_id"),
					model=turn.get("model") or model,
					ts=_coerce_ts(turn.get("ts")),
					global_turn=int(turn.get("global_turn") or global_turn or 0),
					originator=str(turn.get("originator") or originator or ""),
					source=str(turn.get("source") or source or ""),
					source_ref=turn.get("source_ref"),
				)
				if ok:
					inserted += 1
				else:
					seq -= 1
			conn.commit()
		return inserted

	def read_turns(
		self,
		continuity_id: str,
		*,
		since_seq: int = 0,
		limit: Optional[int] = None,
	) -> List[dict]:
		"""Turnos del alma en orden de `seq` (con `tool_calls` ya deserializados)."""
		continuity = str(continuity_id or "").strip()
		if not continuity:
			return []
		sql = "SELECT * FROM session_mirror WHERE continuity_id = ? AND seq > ? ORDER BY seq ASC"
		params: List[Any] = [continuity, int(since_seq or 0)]
		if limit is not None:
			sql += " LIMIT ?"
			params.append(max(1, min(int(limit), 5000)))
		with connect_session_db(self.db_path) as conn:
			rows = conn.execute(sql, tuple(params)).fetchall()
		turns: List[dict] = []
		for row in rows:
			turn = dict(row)
			raw_calls = turn.get("tool_calls")
			if raw_calls:
				try:
					parsed = json.loads(raw_calls)
				except json.JSONDecodeError:
					parsed = None
				turn["tool_calls"] = parsed if isinstance(parsed, list) else None
			else:
				turn["tool_calls"] = None
			turns.append(turn)
		return turns

	def count_turns(self, continuity_id: str) -> int:
		with connect_session_db(self.db_path) as conn:
			row = conn.execute(
				"SELECT COUNT(*) AS n FROM session_mirror WHERE continuity_id = ?",
				(str(continuity_id or "").strip(),),
			).fetchone()
		return int(row["n"]) if row else 0

	def last_seq(self, continuity_id: str) -> int:
		with connect_session_db(self.db_path) as conn:
			row = conn.execute(
				"SELECT COALESCE(MAX(seq), 0) AS m FROM session_mirror WHERE continuity_id = ?",
				(str(continuity_id or "").strip(),),
			).fetchone()
		return int(row["m"]) if row else 0

	# ── Ciclo de vida y observabilidad (TTL + monitorización, AD-060) ───────
	def stats(self, *, retention_days: Optional[float] = None) -> dict:
		"""Métricas medibles del espejo (janitor + CLI `session mirror stats`).

		No purga nada. `dead_souls`/`orphan_souls` son la señal de trabajo para la
		retención; `undated_rows` son turnos sin `ts` fiable (backfill incompleto).
		"""
		import os

		import red_pill.config as cfg

		days = float(retention_days) if retention_days is not None else float(getattr(cfg.get_config(), "SESSION_MIRROR_RETENTION_DAYS", 30))
		cutoff = time.time() - max(0.0, days) * 86400.0
		with connect_session_db(self.db_path) as conn:
			row = conn.execute(
				"SELECT COUNT(*) AS rows, COUNT(DISTINCT continuity_id) AS souls, "
				"SUM(CASE WHEN ts > 0 THEN 1 ELSE 0 END) AS dated_rows, "
				"MIN(CASE WHEN ts > 0 THEN ts END) AS oldest_ts, MAX(ts) AS newest_ts "
				"FROM session_mirror"
			).fetchone()
			per_soul = conn.execute(
				"SELECT continuity_id, COUNT(*) AS turns, MAX(ts) AS last_ts, "
				"SUM(CASE WHEN ts = 0 THEN 1 ELSE 0 END) AS undated "
				"FROM session_mirror GROUP BY continuity_id"
			).fetchall()
			registry_rows = conn.execute(
				"SELECT continuity_id, MAX(CASE WHEN ttl_state != 'expired' THEN 1 ELSE 0 END) AS has_active, "
				"MAX(updated_at) AS last_updated FROM session_registry GROUP BY continuity_id"
			).fetchall()
		registry = {str(r["continuity_id"]): r for r in registry_rows}
		active_souls = dead_souls = orphan_souls = dead_rows = orphan_rows = 0
		unknown_age_souls = expired_candidates = 0
		for soul in per_soul:
			cid = str(soul["continuity_id"])
			info = registry.get(cid)
			is_active = bool(info and info["has_active"])
			is_orphan = info is None
			if is_active:
				active_souls += 1
				continue
			if is_orphan:
				orphan_souls += 1
				orphan_rows += int(soul["turns"])
			else:
				dead_souls += 1
				dead_rows += int(soul["turns"])
			last_ts = float(soul["last_ts"] or 0.0)
			if last_ts <= 0:
				unknown_age_souls += 1
			elif last_ts < cutoff:
				expired_candidates += 1
		try:
			db_bytes = os.path.getsize(self.db_path)
		except OSError:
			db_bytes = 0
		try:
			wal_bytes = os.path.getsize(self.db_path + "-wal")
		except OSError:
			wal_bytes = 0
		return {
			"rows": int(row["rows"] or 0),
			"souls": int(row["souls"] or 0),
			"dated_rows": int(row["dated_rows"] or 0),
			"undated_rows": int(row["rows"] or 0) - int(row["dated_rows"] or 0),
			"oldest_ts": float(row["oldest_ts"]) if row["oldest_ts"] is not None else None,
			"newest_ts": float(row["newest_ts"]) if row["newest_ts"] is not None else None,
			"active_souls": active_souls,
			"dead_souls": dead_souls,
			"orphan_souls": orphan_souls,
			"dead_rows": dead_rows,
			"orphan_rows": orphan_rows,
			"unknown_age_souls": unknown_age_souls,
			"expired_candidates": expired_candidates,
			"db_bytes": db_bytes,
			"wal_bytes": wal_bytes,
			"retention_days": days,
			"retention_cutoff_ts": cutoff,
		}

	def purge(self, registry: Optional[SessionRegistry] = None, *, retention_days: Optional[float] = None) -> dict:
		"""Purga CONSERVADORA: solo almas sin ningún leg activo y más viejas que el TTL.

		Un alma activa no pierde turnos (ni antiguos): el coste de un purgado
		demasiado agresivo es mayor que el de esperar métricas. Los turnos sin `ts`
		fiable se conservan y se reportan (`unknown_age_souls`). Nunca toca el
		registro ni `mission_events`.
		"""
		import red_pill.config as cfg

		reg = registry or SessionRegistry(self.db_path)
		days = float(retention_days) if retention_days is not None else float(getattr(cfg.get_config(), "SESSION_MIRROR_RETENTION_DAYS", 30))
		cutoff = time.time() - max(0.0, days) * 86400.0
		active = set(reg.active_continuities())
		purged_rows = purged_souls = 0
		with connect_session_db(self.db_path) as conn:
			souls = conn.execute(
				"SELECT continuity_id, COUNT(*) AS turns, MAX(ts) AS last_ts FROM session_mirror GROUP BY continuity_id"
			).fetchall()
			for soul in souls:
				cid = str(soul["continuity_id"])
				if cid in active:
					continue
				last_ts = float(soul["last_ts"] or 0.0)
				if last_ts <= 0 or last_ts >= cutoff:
					continue
				# Solo turnos CON fecha y viejos: un turno sin `ts` nunca se borra por
				# edad (se conserva y se reporta). El NOT EXISTS re-verifica "sin leg
				# activo" dentro de la misma transacción: un leg que despierte entre el
				# snapshot y el DELETE no pierde su espejo (carrera cerrada).
				cur = conn.execute(
					"DELETE FROM session_mirror WHERE continuity_id = ? AND ts > 0 AND ts < ? "
					"AND NOT EXISTS (SELECT 1 FROM session_registry WHERE continuity_id = ? AND ttl_state != 'expired')",
					(cid, cutoff, cid),
				)
				if cur.rowcount:
					purged_rows += int(cur.rowcount)
					purged_souls += 1
			conn.commit()
			if purged_rows:
				try:
					conn.execute("VACUUM")
				except sqlite3.OperationalError:
					pass
		return {
			"rows_purged": purged_rows,
			"souls_purged": purged_souls,
			"retention_days": days,
			"retention_cutoff_ts": cutoff,
		}


def _source_plugin(provider: str, base_dir: Optional[str] = None) -> Any:
	entry = _SOURCE_CLASSES.get(str(provider or "").strip())
	if not entry:
		return None
	import importlib

	module_name, class_name, isolation_kwarg = entry
	cls = getattr(importlib.import_module(module_name), class_name)
	if base_dir and isolation_kwarg:
		return cls(**{isolation_kwarg: base_dir})
	return cls()


class SessionSourceNotFound(LookupError):
	"""El provider del leg no tiene fuente de transcripts canónicos."""


def sync_originator(
	mirror: SessionMirror,
	*,
	originator: str,
	continuity_id: str,
	mission_id: str,
	provider: Optional[str] = None,
	base_dir: Optional[str] = None,
	model: Optional[str] = None,
) -> int:
	"""Vuelca el transcript de UN leg al espejo (idempotente). Devuelve insertados.

	`provider` por defecto se deduce del prefijo de `originator`
	(`opencode:<sesión>`). Un provider sin fuente canónica lanza
	`SessionSourceNotFound` para que el llamante lo trate como deuda, no como
	"0 turnos" silencioso.
	"""
	origin = str(originator or "").strip()
	if ":" not in origin:
		raise ValueError("originator debe ser `provider:session_id`")
	prov, _, session_id = origin.partition(":")
	prov = str(provider or prov)
	plugin = _source_plugin(prov, base_dir=base_dir)
	if plugin is None:
		raise SessionSourceNotFound(prov)
	turns = plugin.load_canonical(session_id)
	return mirror.append_turns(
		continuity_id,
		turns,
		mission_id=mission_id,
		originator=origin,
		source=prov,
		model=model,
	)


def sync_registry(
	mirror: SessionMirror,
	registry: Optional[SessionRegistry] = None,
	*,
	continuity_id: Optional[str] = None,
	originator: Optional[str] = None,
	base_dirs: Optional[Dict[str, str]] = None,
) -> List[dict]:
	"""Backfill fail-soft: sincroniza los legs del registro y resume por leg.

	Cada leg falla por separado (transcript ausente, provider sin fuente): el
	resultado lo declara (`error`) y los demás continúan.
	"""
	reg = registry or SessionRegistry(mirror.db_path)
	if continuity_id:
		rows = reg.get_by_continuity(str(continuity_id))
	elif originator:
		row = reg.get_by_originator(str(originator))
		rows = [row] if row else []
	else:
		rows = reg.list_sessions(limit=500)
	report: List[dict] = []
	for row in rows:
		origin = str(row.get("originator") or "")
		entry = {"originator": origin, "provider": row.get("provider"), "inserted": 0, "error": None}
		if ":" not in origin:
			entry["error"] = "sin cuerpo compuesto"
			report.append(entry)
			continue
		if row.get("ttl_state") == "expired":
			entry["error"] = "leg expirado"
			report.append(entry)
			continue
		try:
			entry["inserted"] = sync_originator(
				mirror,
				originator=origin,
				continuity_id=str(row.get("continuity_id") or ""),
				mission_id=str(row.get("mission_id") or ""),
				provider=row.get("provider"),
				base_dir=(base_dirs or {}).get(str(row.get("provider"))),
			)
		except Exception as e:
			entry["error"] = str(e)
			logger.warning(f"[SessionMirror] sync {origin}: {e}")
		report.append(entry)
	return report
