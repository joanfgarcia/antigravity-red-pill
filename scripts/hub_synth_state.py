#!/usr/bin/env python3
"""Estado de la síntesis de hubs, por sesión — read-only, una sola mirada.

El ciclo de sueño escribe o no escribe un hub por sesión, y hoy ese veredicto
solo se puede leer abriendo el tablero (una línea de WARNING agregada), el log
del sueño (sin sesión) o Qdrant a mano. Cuando una sesión no se escribe, la
pregunta que importa —**¿falló, o está esperando una fecha?**— exige cruzar el
marcador de los miembros (`hub_synth_reject_*`) con el `hub_input_hash` de hoy y
con las dos palancas de coste. Eso es lo que este script imprime.

Veredictos (espejo exacto de la compuerta de `_synthesize_one`):

- `hub`          — el hub existe con la versión vigente (nada pendiente).
- `stale`        — el hub existe, pero con versión vieja o truncado.
- `open`         — sin marcador, o el marcador es de OTRA entrada: paga hoy.
- `waiting`      — mismo input rechazado N veces y la ventana sigue viva;
	`remaining` dice cuántos días faltan para el intento.
- `expires_now`  — la ventana caducó (o el marcador es legacy sin fecha):
	paga UN intento en el ciclo siguiente.

Es un espejo, no un oráculo: no escribe nada y no sustituye al sueño. Sirve
para medir la noche (¿qué sesiones esperaban, hasta cuándo?) sin grep ni
consultas sueltas a mano. Si la compuerta cambia, este archivo cambia con ella.

Uso (desde la raíz del repo):
	`python scripts/hub_synth_state.py` (solo lo que no está sano) ·
	`--all` (todas las sesiones) · `--json` (para comparar dos noches).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

COLLECTIONS = ("work_memories", "social_memories")

FAILED_SIGNAL = "hub_synthesis_failed"
WAITING_SIGNAL = "hub_synthesis_waiting"


def gate_verdict(
	rej_hash: str,
	rej_count: int,
	ihash: str,
	age_days: Optional[float],
	max_rejections: int,
	window_days: float,
) -> Tuple[str, Optional[float]]:
	"""Qué hará la compuerta con esta entrada: `(veredicto, días restantes)`.

	Mismas condiciones que `hub_synthesis._synthesize_one`, incluida la trampa
	de la fecha: un marcador legacy SIN `hub_synth_reject_at` no puede probar la
	espera, así que cuenta como caducado (se gasta, no se pierde).
	"""
	if max_rejections <= 0 or rej_hash != ihash or rej_count < max_rejections:
		return "open", None
	if window_days <= 0:
		# Caducidad desactivada: la espera es indefinida (conducta previa a 2026-11-12).
		return "waiting", None
	if age_days is not None and age_days < window_days:
		return "waiting", max(0.0, window_days - age_days)
	return "expires_now", None


def _hub_payloads(memory_manager: Any, collection: str, ids: List[str]) -> Dict[str, Dict[str, Any]]:
	out: Dict[str, Dict[str, Any]] = {}
	for i in range(0, len(ids), 256):
		try:
			found = memory_manager.client.retrieve(
				collection_name=collection,
				ids=ids[i : i + 256],
				with_payload=True,
				with_vectors=False,
			)
		except Exception:
			continue
		for p in found:
			out[str(p.id)] = p.payload or {}
	return out


def collect(memory_manager: Any, collections: Tuple[str, ...], cfg: Any) -> List[Dict[str, Any]]:
	from red_pill.metabolism.hub_synthesis import (
		HUB_SYNTH_VERSION,
		_rejection_age_days,
		_rejection_marker,
		group_by_session,
		hub_input_hash,
		hub_point_id,
	)

	max_rejections = int(getattr(cfg, "SW_HUB_SYNTH_MAX_REJECTIONS", 2) or 0)
	window = float(getattr(cfg, "SW_HUB_SYNTH_WAIT_RETRY_DAYS", 7.0) or 0.0)
	rows: List[Dict[str, Any]] = []
	for collection in collections:
		try:
			if not memory_manager.client.collection_exists(collection):
				continue
		except Exception:
			continue
		points: List[Tuple[Any, Dict[str, Any]]] = []
		offset = None
		while True:
			batch, offset = memory_manager.client.scroll(collection, limit=1000, offset=offset, with_payload=True, with_vectors=False)
			points.extend((p.id, p.payload) for p in batch)
			if offset is None:
				break
		groups = {sid: mem for sid, mem in group_by_session(points).items() if len(mem) >= 2}
		hubs = _hub_payloads(memory_manager, collection, [hub_point_id(collection, sid) for sid in groups])
		for session_id, members in groups.items():
			ihash = hub_input_hash([pid for pid, _ in members])
			rej_hash, rej_count = _rejection_marker(members)
			age = _rejection_age_days(members)
			verdict, remaining = gate_verdict(rej_hash, rej_count, ihash, age, max_rejections, window)
			hub = hubs.get(str(hub_point_id(collection, session_id))) or {}
			if hub:
				if int(hub.get("hub_synth_version") or 0) >= HUB_SYNTH_VERSION and not bool(hub.get("hub_truncated")):
					verdict, remaining = "hub", None
				else:
					verdict, remaining = "stale", None
			rows.append(
				{
					"collection": collection,
					"session_id": session_id,
					"members": len(members),
					"hub": bool(hub),
					"verdict": verdict,
					"reject_count": rej_count,
					"reject_same_input": bool(rej_hash) and rej_hash == ihash,
					"reject_age_days": None if age is None else round(age, 2),
					"remaining_days": None if remaining is None else round(remaining, 2),
				}
			)
	rows.sort(key=lambda r: (r["verdict"] == "hub", r["collection"], r["session_id"]))
	return rows


def signals(memory_manager: Any) -> Dict[str, bool]:
	out: Dict[str, bool] = {}
	for name in (FAILED_SIGNAL, WAITING_SIGNAL):
		try:
			out[name] = bool(memory_manager.has_signal(name))
		except Exception:
			out[name] = False
	return out


def main() -> int:
	parser = argparse.ArgumentParser(description="Estado read-only de la síntesis de hubs por sesión.")
	parser.add_argument("--all", action="store_true", help="incluye las sesiones ya sanas (hub vigente)")
	parser.add_argument("--json", action="store_true", help="salida JSON (para comparar noches)")
	parser.add_argument("--collection", action="append", help="work_memories | social_memories (repetible)")
	args = parser.parse_args()

	from red_pill.config import get_config

	cfg = get_config()
	from red_pill.memory import MemoryManager

	manager = MemoryManager()
	rows = collect(manager, tuple(args.collection or COLLECTIONS), cfg)
	if not args.all:
		rows = [r for r in rows if r["verdict"] != "hub"]
	sig = signals(manager)
	levers = {
		"SW_HUB_SYNTH_MAX_REJECTIONS": int(getattr(cfg, "SW_HUB_SYNTH_MAX_REJECTIONS", 2) or 0),
		"SW_HUB_SYNTH_WAIT_RETRY_DAYS": float(getattr(cfg, "SW_HUB_SYNTH_WAIT_RETRY_DAYS", 7.0) or 0.0),
		"as_of": time.strftime("%Y-%m-%dT%H:%M:%S"),
	}

	if args.json:
		print(json.dumps({"levers": levers, "signals": sig, "sessions": rows}, indent=2, ensure_ascii=False))
		return 0

	print(
		f"compuerta: MAX_REJECTIONS={levers['SW_HUB_SYNTH_MAX_REJECTIONS']} · "
		f"WAIT_RETRY_DAYS={levers['SW_HUB_SYNTH_WAIT_RETRY_DAYS']:.0f} · {levers['as_of']}"
	)
	print(f"señales: {FAILED_SIGNAL}={sig[FAILED_SIGNAL]} · {WAITING_SIGNAL}={sig[WAITING_SIGNAL]}")
	if not rows:
		print("ninguna sesión pendiente: todas tienen hub vigente.")
		return 0
	print(f"{'VEREDICTO':<12} {'COLECCIÓN':<16} {'SESIÓN':<26} {'MIEM':>5} {'REJ':>4} {'EDAD':>6} {'RESTA':>6}")
	for r in rows:
		age = "—" if r["reject_age_days"] is None else f"{r['reject_age_days']:.1f}d"
		rema = "—" if r["remaining_days"] is None else f"{r['remaining_days']:.1f}d"
		mark = "*" if r["reject_same_input"] else " "
		print(
			f"{r['verdict']:<12} {r['collection']:<16} {r['session_id'][:24]:<26} {r['members']:>5} {r['reject_count']:>3}{mark} {age:>6} {rema:>6}"
		)
	counts: Dict[str, int] = {}
	for r in rows:
		counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
	print("resumen: " + " · ".join(f"{k}={v}" for k, v in sorted(counts.items())))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
