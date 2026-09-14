#!/usr/bin/env python3
"""memento_reinforce.py — refuerzo Memento-consciente del weaver (Fase 4 §4.2).

Etapa del ciclo nocturno (sleep.yaml → nightly): ejecuta
`weave_memento_reinforcement` sobre la ventana reciente de engramas y reporta
cuántos refine se reforzaron y cuántos ascendieron por superar el gate.
Sale 0 siempre (best-effort, on_fail: warn en el DAG).
"""

from __future__ import annotations

import sys


def main() -> int:
	from red_pill.memento.ascension import weave_memento_reinforcement

	stats = weave_memento_reinforcement()
	print(f"[MEM-REINFORCE] {stats}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
