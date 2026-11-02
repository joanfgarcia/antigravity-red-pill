"""Reconciliación del dolor (RFC-OBS-005, P0 report-only).

El auditor inyecta una señal por finding (`sync_to_thalamus`) y nada la entierra
cuando su causa desaparece: cuatro señales a 9–10 sobrevivieron días a su causa
(2026-11-02). Este módulo cierra el ciclo: al final de una ronda, sabe qué
segmentos miraron y qué emitieron, y calcula qué señales del auditor ya no
sostiene nadie.

P0 no borra: **report-only**. Calcula, cuenta ausencias y deja el artefacto en
`state/auditor_round.json` para que el Operador vea qué habría hecho y con qué
edad. La evaporación real es P1, tras dos semanas de este modo.

Guardas (§4.5 del RFC), todas obligatorias:

- sin veredicto no hay borrado: un segmento que lanza, se salta o está deshabilitado preserva sus nombres;
- los eventos (`reconcilable: false`) no se reconcilian;
- solo se tocan señales con `signal_source="SentinelAuditor"`;
- una ronda incompleta no reconcilia;
- hacen falta `reconcile.absences` rondas consecutivas sin emisión.

Toda la política (interruptor, report-only, ausencias, gracia) se lee del YAML
(`configs/signals/signal_profiles.yaml`), no de constantes de código.
"""

import fcntl
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

logger = logging.getLogger(__name__)

AUDITOR_SOURCE = "SentinelAuditor"
ROUND_FILE = "auditor_round.json"
ABSENCES_FILE = "signal_absences.json"

VERDICT_OK = "ok"
VERDICT_SKIPPED = "skipped"
VERDICT_ERROR = "error"
VERDICT_DISABLED = "disabled"


@dataclass
class SegmentResult:
	"""Un trozo de ronda: qué miró, qué veredicto dio y qué nombres protege."""

	segment: str
	verdict: str
	emitted: Set[str] = field(default_factory=set)
	preserved: Set[str] = field(default_factory=set)

	@property
	def has_verdict(self) -> bool:
		return self.verdict == VERDICT_OK


@dataclass
class AuditRound:
	"""Una pasada del auditor. Solo se reconcilia si `complete` es True."""

	round_id: str
	started_at: float = field(default_factory=time.time)
	segments: List[SegmentResult] = field(default_factory=list)
	complete: bool = False

	def record(self, segment: str, verdict: str, emitted: Iterable[str] = (), preserved: Iterable[str] = ()) -> None:
		self.segments.append(SegmentResult(segment, verdict, set(emitted), set(preserved)))

	def emitted(self) -> Set[str]:
		names: Set[str] = set()
		for seg in self.segments:
			if seg.has_verdict:
				names |= seg.emitted
		return names

	def preserved(self) -> Set[str]:
		names: Set[str] = set()
		for seg in self.segments:
			names |= seg.preserved
			if not seg.has_verdict:
				names |= seg.emitted  # lo que no dio veredicto, se protege entero
		return names

	def verdicts(self) -> Dict[str, str]:
		return {seg.segment: seg.verdict for seg in self.segments}


def _state_dir() -> Path:
	from red_pill.core.paths import get_state_dir

	return get_state_dir()


def _load_json(path: Path) -> Dict[str, Any]:
	try:
		data = json.loads(path.read_text(encoding="utf-8"))
		return data if isinstance(data, dict) else {}
	except Exception:
		return {}


def _save_json(path: Path, data: Dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _lock(path: Path):
	"""Lock exclusivo por fichero: dos auditorías solapadas no reconcilian dos veces."""
	path.parent.mkdir(parents=True, exist_ok=True)
	handle = open(path, "a+", encoding="utf-8")
	fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
	return handle


def reconcile(
	round_: AuditRound,
	memory: Any = None,
	*,
	policy: Optional[Dict[str, Any]] = None,
	state_dir: Optional[Path] = None,
	now: Optional[float] = None,
) -> Dict[str, Any]:
	"""Calcula (y en P1 ejecuta) el entierro de las señales del auditor.

	Devuelve el informe de la ronda. En `report_only` no borra nada: deja en el
	artefacto lo que habría evaporado.
	"""
	from red_pill.metabolism.signal_profiles import load_catalog

	catalog = load_catalog()
	cfg = dict(catalog.reconcile_policy())
	if policy:
		cfg.update(policy)

	state = state_dir or _state_dir()
	report: Dict[str, Any] = {
		"round_id": round_.round_id,
		"started_at": round_.started_at,
		"finished_at": now or time.time(),
		"complete": round_.complete,
		"verdicts": round_.verdicts(),
		"report_only": bool(cfg["report_only"]),
		"emitted": sorted(round_.emitted()),
		"preserved": sorted(round_.preserved()),
		"candidates": [],
		"absent": [],
		"would_evaporate": [],
		"evaporated": [],
	}

	if not cfg["enabled"]:
		report["skipped"] = "disabled"
		_save_json(state / ROUND_FILE, report)
		return report
	if not round_.complete:
		report["skipped"] = "incomplete_round"
		logger.info("[RECONCILE] ronda incompleta: no se reconcilia")
		_save_json(state / ROUND_FILE, report)
		return report

	if memory is None:
		from red_pill.memory import MemoryManager

		memory = MemoryManager()

	emitted = round_.emitted()
	preserved = round_.preserved()
	candidates = {s.get("name") for s in memory.signals_by_source(AUDITOR_SOURCE) if s.get("name")}
	candidates = {n for n in candidates if catalog.is_reconcilable(str(n))}
	report["candidates"] = sorted(candidates)

	resto = candidates - emitted - preserved
	report["absent"] = sorted(resto)

	absences = _load_json(state / ABSENCES_FILE)
	threshold = int(cfg["absences"])
	for name in candidates:
		if name in resto:
			absences[name] = int(absences.get(name, 0)) + 1
		else:
			absences.pop(name, None)  # emitida o preservada: la cuenta vuelve a cero
	due = sorted(n for n in resto if absences.get(n, 0) >= threshold)
	report["would_evaporate"] = due

	logger.info(
		f"[RECONCILE] ronda {round_.round_id} {'completa' if round_.complete else 'incompleta'}"
		f" · segmentos {report['verdicts']} · candidatas {len(candidates)}"
		f" · emitidas {len(emitted)} · ausentes {len(resto)}"
	)
	for name in sorted(resto):
		logger.info(f"[RECONCILE] ausencia {absences.get(name, 0)}/{threshold}: {name}")

	if due and not cfg["report_only"]:
		for name in due:
			payload: Dict[str, Any] = next(
				(s for s in memory.signals_by_source(AUDITOR_SOURCE) if s.get("name") == name), {}
			)
			deleted = memory.evaporate_signals(name)
			if deleted:
				report["evaporated"].append(
					{
						"name": name,
						"intensity": payload.get("intensity"),
						"age_hours": payload.get("age_hours"),
						"round": round_.round_id,
					}
				)
				logger.warning(
					f"[RECONCILE] evaporada {name} ({payload.get('intensity')}, edad {payload.get('age_hours')} h)"
					f" — {absences.get(name, 0)} rondas"
				)
				absences.pop(name, None)
			else:
				logger.error(f"[RECONCILE] pidió evaporar {name} y borró 0: ¿Qdrant? no se toca el contador")
	elif due:
		for name in due:
			logger.info(f"[RECONCILE] report-only: evaporaría {name} tras {absences.get(name, 0)} rondas")

	_save_json(state / ABSENCES_FILE, absences)
	_save_json(state / ROUND_FILE, report)
	return report
