"""The declared mood: a datum the Operator gives, not one the system infers.

RFC-AFE-001, D-01. Vocabulary: fondo = declared mood, letra = mood code; see
`docs/CORE/GLOSSARY.md`.

Mood has two axes and the system only had one. The **fragment** (what a turn
expresses) can be read from text; the **declared mood** (how the Operator is) can
not: measured 2026-11-14, in 10 of 14 days the fragment was flat while his mood was
not, and aggregating the fragment by day got it right 4 of 14. So the mood is
**asked** and stored as given; the machine does not guess it.

Decisions this module implements:

- **One record per installation, not per session.** `continuity_id` is per-leg (6
- rows, 6 ids in the register): storing it "per soul" would give one mood per tab,
- which is the opposite of D-02 ("you are the same in every session"). No key.
- **Natural day, not a rolling window.** Declared yesterday at 23:55 and read today
- at 11:50 it says `ayer` — not "today" with 11.9 h of age, which is the defect this
- RFC fixes.
- **No decay in F1.** The *Fading Affect Bias* in `data/affect_models.yaml` scales
- engram erosion per colour; it is not a law of mood: it has no tau and no units.
- F1 only reports freshness (today / yesterday / before / none). Decay is F3, D-04.
- **Serialized write.** `flock` + unique `tmp` + a monotonicity guard: three live
- sessions write the same file, and an old declaration must not overwrite a newer one
- (silent lost update).

Renamed from `core/affect_fondo.py` per `docs/CORE/LANGUAGE_POLICY.md`: the module
name, the state file and the exception were half-breed tokens. The legacy file name
and the legacy `letra` payload key are still **read** and are rewritten on the next
write, so no history is lost and nothing has to be migrated by hand.
"""

from __future__ import annotations

import fcntl
import functools
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

FILENAME = "declared_mood.json"
LOCKNAME = "declared_mood.lock"
LEGACY_FILENAME = "affect_fondo.json"
HISTORY_MAX = 10

# Accepted codes; the canonical datum (emotion, colour, label) lives in YAML.
MOOD_CODES = ("B", "C", "F", "T", "X", "-")

NO_SIGNAL = "ÁNIMO — fondo: sin señal (pregúntale cómo está hoy antes de empujar trabajo)"


class DeclaredMoodLocked(RuntimeError):
	"""The declaration is older than the one in force, so it is not applied.

	It exists so the CLI never says "saved" when nothing was saved (the adversarial
	caught it: with the clock ahead the operator asked for F and got "C saved",
	exit 0).
	"""

	def __init__(self, in_force: Dict[str, Any]):
		super().__init__(f"declaración más reciente en vigor: {code_of(in_force)}")
		self.in_force = in_force


def _state_dir() -> Path:
	from red_pill.core.paths import get_state_dir

	return get_state_dir()


def path() -> Path:
	return _state_dir() / FILENAME


def legacy_path() -> Path:
	return _state_dir() / LEGACY_FILENAME


@functools.lru_cache(maxsize=1)
def letters() -> Dict[str, Dict[str, str]]:
	"""Table code → {emotion, color, label}; `{}` when the YAML cannot be read.

	Cached: `get_current_sync_state` queries it every turn. It never raises: a missing
	mood datum must not take a turn down (doctrine of this module).
	"""
	import yaml

	yml = Path(__file__).resolve().parent.parent / "data" / "affect_letters.yaml"
	try:
		with open(yml, "r", encoding="utf-8") as fh:
			data = yaml.safe_load(fh) or {}
		return {str(k): dict(v or {}) for k, v in data.items()}
	except Exception:
		return {}


def code_of(record: Optional[Dict[str, Any]]) -> str:
	"""The mood code of a record, accepting the legacy `letra` key.

	`letra` was the Spanish field written by every declaration until 8.4.x; records
	on disk still carry it and history entries are never rewritten (history is not
	reworded).
	"""
	if not record:
		return "-"
	return str(record.get("code") or record.get("letra") or "-")


def normalize(value: str) -> str:
	clean = str(value or "").strip().upper()
	if clean in ("", "NONE", "NADA", "N"):
		return "-"
	if clean not in MOOD_CODES:
		raise ValueError(f"código de ánimo inválido: {value!r} (válidos: {', '.join(MOOD_CODES)})")
	return clean


def _as_datetime(ts: float) -> datetime:
	return datetime.fromtimestamp(ts)


def _same_day(ts: float, now_ts: Optional[float] = None) -> bool:
	"""Same NATURAL day (local time of the installation), not a rolling 24 h window."""
	current = float(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())
	return _as_datetime(ts).date() == _as_datetime(current).date()


def _valid_ts(value: Any) -> Optional[float]:
	"""`declared_at` counts only if it is a positive number: null/0/'' is no datum."""
	try:
		ts = float(value)
	except (TypeError, ValueError):
		return None
	return ts if ts > 0 else None


def _is_today(record: Dict[str, Any], now_ts: Optional[float] = None) -> bool:
	"""Same NATURAL day in the declarer's zone, not in the reader's.

	`declared_local` (YYYY-MM-DD) is stored on write, so a CLI with a different `TZ`
	cannot change the answer to "is this from today?" (the adversarial caught it).

	The reference clock is `now_ts` when the caller passes it: `read(now=...)` and
	`describe(now=...)` exist to look at a specific instant, and comparing
	`declared_local` against the wall clock ignored that instant (the byte-exact
	contract test went red just by changing the day).
	"""
	local = str(record.get("declared_local") or "")
	if local:
		current = float(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())
		return local == _as_datetime(current).strftime("%Y-%m-%d")
	ts = _valid_ts(record.get("declared_at"))
	if ts is None:
		return False
	return _same_day(ts, now_ts)


