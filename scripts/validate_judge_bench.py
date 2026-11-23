#!/usr/bin/env python3
"""validate_judge_bench.py — bench READ-ONLY del juez de `validate`.

¿Por qué existe? `memento_validate.validate_note` **sella** el veredicto en el
frontmatter de la nota. Para comparar modelos no podemos usarlo: el primero que
pase dejaría el sello y los demás medirían sobre un corpus mutado.

Este banco replica el contrato EXACTO de producción —mismo system prompt, mismo
render, mismo transporte SIP, misma task y **una nota por llamada**— pero **no
escribe nada**: devuelve el veredicto por nota y un resumen. La comparación
entre modelos se hace después, modelo a modelo, sobre la MISMA muestra
determinista.

Uso (una configuración por step, element_job):
	python scripts/validate_judge_bench.py --model granite_8b --n 12 --seed 7 \
		--out scratch/benchmarks/validate/granite_8b.json

El modelo viaja en `RP_LLM_MODEL` (lo lee `runtime._demand` en cada llamada).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from red_pill.memento import get_memento_root  # noqa: E402
from red_pill.memento.agentic import http_transport, pending_validations, prompts, runtime  # noqa: E402  # noqa: E402
from red_pill.memento.agentic.validate import _body, looks_like_raw_dump  # noqa: E402

MAX_CHARS_PER_NOTE = 600


def _sample(root: Path, n: int, seed: int) -> list[Path]:
	paths = sorted(pending_validations(root))
	rng = random.Random(seed)
	rng.shuffle(paths)
	out = []
	for p in paths:
		if looks_like_raw_dump(_body(p)):
			continue  # producción lo rechaza sin LLM; no discrimina
		out.append(p)
		if len(out) >= n:
			break
	return out


def main() -> int:
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument("--model", required=True, help="Perfil del elenco (RP_LLM_MODEL).")
	ap.add_argument("--n", type=int, default=12, help="Notas de la muestra (determinista por seed).")
	ap.add_argument("--seed", type=int, default=7)
	ap.add_argument("--task", default="validate")
	ap.add_argument("--root", type=Path, default=None)
	ap.add_argument("--out", type=Path, required=True)
	args = ap.parse_args()

	root = args.root or get_memento_root()
	sample = _sample(root, args.n, args.seed)
	if not sample:
		print("[validate-bench] sin notas pendientes", file=sys.stderr)
		return 1

	os.environ["RP_LLM_MODEL"] = args.model
	os.environ["RP_LLM_TASK"] = args.task

	# Producción valida UNA nota por llamada (`validate_note` → batch=1 con el
	# prefijo `[0]`). Agrupar en un solo prompt cambia el contrato y trunca.
	verdicts: dict[int, dict] = {}
	raws: dict[int, str] = {}
	for i, p in enumerate(sample):
		raw = http_transport(
			prompts.system("content_validate_user") or "",
			prompts.render("content_validate_user", notes=f"[0] {_body(p)[:MAX_CHARS_PER_NOTE]}"),
			2048,
			0.1,
		)
		raws[i] = raw
		for row in runtime._extract_json_array(raw) or []:
			if not isinstance(row, dict):
				continue
			approved = row.get("approved") if isinstance(row.get("approved"), bool) else str(row.get("approved")).lower() == "true"
			verdicts[i] = {"approved": approved, "reason": str(row.get("reason") or "").strip()[:120]}
			break

	notes = []
	for i, p in enumerate(sample):
		notes.append(
			{
				"i": i,
				"path": str(p.relative_to(root)),
				"verdict": verdicts.get(i),
				"raw_head": "" if i in verdicts else raws.get(i, "")[:200],
			}
		)

	out = {
		"model": args.model,
		"task": args.task,
		"seed": args.seed,
		"n": len(sample),
		"answered": len(verdicts),
		"approved": sum(1 for v in verdicts.values() if v["approved"]),
		"rejected": sum(1 for v in verdicts.values() if not v["approved"]),
		"notes": notes,
	}
	args.out.parent.mkdir(parents=True, exist_ok=True)
	args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
	print(json.dumps({k: out[k] for k in ("model", "n", "answered", "approved", "rejected")}, ensure_ascii=False))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
