#!/usr/bin/env python3
"""Contador del backlog de Memento: qué quedó sin destilar tras el pase nocturno.

El tope `MEMENTO_AGENTIC_NIGHT_LIMIT` evita que una noche de pico monopolice el
LLM, pero deja sesiones fuera. Sin un contador visible, ese resto es invisible:
parece que "todo está al día" cuando hay N esperando.

Este paso cierra el chronicle (después de distill/annotate) y:

- cuenta las sesiones que siguen pendientes (`pending_agentic`, la misma
	selección que usa el pase; el contador es acumulativo porque lo que no se
	procesa sigue en la cola), **partidas por motivo**: destilado
	(`missing|stale|redistill`, lo que el tope raciona) y notas (`annotate`, que no
	compite por el tope y se auto-cura en la pasada siguiente);
- emite/actualiza la señal `memento_backlog` con el número de las que faltan por
	**destilar** y la edad de la más antigua de esas (clase `sed`: escala con el
	tiempo y su acantilado son los 30 días del tope duro del buffer — cuando
	cruza, la señal pasa a SYSTEM-FAILURE). Las notas pendientes no encienden la
	señal: no tienen acantilado de buffer;
- la evapora cuando no queda nada por destilar.

Motivo (2026-11-18): una sesión ya destilada cuyas notas faltan entraba en el
mismo contador, así que el WARNING decía "3 sin destilar" sobre material al día.

Uso:
	scripts/report_memento_backlog.py            # emite/actualiza la señal
	scripts/report_memento_backlog.py --dry-run  # solo cuenta (sin tocar Qdrant)
	scripts/report_memento_backlog.py --json     # salida estructurada
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SIGNAL = "memento_backlog"


def _epoch(iso: Any) -> Optional[float]:
	"""Epoch UTC de un `created_at` ISO del registry.

	El registry guarda `...Z`. Parsearlo con `strptime` + `mktime` lo leía como
	hora LOCAL, así que la edad salía inflada por el desfase del huso (medido:
	+3.600–7.201 s en las 1.486 entradas vivas con `created_at`), justo contra el
	acantilado de 30 d de la clase `sed`. Misma lectura que
	`ascension._session_created_at`.
	"""
	try:
		return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
	except Exception:
		return None


def compute(registry: Any, root: Path) -> Dict[str, Any]:
	"""Cuenta los pendientes por motivo y la edad del destilado más antiguo.

	`annotate` no entra en la edad ni en el conteo de "sin destilar": esa sesión
	ya tiene polaroids de este hash y lo que le falta son las notas.
	"""
	from red_pill.memento.agentic import pending_agentic

	pending = list(pending_agentic(registry, root=root, force=False, redistill_since=None))
	by_reason: Dict[str, int] = {}
	más_vieja: Optional[float] = None
	for source, session_id, reason in pending:
		by_reason[reason] = by_reason.get(reason, 0) + 1
		if reason == "annotate":
			continue
		entry = (registry.state.get("registry", {}).get(source, {}) or {}).get(session_id) or {}
		ts = _epoch(entry.get("created_at"))
		if ts is None:
			continue
		más_vieja = ts if más_vieja is None else min(más_vieja, ts)
	age_days = round((time.time() - más_vieja) / 86400, 1) if más_vieja else None
	notas = by_reason.get("annotate", 0)
	return {
		"pending": len(pending),
		"distill_pending": len(pending) - notas,
		"annotate_pending": notas,
		"by_reason": by_reason,
		"oldest_days": age_days,
	}


def report(counts: Dict[str, Any], *, cap: int, msg_cap: int = 0, memory: Any = None, dry_run: bool = False) -> Dict[str, Any]:
	"""Emite/actualiza o evapora la señal según lo que falte por DESTILAR."""
	total = int(counts.get("pending") or 0)
	notas = int(counts.get("annotate_pending") or 0)
	n = int(counts.get("distill_pending", total - notas))
	oldest = counts.get("oldest_days")
	out = {
		"pending": total,
		"distill_pending": n,
		"annotate_pending": notas,
		"oldest_days": oldest,
		"cap": cap,
		"msg_cap": msg_cap,
		"signal": "none",
	}
	if n <= 0:
		if memory is not None and not dry_run:
			memory.evaporate_signals(SIGNAL)
			out["signal"] = "evaporated"
		return out
	if memory is not None and not dry_run:
		edad = f" · la más antigua hace {oldest} d" if oldest else ""
		cola = f" Aparte, {notas} sesión(es) solo esperan notas (no compiten por el tope)." if notas else ""
		memory.inject_signal(
			name=SIGNAL,
			intensity=4.0,
			signal_type="pain",
			source="Nightly",
			message=(
				f"{n} sesión(es) sin destilar tras el pase (tope {cap} sesiones / {msg_cap} mensajes por noche{edad}). "
				f"Quedan para la siguiente; el contador es acumulativo.{cola}"
			),
			originator=f"memento_backlog ({n} pendientes)",
		)
		out["signal"] = "injected"
	return out


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--dry-run", action="store_true", help="solo cuenta; no toca Qdrant")
	parser.add_argument("--json", action="store_true", help="salida JSON")
	args = parser.parse_args()

	import red_pill.config as cfg
	from red_pill.memento import get_memento_root
	from red_pill.memento.registry import MementoRegistry

	registry = MementoRegistry()
	counts = compute(registry, get_memento_root())
	cap = int(getattr(cfg, "MEMENTO_AGENTIC_NIGHT_LIMIT", 0))
	msg_cap = int(getattr(cfg, "MEMENTO_AGENTIC_NIGHT_MSG_LIMIT", 0))
	memory = None
	if not args.dry_run:
		try:
			from red_pill.memory import MemoryManager

			memory = MemoryManager()
		except Exception as exc:  # sin Qdrant, el contador aún se imprime
			print(f"[backlog] Qdrant no disponible ({exc}); solo cuento", file=sys.stderr)
	resultado = report(counts, cap=cap, msg_cap=msg_cap, memory=memory, dry_run=args.dry_run)

	if args.json:
		print(json.dumps(resultado, ensure_ascii=False))
	else:
		edad = f" · la más antigua hace {resultado['oldest_days']} d" if resultado["oldest_days"] else ""
		notas = f" · {resultado['annotate_pending']} solo esperan notas" if resultado["annotate_pending"] else ""
		print(f"[backlog] {resultado['distill_pending']} sesión(es) sin destilar (tope {cap} sesiones / {msg_cap} mensajes por noche){edad}{notas}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