def _read_raw(source: Optional[Path] = None) -> Optional[Dict[str, Any]]:
	try:
		raw = (source or path()).read_text(encoding="utf-8")
		data = json.loads(raw)
		if not isinstance(data, dict) or not (data.get("code") or data.get("letra")):
			return None
		return data
	except (OSError, ValueError, TypeError):
		# Corrupt or absent is "no signal", never an exception inside a turn.
		return None


def _read_any() -> Optional[Dict[str, Any]]:
	"""Current record, falling back to the legacy file name during the rename."""
	return _read_raw() or _read_raw(legacy_path())


def read(now: Optional[float] = None) -> Optional[Dict[str, Any]]:
	"""Current record with `age_h` and `es_hoy` added; `None` when there is none."""
	record = _read_any()
	if not record:
		return None
	ts = _valid_ts(record.get("declared_at"))
	if ts is None:
		return None
	current = float(now if now is not None else datetime.now(timezone.utc).timestamp())
	record = dict(record)
	record["code"] = code_of(record)
	record["age_h"] = round(max(0.0, (current - ts) / 3600.0), 1)
	record["es_hoy"] = _is_today(record, current)
	return record


def write(
	code: str,
	*,
	note: str = "",
	by: str = "operator",
	now: Optional[float] = None,
) -> Dict[str, Any]:
	"""Store an Operator declaration and return the resulting record.

	- Validates the code (ValueError when it does not exist).
	- Takes a file lock: several sessions may declare at once.
	- Monotonicity guard: a declaration with an older timestamp does NOT overwrite
	- the one in force (a resumed session cannot rewind the mood).
	"""
	clean = normalize(code)
	ts = float(now if now is not None else datetime.now(timezone.utc).timestamp())
	record: Dict[str, Any] = {
		"code": clean,
		"note": str(note or "")[:280],
		"declared_at": ts,
		"declared_local": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
		"updated_by": str(by or "operator")[:60],
	}

	directory = _state_dir()
	directory.mkdir(parents=True, exist_ok=True)
	lock_path = directory / LOCKNAME
	with open(lock_path, "w", encoding="utf-8") as lock:
		fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
		try:
			previous = _read_any() or {}
			history: List[Dict[str, Any]] = list(previous.get("history") or [])
			try:
				previous_ts = float(previous.get("declared_at") or 0)
			except (TypeError, ValueError):
				previous_ts = 0.0
			if previous_ts > ts:
				raise DeclaredMoodLocked(read(now=ts) or dict(previous, es_hoy=True, age_h=0.0))
			if code_of(previous) != "-":
				history.append({"code": code_of(previous), "declared_at": previous_ts, "by": previous.get("updated_by")})
			record["history"] = history[-HISTORY_MAX:]
			payload = json.dumps(record, ensure_ascii=False, indent=1)
			fd, tmp = tempfile.mkstemp(dir=str(directory), prefix=".declared_mood.", suffix=".tmp")
			try:
				with os.fdopen(fd, "w", encoding="utf-8") as fh:
					fh.write(payload)
				os.replace(tmp, path())
			finally:
				if os.path.exists(tmp):
					os.unlink(tmp)
			if legacy_path().exists():
				legacy_path().unlink()
		finally:
			fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
	return read(now=ts) or dict(record, es_hoy=True, age_h=0.0)


def describe(record: Optional[Dict[str, Any]], now: Optional[float] = None) -> str:
	"""The three block texts, byte-exact (contract of F1).

	- today  → `ÁNIMO — fondo: C · cansancio · declarado hoy 08:12 (hace 3.2 h)`
	- before → `ÁNIMO — fondo: B · bien · declarado ayer 21:40 — puede no ser de hoy`
	- none   → `ÁNIMO — fondo: sin señal (pregúntale cómo está hoy antes de empujar trabajo)`

	These strings are the interface layer (`LANGUAGE_POLICY` §3): they will be
	rendered per locale, and `es` must stay byte-identical when that happens.
	"""
	if not record:
		return NO_SIGNAL
	code = code_of(record)
	table = letters().get(code, {})
	label = table.get("label") or code
	ts = _valid_ts(record.get("declared_at"))
	if ts is None:
		return NO_SIGNAL
	current = float(now if now is not None else datetime.now(timezone.utc).timestamp())
	declared = _as_datetime(ts)
	if _is_today(record, current):
		age = round(max(0.0, (current - ts) / 3600.0), 1)
		return f"ÁNIMO — fondo: {code} · {label} · declarado hoy {declared.strftime('%H:%M')} (hace {age:.1f} h)"
	days = (_as_datetime(current).date() - declared.date()).days
	day = "ayer" if days == 1 else declared.strftime("%d-%m")
	return f"ÁNIMO — fondo: {code} · {label} · declarado {day} {declared.strftime('%H:%M')} — puede no ser de hoy"


def enabled() -> bool:
	"""Whether the declared mood is on. `DECLARED_MOOD_ENABLED`, legacy name accepted.

	The legacy key is still read because a `.env` that nobody updated must not turn
	the feature off in silence — a rename that changes behaviour without saying so is
	the failure this whole commit is about.
	"""
	import red_pill.config as cfg

	current = bool(getattr(cfg, "DECLARED_MOOD_ENABLED", False))
	legacy = bool(getattr(cfg, "AFFECT_FONDO_ENABLED", False))
	return current or legacy


def block(now: Optional[float] = None) -> str:
	"""Awakening block; empty string when the feature is off."""
	if not enabled():
		return ""
	return describe(read(now=now), now=now)
