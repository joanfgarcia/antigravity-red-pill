#!/usr/bin/env python3
"""Benchmark del interceptor 12_session_sync (ALMA_Y_CORO_CIERRE · etapa B2).

Mide el coste REAL de `execute()` en los TRES modos (silent/minimal/header)
contra el estado vivo del Búnker — directorio de latidos y `session.db`
reales — que es la condición más cargada razonable: sin Qdrant, sin LLM,
sin subprocess.

Dos escenarios por modo, porque el interceptor cachea el digest con TTL:

- **cold** (`SESSION_SYNC_TTL_S` ínfimo): la caché nunca acierta → cada
llamada paga el camino largo (iterdir de latidos + SELECTs del registro).
Este es el que debe caber en el presupuesto; es el peor caso por turno.
- **warm** (TTL de producción): dentro del TTL → coste de servir de memoria.

Y dos cargas, porque con UNA sesión viva el número sale bonito pero no dice
nada del diseño (esto es un coro):

- **estado REAL del Búnker**: los latidos y el `session.db` de verdad.
- **coro SINTÉTICO**: `XDG_DATA_HOME` redirigido a un tmp, sembrado con 24
sesiones vivas en 4 misiones y 40 eventos pendientes (el COUNT del aviso,
estresado). No se toca el estado del Operador; el tmp se borra al salir
(`--no-stress` lo omite).

El modo se fuerza por la vía de producción: variable de entorno + recarga de
la config (`SESSION_SYNC_MODE`). No se muta ningún estado interno del plugin
(ni su caché): los seams privados `_mode()`/`_live_signals()` solo se leen
para validar y para el banner de carga.

Las muestras NO se recortan. La primera llamada de cada modo —la que
construye el `SessionRegistry`— entra en la distribución y además se
reporta aparte como `boot` (es un coste por proceso, no por turno).

Exit code:
- 0 → los tres modos caben en el presupuesto (p99 < 20 ms por defecto).
- 1 → al menos un p99 supera el presupuesto. La decisión de subirlo es del
Operador, no de este script.
- 2 → medición INVÁLIDA: el digest degradó a "" o el modo no se pudo forzar.
Un interceptor roto es rapidísimo; no se acepta como verde.

Uso:
	PYTHONPATH=<repo>/src python scripts/bench_interceptor_session_sync.py [--iters 300] [--budget 20] [--no-stress]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import logging
import math
import os
import platform
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

MODULE = "red_pill.interceptors.12_session_sync"
MODES = ("silent", "minimal", "header")
MIN_ITERS = 200
DEFAULT_ITERS = 300
DEFAULT_BUDGET_MS = 20.0
STRESS_SESSIONS = 24  # coro sintético: el doble de vivo que el estado real de hoy
STRESS_EVENTS = 40  # pendientes en MI misión: el COUNT del aviso, estresado
_TTL_COLD_S = "0.000000001"
_TTL_WARM_S = "300"
PROMPT = "¿qué tal va el turno?"  # el interceptor ignora el contenido: cualquier turno vale


class InvalidMeasurement(RuntimeError):
	"""El número medido no representa el camino real: fuera, no se relaja."""


class _FailureDetector(logging.Handler):
	"""Cuenta CUALQUIER log del plugin: el módulo solo registra por caminos de
	fallo (degradar a "", registro/latidos/global_turn no disponibles, aviso de
	pendientes roto). Un interceptor que falla en silencio es rapidísimo y no
	puede salir verde."""

	def __init__(self):
		super().__init__(level=logging.DEBUG)
		self.hits: int = 0
		self.samples: list[str] = []

	def emit(self, record: logging.LogRecord) -> None:
		self.hits += 1
		if len(self.samples) < 3:
			self.samples.append(f"{record.levelname}: {record.getMessage()}")


def _plugin_module():
	return importlib.import_module(MODULE)


def _set_config(**flags: str) -> None:
	"""Fija flags de config por la vía de producción (env + recarga del singleton)."""
	import red_pill.config as cfg

	for name, value in flags.items():
		os.environ[name] = value
	cfg.get_config.cache_clear()
	_cfg = cfg.get_config()
	for name, value in flags.items():
		actual = getattr(_cfg, name)
		if str(actual) == str(value):
			continue
		try:
			if float(actual) == float(value):  # un float de pydantic no se reimprime igual (1e-09)
				continue
		except (TypeError, ValueError):
			pass
		raise InvalidMeasurement(f"{name} no se pudo fijar a {value!r} (vale {actual!r})")


def _percentile(sorted_ms: list[float], p: float) -> float:
	"""Percentil por rango más cercano (hacia arriba).

	Sin interpolar: interpolar suaviza la cola, y lo que decide el presupuesto
	es exactamente la cola."""
	idx = max(0, min(len(sorted_ms) - 1, math.ceil(p / 100.0 * len(sorted_ms)) - 1))
	return sorted_ms[idx]


def _stats(samples: list[float]) -> dict:
	s = sorted(samples)
	return {
		"n": len(s),
		"p50": _percentile(s, 50),
		"p95": _percentile(s, 95),
		"p99": _percentile(s, 99),
		"mean": statistics.fmean(s),
		"max": s[-1],
	}


def _load_report() -> dict:
	"""Carga del estado real: sin esto los milisegundos no se interpretan.

	Las cifras se leen por los MISMOS seams que usa el plugin (latidos y
	registro), así que el banner describe el I/O que se está midiendo."""
	from red_pill.core.session_liveness import list_sessions
	from red_pill.session.store import SessionRegistry

	mod = _plugin_module()
	registry = SessionRegistry()
	rows = registry.list_sessions(limit=200)
	return {
		"heartbeats": len(list_sessions()),
		"registry_rows": len(rows),
		"global_turn": registry.get_max_global_turn(),
		"other_live": len(mod.SessionSyncPlugin()._live_signals()),
	}


def _seed_stress(sessions: int, events: int) -> str:
	"""Siembra el estado sintético (ya redirigido a un tmp) y devuelve MI originator."""
	from red_pill.core.session_liveness import touch_session
	from red_pill.session.store import SessionRegistry

	mine = "opencode:ses_bench_mia"
	providers = ("opencode", "claude", "dag", "pi")
	missions = ("repo:next", "mission:alma", "repo:stream", "mission:coro")
	roles = ("task", "job", "orchestrator")

	registry = SessionRegistry()
	registry.upsert_session(
		originator=mine,
		continuity_id="01a18156-0000-7000-0000-000000000000",
		mission_id="repo:next",
		role="task",
		last_seen_event_seq=0,
	)
	touch_session("opencode", "ses_bench_mia", "start")
	for i in range(sessions):
		provider = providers[i % len(providers)]
		session_id = f"ses_bench_{i:03d}"
		registry.upsert_session(
			originator=f"{provider}:{session_id}",
			continuity_id=f"01a18156-0000-7000-0000-{i:012d}",
			mission_id=missions[i % len(missions)],
			role=roles[i % len(roles)],
			last_seen_event_seq=0,
		)
		touch_session(provider, session_id, "start")
		if i % 3 == 0:  # un tercio ya cerró turno: "alguien ha tocado", no está en vuelo
			touch_session(provider, session_id, "end")
	for k in range(events):
		registry.add_event(
			event_type="phase_done",
			mission_id="repo:next",
			summary=f"evento de estrés {k} para el COUNT del aviso de pendientes",
			global_turn=k + 1,
		)
	for _ in range(events):  # el reloj global de turnos, también andado (no 0 sintético)
		registry.next_global_turn(mine)
	return mine


@contextlib.contextmanager
def _stress_state(sessions: int, events: int):
	"""Estado sintético AISLADO: XDG_DATA_HOME a un tmp, se siembra, se mide, se borra.

	El estado real del Operador no se toca: la única diferencia con el escenario
	anterior es cuántas sesiones hay vivas y cuántos eventos pendientes."""
	# `pop` captura y quita en una sola operación: no es una lectura XDG para
	# RESOLVER rutas (lo que prohíbe la convención), sino aislar el entorno para
	# medir con estado sintético y restaurarlo después.
	prev_data = os.environ.pop("XDG_DATA_HOME", None)
	prev_orig = os.environ.get("REDPILL_ORIGINATOR")
	root = Path(tempfile.mkdtemp(prefix="bench-session-sync-"))
	try:
		os.environ["XDG_DATA_HOME"] = str(root)
		os.environ["REDPILL_ORIGINATOR"] = _seed_stress(sessions, events)
		yield _load_report()
	finally:
		if prev_data is None:
			os.environ.pop("XDG_DATA_HOME", None)
		else:
			os.environ["XDG_DATA_HOME"] = prev_data
		if prev_orig is None:
			os.environ.pop("REDPILL_ORIGINATOR", None)
		else:
			os.environ["REDPILL_ORIGINATOR"] = prev_orig
		shutil.rmtree(root, ignore_errors=True)


async def _loop(plugin, iters: int) -> tuple[list[float], str]:
	"""`iters` llamadas medidas sobre UNA instancia viva, como en producción."""
	samples: list[float] = []
	text = ""
	for _ in range(iters):
		t0 = time.perf_counter()
		text = await plugin.execute(PROMPT)
		samples.append((time.perf_counter() - t0) * 1000.0)
	return samples, text


def _raise_if_plugin_failed(mode: str, detector: _FailureDetector) -> None:
	if detector.hits:
		raise InvalidMeasurement(
			f"{mode}: el plugin registró {detector.hits} fallo(s) internos (degrada en silencio → el número medido no vale): {detector.samples[0]}"
		)


async def _bench_mode(mode: str, iters: int, detector: _FailureDetector) -> dict:
	mod = _plugin_module()
	_set_config(SESSION_SYNC_MODE=mode, SESSION_SYNC_TTL_S=_TTL_COLD_S)
	if mod._mode() != mode:
		raise InvalidMeasurement(f"modo {mode!r} no resuelto (got {mod._mode()!r})")

	plugin = mod.SessionSyncPlugin()
	# silent: cero I/O y ni siquiera se mira la caché → un solo escenario.
	cold_samples, cold_text = await _loop(plugin, iters)
	_raise_if_plugin_failed(mode, detector)
	if mode != "silent":
		if not cold_text.strip():
			raise InvalidMeasurement(f"{mode}: el digest cold salió vacío — no se está midiendo nada real")
		if "SYNC" not in cold_text:
			raise InvalidMeasurement(f"{mode}: el digest cold no parece el bloque esperado: {cold_text[:80]!r}")

	warm_samples: list[float] = []
	if mode != "silent":
		_set_config(SESSION_SYNC_MODE=mode, SESSION_SYNC_TTL_S=_TTL_WARM_S)
		await plugin.execute(PROMPT)  # rellena la caché
		warm_samples, warm_text = await _loop(plugin, iters)
		_raise_if_plugin_failed(mode, detector)
		if not warm_text.strip():
			raise InvalidMeasurement(f"{mode}: el digest warm salió vacío")

	return {
		"mode": mode,
		"cold": _stats(cold_samples),
		"warm": _stats(warm_samples) if warm_samples else None,
		"boot_ms": cold_samples[0],
		"sample_text": cold_text,
	}


def _print_report(title: str, tag: str, results: list[dict], load: dict, iters: int, budget: float) -> list[str]:
	print()
	print(f"═══ 12_session_sync · {title} ═══")
	print(f"host: {platform.node()} · python {platform.python_version()} · kernel {platform.release()}")
	print(f"iteraciones por escenario: {iters} · presupuesto p99: {budget:.1f} ms")
	print(
		f"carga real medida: {load['heartbeats']} latidos · {load['registry_rows']} filas de registro · "
		f"global_turn={load['global_turn']} · otras sesiones vivas: {load['other_live']}"
	)
	print(f"originator de esta sesión: {os.getenv('REDPILL_ORIGINATOR') or '(sin env)'}")
	print()
	header = f"{'modo':<9}{'escenario':<10}{'n':>5}{'p50':>9}{'p95':>9}{'p99':>9}{'media':>9}{'max':>9}"
	line = "-" * len(header)
	print(header)
	print(line)
	for r in results:
		for scenario in ("cold", "warm"):
			s = r[scenario]
			if not s:
				continue
			print(f"{r['mode']:<9}{scenario:<10}{s['n']:>5}{s['p50']:>9.3f}{s['p95']:>9.3f}{s['p99']:>9.3f}{s['mean']:>9.3f}{s['max']:>9.3f}")
	print(line)
	print("(milisegundos · percentil por rango más cercano, sin recortar muestras)")
	print()
	print("boot (primera llamada, incluye construir el SessionRegistry; coste por proceso):")
	for r in results:
		print(f"  {r['mode']:<9}{r['boot_ms']:>9.3f} ms")
	print()
	print("digest de muestra (header, tal cual sale del interceptor):")
	sample = next((r["sample_text"] for r in results if r["mode"] == "header" and r["sample_text"]), "")
	for ln in sample.splitlines() or ["(vacío)"]:
		print(f"  {ln}")
	print()

	failed: list[str] = []
	for r in results:
		worst = max([r["cold"]["p99"]] + ([r["warm"]["p99"]] if r["warm"] else []))
		verdict = "CUMPLE" if worst <= budget else "SUPERA"
		if worst > budget:
			failed.append(f"{tag}/{r['mode']}")
		print(f"  {r['mode']:<9} p99 = {worst:>8.3f} ms  → {verdict} del presupuesto ({budget:.1f} ms)")
	return failed


def _measure_all(iters: int, detector: _FailureDetector) -> list[dict]:
	return [asyncio.run(_bench_mode(mode, iters, detector)) for mode in MODES]


def main() -> int:
	parser = argparse.ArgumentParser(description="Mide la latencia del interceptor 12_session_sync.")
	parser.add_argument("--iters", type=int, default=DEFAULT_ITERS, help=f"iteraciones por escenario (mín. {MIN_ITERS})")
	parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET_MS, help="presupuesto p99 en ms (default 20)")
	parser.add_argument("--stress-sessions", type=int, default=STRESS_SESSIONS, help="sesiones vivas del coro sintético")
	parser.add_argument("--stress-events", type=int, default=STRESS_EVENTS, help="eventos pendientes del coro sintético")
	parser.add_argument("--no-stress", action="store_true", help="omite el escenario de coro sintético aislado")
	args = parser.parse_args()

	if args.iters < MIN_ITERS:
		parser.error(f"--iters debe ser >= {MIN_ITERS} (el plan exige N>=200 por modo)")

	detector = _FailureDetector()
	logger = logging.getLogger(MODULE)
	logger.addHandler(detector)
	logger.setLevel(logging.DEBUG)
	logger.propagate = False  # los fallos del plugin no se mezclan con el log de consola

	failed: list[str] = []
	try:
		load = _load_report()
		failed += _print_report("estado REAL del Búnker", "real", _measure_all(args.iters, detector), load, args.iters, args.budget)
		if not args.no_stress:
			with _stress_state(args.stress_sessions, args.stress_events) as syn_load:
				failed += _print_report(
					f"coro SINTÉTICO aislado ({args.stress_sessions} sesiones vivas, tmp)",
					"stress",
					_measure_all(args.iters, detector),
					syn_load,
					args.iters,
					args.budget,
				)
	except InvalidMeasurement as e:
		print(f"\n[bench] MEDICIÓN INVÁLIDA: {e}", file=sys.stderr)
		print("[bench] NO se relaja la medición: arreglar el interceptor y volver a medir.", file=sys.stderr)
		return 2

	if failed:
		names = ", ".join(sorted(set(failed)))
		print(f"\n[bench] KO: {names} supera el presupuesto de {args.budget:.1f} ms (p99).")
		print("[bench] La decisión de subir el presupuesto es del Operador: se reporta el número real.")
		return 1
	print(f"\n[bench] OK: los tres modos caben en {args.budget:.1f} ms (p99), con el estado real y con el coro sintético lleno.")
	return 0


if __name__ == "__main__":
	sys.exit(main())
