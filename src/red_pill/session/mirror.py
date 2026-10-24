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
_TURN_STATUSES = frozenset({"pending", "completed", "aborted"})

# provider → (módulo, clase, kwarg de aislamiento). `opencode` usa `db_path`, no
# `base_dir`: sin este mapa explícito, un `base_dir` pretendido acababa leyendo la
# BD viva del operador (y el `TypeError` se tragaba en silencio).
_SOURCE_CLASSES = {
	"opencode": ("red_pill.chronicle_sources.opencode", "OpencodeSourcePlugin", "db_path"),
	"claude_code": ("red_pill.chronicle_sources.claude_code", "ClaudeCodeSourcePlugin", "base_dir"),
	"pi": ("red_pill.chronicle_sources.pi", "PiSourcePlugin", "base_dir"),
	"antigravity": ("red_pill.chronicle_sources.antigravity", "AntigravitySourcePlugin", None),
}


_STUB_PREFIX = "[output purgado:"


def _max_turn_bytes() -> int:
	try:
		import red_pill.config as cfg

		return int(getattr(cfg.get_config(), "SESSION_MIRROR_MAX_TURN_BYTES", 262144))
	except Exception:
		return 262144


def _cap_text(value: Optional[str], cap: int) -> Optional[str]:
	if value is None:
		return None
	if len(value) <= cap:
		return value
	return value[:cap] + f"… [truncado {len(value) - cap} chars]"


def _cap_tool_calls_json(value: Any, cap: int) -> Optional[str]:
	if value is None:
		return None
	if not isinstance(value, list):
		raise ValueError("tool_calls debe ser una lista")
	raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
	if len(raw) <= cap:
		return raw
	# Se conservan id/nombre (lo que permite emparejar con `role=tool`) y se
	# sustituyen los argumentos gigantes por un marcador. Sigue siendo JSON válido.
	compact = []
	for call in value:
		if not isinstance(call, dict):
			continue
		fn = call.get("function") or {}
		args = fn.get("arguments")
		compact.append(
			{
				"id": call.get("id"),
				"type": call.get("type") or "function",
				"function": {
					"name": fn.get("name"),
					"arguments": f"[truncado {len(str(args))} chars]",
				},
			}
		)
	raw = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
	if len(raw) > cap:
		# Cola de llamadas enorme: se recorta la lista.
		while compact and len(json.dumps(compact, ensure_ascii=False, separators=(",", ":"))) > cap:
			compact.pop()
		raw = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
	return raw


def _json_tool_calls(value: Any) -> Optional[str]:
	return _cap_tool_calls_json(value, _max_turn_bytes())


def _coerce_ts(value: Any) -> float:
	try:
		ts = float(value)
	except (TypeError, ValueError):
		return 0.0
	return ts if ts > 0 else 0.0


