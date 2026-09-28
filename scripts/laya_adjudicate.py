#!/usr/bin/env python3
"""Adjudicación F1b (AD-039): el juez LLM dirime baseline vs Laya en la MISMA
muestra del bake-off (`state/laya_bakeoff/sample.json` + `predictions.json`).

- Reutiliza `_judge` de `memento_recalibrate` (juez work/social independiente
	del scorer) en lotes de 25 para no saturar el contexto del daemon.
- Compara contra el juez: baseline `dual_route` y `dominio` de Laya.
	(`none`/`altre` siempre discrepan del juez binario: se reportan aparte.)
- Salida: `state/laya_bakeoff/adjudication.json` + resumen stdout. Exit 0
	si el reporte existe; exit 77 (defer) si el LLM local no está disponible.

Corre en el venv del repo con GPU (tarea LLM). No toca Qdrant (solo lectura
del árbol) ni escribe recuerdos.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memento_recalibrate import _judge  # noqa: E402

BATCH = 25


def _choice(pred: dict) -> str:
	try:
		return str(pred["pred"]["answers"]["dominio"].get("choice", "?"))
	except Exception:
		return "?"


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--dir", default="state/laya_bakeoff")
	args = ap.parse_args()
	d = Path(args.dir)
	sample = json.loads((d / "sample.json").read_text(encoding="utf-8"))
	preds = json.loads((d / "predictions.json").read_text(encoding="utf-8"))
	pred_by_id = {p["id"]: p for p in preds if "error" not in p}

	items, idx_map = [], []
	for i, s in enumerate(sample):
		if s["id"] not in pred_by_id:
			continue
		items.append({"snippet": s["text"], "cat": s["route"], "cat_score": 0.5})
		idx_map.append(i)

	labels: dict[int, str] = {}
	for b in range(0, len(items), BATCH):
		chunk = items[b : b + BATCH]
		try:
			data = _judge(chunk)
		except SystemExit as e:
			print(f"ADJUDICATE: LLM no disponible ({e})", flush=True)
			return 77
		for row in data:
			try:
				j = int(row.get("i"))
				cat = str(row.get("category", "")).lower().strip()
			except (TypeError, ValueError):
				continue
			if cat in ("work", "social") and 0 <= j < len(chunk):
				labels[idx_map[b + j]] = cat

	base_ok = base_n = laya_ok = laya_n = 0
	base_bin_ok = base_bin_n = 0
	disag_laya_wins = disag_base_wins = 0
	for i, s in enumerate(sample):
		want = labels.get(i)
		if want is None or s["id"] not in pred_by_id:
			continue
		laya = _choice(pred_by_id[s["id"]])
		laya_bin = laya if laya in ("work", "social") else None
		base = s["route"]
		# baseline completa (none cuenta como fallo: el juez es binario)
		base_n += 1
		base_ok += base == want
		# baseline solo binaria (comparación justa)
		if base in ("work", "social"):
			base_bin_n += 1
			base_bin_ok += base == want
		# laya
		if laya_bin is not None:
			laya_n += 1
			laya_ok += laya_bin == want
		# desacuerdos baseline-vs-laya (ambos binarios): ¿a quién da el juez la razón?
		if base in ("work", "social") and laya_bin is not None and base != laya_bin:
			if laya_bin == want:
				disag_laya_wins += 1
			elif base == want:
				disag_base_wins += 1

	out = {
		"n_muestra": len(sample),
		"n_juzgadas": len(labels),
		"baseline_vs_juez": round(base_ok / max(1, base_n), 3),
		"baseline_bin_vs_juez": round(base_bin_ok / max(1, base_bin_n), 3),
		"laya_vs_juez": round(laya_ok / max(1, laya_n), 3),
		"desacuerdos": {"n": disag_laya_wins + disag_base_wins, "laya_gana": disag_laya_wins, "baseline_gana": disag_base_wins},
	}
	(d / "adjudication.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
	print("ADJUDICATION " + json.dumps(out, ensure_ascii=False), flush=True)
	return 0


if __name__ == "__main__":
	sys.exit(main())
