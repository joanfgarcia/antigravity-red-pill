#!/usr/bin/env python3
"""calibrate_slots.py — RECETA: mide cuántos slots (`-np`) convienen en ESTE equipo.

No hay un número universal. `num_parallel` depende del modelo (pesos + KV), del
contexto que necesite la tarea y del ancho de banda de la GPU. Cada agente debe
correr esta receta al instalarse/actualizarse y **repetirla al cambiar de modelo
o de contexto**; el resultado se aplica al perfil (`hardware_affinity.num_parallel`)
y a la concurrencia de la tarea (`MEMENTO_TITLES_CONCURRENCY` en títulos).

Qué mide:
  levanta el servidor del perfil con `-np 1,2,4,6,8` (los que quepan) y lanza
  N batches sintéticos de títulos EN CONCURRENTE; mide tiempo total, tokens/s y
  VRAM. Compara con `-np 1` (mismo número de peticiones en vuelo) y elige el
  primer slot donde la ganancia marginal cae por debajo del umbral.

Requisitos:
  - GPU libre: descarga el modelo del daemon (`unload_daemon`) y, si el desk
    (Dokimé) está usando VRAM, pausarlo antes (`red_pill.core.gpu_desk.pause`).
  - Sin datos privados: usa notas sintéticas.

Uso:
  PYTHONPATH=src .venv/bin/python scripts/calibrate_slots.py --profile bonsai_2_9b --ctx 32768
  PYTHONPATH=src .venv/bin/python scripts/calibrate_slots.py --dry-run
  ... --apply     # escribe num_parallel en el perfil (con backup)

Salida: tabla por stdout + JSON en --json-out (default /tmp/calibrate_slots.json).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from red_pill.core.llm_endpoint import llm_chat_url  # noqa: E402
from red_pill.inference.runtime_server import RuntimeServer  # noqa: E402
from red_pill.memento.agentic.prompts import render as render_prompt  # noqa: E402
from red_pill.memento.agentic.prompts import render as prender, system as psystem  # noqa: E402
from red_pill.memento.agentic.prompts import system as system_prompt  # noqa: E402

MIN_SLOT_CTX = 4096
MIN_GAIN = 0.10


def _vram_used_mb() -> int:
	try:
		out = subprocess.run(
			["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
			capture_output=True,
			text=True,
			timeout=10,
		).stdout.strip()
		return int(out.splitlines()[0].strip())
	except Exception:
		return -1


def synthetic_notes(n: int, batch_size: int) -> List[str]:
	"""Notas sintéticas (~300-500 chars) — sin datos del operador."""
	pool = [
		"El daemon perdía VRAM al arrancar porque el pipeline no liberaba el contexto del modelo anterior.",
		"La migración de esquema dejó índices huérfanos que el recall no podía resolver y el gate los contaba como ruido.",
		"Se decidió trocear el pase en partes similares para que el p99 no truncara la salida del juez.",
		"El backfill se reanudó desde el checkpoint por sesión y evitó repetir las 71 sesiones ya destiladas.",
		"La prueba de calidad comparó tres contextos y dos modelos; el más pequeño ganó en latencia sin perder fidelidad.",
		"El hook de identidad inyecta el bloque una vez por turno y el reloj viaja en la telemetría del sobre.",
		"Un job diferido debe fallar visible y reintentarse, no fingir éxito cuando la GPU no tiene hueco.",
	]
	out = []
	for i in range(n):
		base = pool[i % len(pool)]
		out.append(f"Nota {i + 1}: {base} Referencia interna {i + 1}.")
	return out


def build_prompts(notes: Sequence[str], batch_size: int) -> List[str]:
	batches = [notes[i : i + batch_size] for i in range(0, len(notes), batch_size)]
	return [
		render_prompt("titles_user", notes="\n\n".join(f"[{j}] {t[:600]}" for j, t in enumerate(b)))
		for b in batches
	]


def call(base_url: str, system: str, prompt: str, max_tokens: int = 672) -> Dict[str, Any]:
	t0 = time.monotonic()
	r = requests.post(
		f"{base_url}/v1/chat/completions",
		json={
			"messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
			"temperature": 0.2,
			"max_tokens": max_tokens,
		},
		timeout=300,
	)
	d = r.json()
	return {
		"seconds": time.monotonic() - t0,
		"tokens": int((d.get("usage") or {}).get("completion_tokens") or 0),
		"status": r.status_code,
	}


def recommend(rows: Sequence[Dict[str, Any]], min_gain: float = MIN_GAIN) -> int:
	"""Primer slot donde la ganancia marginal respecto al anterior < min_gain."""
	if not rows:
		return 1
	base = next((r for r in rows if r["slots"] == 1), rows[0])
	best = base["slots"]
	prev_speed = base["speedup"]
	for row in sorted(rows, key=lambda r: r["slots"]):
		if row["slots"] == base["slots"]:
			continue
		if row["speedup"] - prev_speed < min_gain:
			break
		best = row["slots"]
		prev_speed = row["speedup"]
	return best


def _write_num_parallel(profile: str, slots: int) -> Path:
	from red_pill.core.paths import get_model_profiles_path

	p = get_model_profiles_path()
	backup = p.with_suffix(f".yaml.bak-calibration-{datetime.now():%Y%m%d-%H%M%S}")
	backup.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
	lines = p.read_text(encoding="utf-8").splitlines()
	start = next((i for i, l in enumerate(lines) if l.startswith(f"  {profile}:")), None)
	if start is None:
		raise SystemExit(f"perfil {profile} no encontrado en {p}")
	end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("  ") and not lines[i].startswith("   ")), len(lines))
	hw = next((i for i in range(start, end) if lines[i].strip() == "hardware_affinity:"), None)
	if hw is None:
		lines[start:start] = ["    hardware_affinity:", f"      num_parallel: {slots}"]
	else:
		insert = hw + 1
		for i in range(hw + 1, end):
			if lines[i].strip().startswith("num_parallel:"):
				lines[i] = f"      num_parallel: {slots}"
				break
		else:
			lines.insert(insert, f"      num_parallel: {slots}")
	p.write_text("\n".join(lines) + "\n", encoding="utf-8")
	return backup


def main(argv: Sequence[str] | None = None) -> int:
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument("--profile", default="bonsai_2_9b")
	ap.add_argument("--ctx", type=int, default=32768, help="contexto TOTAL (se reparte entre slots)")
	ap.add_argument("--max-slots", type=int, default=8)
	ap.add_argument("--batches", type=int, default=4, help="peticiones en vuelo (una por batch)")
	ap.add_argument("--batch-size", type=int, default=12)
	ap.add_argument("--fixture", choices=("titles", "distill", "distill-real"), default="titles")
	ap.add_argument("--session-dir", default="", help="sesión memento para --fixture distill-real")
	ap.add_argument("--max-output", type=int, default=None, help="tokens de salida por petición")
	ap.add_argument("--json-out", default="/tmp/calibrate_slots.json")
	ap.add_argument("--apply", action="store_true", help="escribe num_parallel en el perfil")
	ap.add_argument("--keep-daemon", action="store_true", help="no descarga el modelo del daemon (comparte VRAM)")
	ap.add_argument("--dry-run", action="store_true")
	args = ap.parse_args(argv)

	slots_seq = [s for s in (1, 2, 4, 6, 8, 12, 16) if s <= args.max_slots]
	print(f"[calibración] perfil={args.profile} ctx={args.ctx} slots={slots_seq} batches={args.batches}×{args.batch_size}")
	if args.dry_run:
		print("[dry-run] no se levanta el servidor. Plan válido.")
		return 0

	if not args.keep_daemon:
		# El daemon mantiene su modelo cargado aunque el plan quepa: sin esto la
		# medición de VRAM incluye pesos ajenos (5,1 GB en vez de ~2,9) y el
		# speedup se mide con la GPU ya ocupada.
		try:
			base = llm_chat_url().split("/v1/")[0]
			requests.post(f"{base}/v1/unload", timeout=20)
			time.sleep(2)
		except Exception as e:
			print(f"[calibración] aviso: no se pudo descargar el daemon: {e}")
	vram_before = _vram_used_mb()
	print(f"[calibración] VRAM en reposo: {vram_before} MB (desk pausado por el operador)")

	if args.fixture == "titles":
		notes = synthetic_notes(args.batches * args.batch_size, args.batch_size)
		prompts = build_prompts(notes, args.batch_size)
		system = system_prompt("titles_user") or ""
		max_out = args.max_output or 672
	elif args.fixture == "distill-real":
		# Fragmento REAL de una sesión larga, con el prompt real de distill.
		from red_pill.memento.agentic.fragments import (
			_fragment_messages,
			_render_fragment,
			_split_messages,
			work_units,
		)

		session = Path(args.session_dir)
		if not session.exists():
			raise SystemExit(f"--session-dir inexistente: {session}")
		units = work_units(session)
		prompts = []
		for unit in units[: args.batches]:
			content = unit.content
			if len(content) <= 8000:
				frag = content
			else:
				frags = _fragment_messages(_split_messages(content), 8000, 2)
				frag = _render_fragment(frags[0])
			prompts.append(prender("distill_user_opening", content=frag))
		system = psystem("distill_user_opening") or ""
		max_out = args.max_output or 2048
		if not prompts:
			raise SystemExit("la sesión no tiene work units")
	else:
		# Fragmento tipo distill sintético: ~8.000 chars por petición.
		base = (
			"## 2026-09-07T16:38:34Z — Asistente\n"
			"El backfill seguía en marcha con 34129 vivo y 396 llamadas; revisé el registry, "
			"el árbol de memento y los ficheros distill/refine por sesión. El hallazgo fue que "
			"el guardado se hacía al final del run y un crash tras 71 sesiones dejaba los "
			"marcados agentic sin persistir. Propuse guardar por sesión y añadir crash-recovery "
			"en pending_agentic. Joan pidió medir el coste y dejar el proceso intacto hasta "
			"terminar.\n\n"
		)
		prompts = [(base * 40)[:8000] for _ in range(args.batches)]
		system = "Eres un destilador. Resume el fragmento en una sección con título y cuerpo, en primera persona."
		max_out = args.max_output or 2048
	rows: List[Dict[str, Any]] = []
	base_seconds = None

	for slots in slots_seq:
		if args.ctx // slots < MIN_SLOT_CTX:
			print(f"[calibración] np={slots}: {args.ctx // slots} < {MIN_SLOT_CTX} por slot — se salta")
			continue
		srv = RuntimeServer(args.profile, ctx=args.ctx, num_parallel=slots, unload_daemon=True, vram_margin_mb=0)
		try:
			srv.start()
			srv.wait_ready()
			time.sleep(1)
			vram = _vram_used_mb()
			t0 = time.monotonic()
			with ThreadPoolExecutor(max_workers=len(prompts)) as ex:
				res = list(ex.map(lambda p: call(srv.base_url, system, p, max_out), prompts))
			secs = time.monotonic() - t0
			tokens = sum(r["tokens"] for r in res)
			codes = sorted({r["status"] for r in res})
			if base_seconds is None:
				base_seconds = secs
			rows.append(
				{
					"slots": slots,
					"seconds": round(secs, 2),
					"tokens": tokens,
					"tok_s": round(tokens / secs, 1) if secs else 0,
					"vram_mb": vram,
					"vram_delta_mb": (vram - vram_before) if vram_before >= 0 and vram >= 0 else -1,
					"speedup": round(base_seconds / secs, 2) if secs else 0,
					"codes": codes,
				}
			)
			print(f"[calibración] np={slots}: {secs:.1f}s · {tokens} tok · {rows[-1]['tok_s']} tok/s · VRAM {vram} MB (+{rows[-1]['vram_delta_mb']}) · speedup {rows[-1]['speedup']}× · HTTP {codes}")
		except Exception as e:
			print(f"[calibración] np={slots}: FALLO {type(e).__name__}: {e}")
			break
		finally:
			try:
				srv.stop()
			except Exception:
				pass

	best = recommend(rows)
	print(f"\n[calibración] recomendado: num_parallel={best} (ctx/slot={args.ctx // max(1, best)})")
	print(f"[calibración] aplica: hardware_affinity.num_parallel: {best}  y  MEMENTO_TITLES_CONCURRENCY={best}")
	out = {"generated_at": datetime.now().isoformat(), "profile": args.profile, "ctx": args.ctx, "rows": rows, "recommended": best}
	Path(args.json_out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
	print(f"[calibración] detalle: {args.json_out}")
	if args.apply and rows:
		backup = _write_num_parallel(args.profile, best)
		print(f"[calibración] num_parallel={best} escrito en el perfil (backup: {backup})")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