class SessionMirror:
	"""Implementa `contracts.MirrorStore` sobre la misma `session.db` (schema v5)."""

	def __init__(self, db_path: Optional[str] = None):
		self.db_path = str(db_path) if db_path else str(get_session_db())
		SessionRegistry(self.db_path)  # dueño del esquema (migración v4)

	def _insert_turn(
		self,
		conn: Any,
		*,
		continuity_id: str,
		seq: int,
		mission_id: str,
		role: str,
		content: Optional[str],
		tool_calls: Optional[str],
		tool_call_id: Optional[str],
		model: Optional[str],
		ts: float,
		global_turn: int,
		originator: str,
		source: str,
		source_ref: Optional[str],
		request_id: Optional[str] = None,
		status: str = "completed",
		status_reason: Optional[str] = None,
	) -> bool:
		if status not in _TURN_STATUSES:
			raise ValueError(f"estado de turno desconocido: {status!r}")
		content = _cap_text(content, _max_turn_bytes())
		cur = conn.execute(
			"""
			INSERT OR IGNORE INTO session_mirror (
				continuity_id, mission_id, global_turn, seq, role, content, tool_calls,
				tool_call_id, model, ts, originator, source, source_ref,
				request_id, status, status_reason
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
				request_id,
				status,
				status_reason,
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
		request_id: Optional[str] = None,
		status: str = "completed",
		status_reason: Optional[str] = None,
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
				request_id=request_id,
				status=status,
				status_reason=status_reason,
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
			"request_id": request_id,
			"status": status,
			"status_reason": status_reason,
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
					request_id=turn.get("request_id"),
					status=str(turn.get("status") or "completed"),
					status_reason=turn.get("status_reason"),
				)
				if ok:
					inserted += 1
				else:
					seq -= 1
			conn.commit()
		return inserted

	def _turn_by_source_ref(self, continuity_id: str, originator: str, source_ref: str) -> Optional[dict]:
		with connect_session_db(self.db_path) as conn:
			row = conn.execute(
				"SELECT * FROM session_mirror WHERE continuity_id=? AND originator=? AND source_ref=?",
				(continuity_id, originator, source_ref),
			).fetchone()
		return dict(row) if row else None

	def begin_turn(
		self,
		*,
		continuity_id: str,
		mission_id: str,
		request_id: str,
		content: str,
		originator: str,
		source: str,
		model: Optional[str] = None,
		global_turn: int = 0,
		source_ref: Optional[str] = None,
		ts: Optional[float] = None,
	) -> dict:
		"""Escribe el user en `pending` o devuelve el turno ya existente."""
		request = str(request_id or "").strip()
		if not request:
			raise ValueError("request_id requerido")
		ref = str(source_ref or f"{request}:user")
		created = self.append_turn(
			continuity_id=continuity_id,
			mission_id=mission_id,
			role="user",
			content=content,
			model=model,
			ts=ts,
			global_turn=global_turn,
			originator=originator,
			source=source,
			source_ref=ref,
			request_id=request,
			status="pending",
		)
		if created is not None:
			return created
		existing = self._turn_by_source_ref(continuity_id, originator, ref)
		if existing is None:
			raise RuntimeError("begin_turn: no se pudo leer el turno existente")
		return existing

	def complete_turn(self, *, continuity_id: str, request_id: str) -> int:
		"""Marca completed todo el grupo del turno; no reabre un aborted."""
		continuity = str(continuity_id or "").strip()
		request = str(request_id or "").strip()
		if not continuity or not request:
			return 0
		with connect_session_db(self.db_path) as conn:
			cur = conn.execute(
				"UPDATE session_mirror SET status='completed', status_reason=NULL "
				"WHERE continuity_id=? AND request_id=? AND status!='aborted'",
				(continuity, request),
			)
			conn.commit()
			return int(cur.rowcount or 0)

	def abort_turn(
		self,
		*,
		continuity_id: str,
		request_id: str,
		reason: str,
		partial_response: Optional[str] = None,
		mission_id: Optional[str] = None,
	) -> int:
		"""Marca aborted el grupo; guarda una respuesta parcial si la hay."""
		continuity = str(continuity_id or "").strip()
		request = str(request_id or "").strip()
		if not continuity or not request:
			return 0
		if partial_response:
			mission = str(mission_id or "").strip() or "mission:pending"
			self.append_turn(
				continuity_id=continuity,
				mission_id=mission,
				role="assistant",
				content=partial_response,
				originator="",
				source="",
				source_ref=f"{request}:partial",
				request_id=request,
				status="aborted",
				status_reason=str(reason)[:500],
			)
		with connect_session_db(self.db_path) as conn:
			cur = conn.execute(
				"UPDATE session_mirror SET status='aborted', status_reason=? "
				"WHERE continuity_id=? AND request_id=?",
				(str(reason or "aborted")[:500], continuity, request),
			)
			conn.commit()
			return int(cur.rowcount or 0)

	def pending_turns(
		self,
		continuity_id: Optional[str] = None,
		*,
		include_aborted: bool = True,
		max_age_s: Optional[int] = None,
	) -> List[dict]:
		"""Turnos pending (y opcionalmente aborted) para inspección/resume."""
		statuses = ["pending", "aborted"] if include_aborted else ["pending"]
		placeholders = ",".join("?" * len(statuses))
		sql = f"SELECT * FROM session_mirror WHERE status IN ({placeholders})"
		params: List[Any] = list(statuses)
		if continuity_id:
			sql += " AND continuity_id=?"
			params.append(str(continuity_id).strip())
		if max_age_s is not None:
			sql += " AND ts >= ?"
			params.append(time.time() - max(0, int(max_age_s)))
		sql += " ORDER BY ts ASC"
		with connect_session_db(self.db_path) as conn:
			rows = conn.execute(sql, tuple(params)).fetchall()
		return [dict(row) for row in rows]

	def expire_pending_turns(self, *, max_age_s: int, continuity_id: Optional[str] = None) -> int:
		"""TTL: pending viejo → aborted con reason=ttl (no borra historial)."""
		cutoff = time.time() - max(0, int(max_age_s))
		sql = "UPDATE session_mirror SET status='aborted', status_reason='ttl' WHERE status='pending' AND ts < ?"
		params: List[Any] = [cutoff]
		if continuity_id:
			sql += " AND continuity_id=?"
			params.append(str(continuity_id).strip())
		with connect_session_db(self.db_path) as conn:
			cur = conn.execute(sql, tuple(params))
			conn.commit()
			return int(cur.rowcount or 0)

	def read_turns(
		self,
		continuity_id: str,
		*,
		since_seq: int = 0,
		limit: Optional[int] = None,
		statuses: Optional[List[str]] = None,
	) -> List[dict]:
		"""Turnos del alma en orden de `seq`; por defecto solo los completados.

		`statuses=None` ⇒ `["completed"]` para que el replay nunca inyecte un turno
		pending/aborted. Para auditoría, pasar `statuses=["pending", "aborted"]` o
		usar `pending_turns()`.
		"""
		continuity = str(continuity_id or "").strip()
		if not continuity:
			return []
		selected = ["completed"] if statuses is None else [str(s) for s in statuses]
		if not selected:
			return []
		if any(status not in _TURN_STATUSES for status in selected):
			raise ValueError(f"estado de turno desconocido en statuses: {selected!r}")
		placeholders = ",".join("?" * len(selected))
		sql = f"SELECT * FROM session_mirror WHERE continuity_id = ? AND seq > ? AND status IN ({placeholders}) ORDER BY seq ASC"
		params: List[Any] = [continuity, int(since_seq or 0), *selected]
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
				"SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending_rows, "
				"SUM(CASE WHEN status='aborted' THEN 1 ELSE 0 END) AS aborted_rows, "
				"MIN(CASE WHEN ts > 0 THEN ts END) AS oldest_ts, "
				"MIN(CASE WHEN status='pending' THEN ts END) AS oldest_pending_ts, "
				"MAX(ts) AS newest_ts FROM session_mirror"
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
		budget = int(getattr(cfg.get_config(), "SESSION_MIRROR_MAX_BYTES", 104857600))
		used = db_bytes + wal_bytes
		return {
			"rows": int(row["rows"] or 0),
			"souls": int(row["souls"] or 0),
			"dated_rows": int(row["dated_rows"] or 0),
			"undated_rows": int(row["rows"] or 0) - int(row["dated_rows"] or 0),
			"oldest_ts": float(row["oldest_ts"]) if row["oldest_ts"] is not None else None,
			"newest_ts": float(row["newest_ts"]) if row["newest_ts"] is not None else None,
			"pending_rows": int(row["pending_rows"] or 0),
			"aborted_rows": int(row["aborted_rows"] or 0),
			"oldest_pending_ts": float(row["oldest_pending_ts"]) if row["oldest_pending_ts"] is not None else None,
			"active_souls": active_souls,
			"dead_souls": dead_souls,
			"orphan_souls": orphan_souls,
			"dead_rows": dead_rows,
			"orphan_rows": orphan_rows,
			"unknown_age_souls": unknown_age_souls,
			"expired_candidates": expired_candidates,
			"db_bytes": db_bytes,
			"wal_bytes": wal_bytes,
			"budget_bytes": budget,
			"budget_pct": round(100.0 * used / budget, 2) if budget > 0 else 0.0,
			"over_budget": used > budget,
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

	def _db_bytes(self) -> int:
		import os

		total = 0
		for suffix in ("", "-wal"):
			try:
				total += os.path.getsize(self.db_path + suffix)
			except OSError:
				pass
		return total

	def stub_tool_results(self, *, retention_days: Optional[float] = None, keep_per_soul: Optional[int] = None) -> dict:
		"""Sustituye el CONTENIDO de resultados de tools viejos por un marcador.

		Conserva `tool_calls` (qué se ejecutó) y el `tool_call_id` (pareja válida):
		solo se pierde el volcado del output. Se stubbean los que están fuera de
		los últimos `keep_per_soul` **y** son más viejos que `retention_days`; un
		resultado reciente nunca se toca, aunque haya muchos.
		"""
		import red_pill.config as cfg

		app_cfg = cfg.get_config()
		days = float(retention_days) if retention_days is not None else float(getattr(app_cfg, "SESSION_MIRROR_TOOL_RETENTION_DAYS", 7))
		keep = int(keep_per_soul) if keep_per_soul is not None else int(getattr(app_cfg, "SESSION_MIRROR_KEEP_TOOL_RESULTS", 200))
		cutoff = time.time() - max(0.0, days) * 86400.0
		stubbed = 0
		saved = 0
		with connect_session_db(self.db_path) as conn:
			souls = conn.execute("SELECT DISTINCT continuity_id FROM session_mirror").fetchall()
			for soul in souls:
				cid = str(soul["continuity_id"])
				rows = conn.execute(
					"SELECT id, content, ts FROM session_mirror WHERE continuity_id = ? AND role = 'tool' ORDER BY seq DESC",
					(cid,),
				).fetchall()
				for index, row in enumerate(rows):
					if index < keep:
						continue
					content = row["content"]
					if not content or str(content).startswith(_STUB_PREFIX):
						continue
					ts = float(row["ts"] or 0.0)
					if ts <= 0 or ts >= cutoff:
						continue
					marker = f"{_STUB_PREFIX} {len(content)} chars]"
					conn.execute("UPDATE session_mirror SET content = ? WHERE id = ?", (marker, int(row["id"])))
					stubbed += 1
					saved += max(0, len(content) - len(marker))
			conn.commit()
			if stubbed:
				try:
					conn.execute("VACUUM")
				except sqlite3.OperationalError:
					pass
		return {"rows_stubbed": stubbed, "chars_saved": saved}

	def enforce_budget(self, *, max_bytes: Optional[int] = None, min_turns_per_soul: Optional[int] = None) -> dict:
		"""Garantiza el techo: stub → purga de muertos → recorte de viejos activos.

		Nunca recorta por debajo de `min_turns_per_soul` en un alma activa. Si aun
		así no cabe (patológico), devuelve `over_budget=True` y el janitor emite
		dolor; no se destruye contexto reciente para "cuadrar" el número.
		"""
		import red_pill.config as cfg

		app_cfg = cfg.get_config()
		budget = int(max_bytes) if max_bytes is not None else int(getattr(app_cfg, "SESSION_MIRROR_MAX_BYTES", 104857600))
		min_turns = int(min_turns_per_soul) if min_turns_per_soul is not None else int(getattr(app_cfg, "SESSION_MIRROR_MIN_TURNS_PER_SOUL", 200))
		before = self._db_bytes()
		result: Dict[str, Any] = {
			"before_bytes": before,
			"budget_bytes": budget,
			"over_budget": before > budget,
			"emergency": False,
			"rows_trimmed": 0,
		}
		if before <= budget:
			return result
		result["stub"] = self.stub_tool_results()
		result["purge"] = self.purge()
		after = self._db_bytes()
		if after > budget:
			result["emergency"] = True
			active = set(SessionRegistry(self.db_path).active_continuities())
			removed = 0
			with connect_session_db(self.db_path) as conn:
				souls = conn.execute("SELECT continuity_id, COUNT(*) AS n FROM session_mirror GROUP BY continuity_id").fetchall()
				for soul in souls:
					cid = str(soul["continuity_id"])
					n = int(soul["n"])
					if cid in active:
						excess = n - min_turns
						if excess <= 0:
							continue
						cur = conn.execute(
							"DELETE FROM session_mirror WHERE id IN "
							"(SELECT id FROM session_mirror WHERE continuity_id = ? ORDER BY seq ASC LIMIT ?)",
							(cid, excess),
						)
					else:
						cur = conn.execute("DELETE FROM session_mirror WHERE continuity_id = ?", (cid,))
					removed += int(cur.rowcount or 0)
				conn.commit()
				if removed:
					try:
						conn.execute("VACUUM")
					except sqlite3.OperationalError:
						pass
			result["rows_trimmed"] = removed
			after = self._db_bytes()
		result["after_bytes"] = after
		result["over_budget"] = after > budget
		return result


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
