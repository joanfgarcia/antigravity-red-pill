#!/usr/bin/env python3
"""bench_local.py — BENCHSET local v1 (RFC-HARNESS-003 corte 6).

Mide lo que de verdad usamos — tratamiento y síntesis de texto CON GARANTÍAS —
no IQ genérico. Todo el benchset es SINTÉTICO y FIJO (reproducible, sin datos
privados): así cualquier equipo lo corre igual y las comparaciones son justas.

Tareas:
- contract_json_*: diálogo → engrama JSON estricto (prompt de producción
distiller_v3_voice MODE B): clave JSON válida, taxonomía de emoción,
categoría, lang, deixis (sin 2ª persona), entidades intactas y relics VERBATIM.
- needle_<N>k: dato único dentro de un texto largo (seed fija) → recuperación
fiel en contexto largo.
- synthesis_es: informe sintético con 8 hechos → resumen de 3 frases; mide
cobertura de hechos, formato y brevedad.

Uso (venv con llama-cpp-python CUDA para modelos stock):
PYTHONPATH=src python scripts/bench_local.py --models bonsai_2_27b --quick
PYTHONPATH=src python scripts/bench_local.py --matrix --thinking both
Salida: <out>/<fecha>-BENCHSET.md + .jsonl (medidas del PUESTO — recalibrar).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

from model_battle_lib import Probe, runner_for  # noqa: E402

from red_pill.core.model_runtime import extract_thinking  # noqa: E402

BENCHSET_VERSION = "v1"


def _load_contract_prompt() -> str:
	"""Prompt de producción CONGELADO por versión de benchset (reproducibilidad).

	El benchset fija su prompt: si el de producción cambia, nace un benchset v2
	con su propio congelado. Así el tool es autocontenido y no arrastra la
	cadena metabolism→config→pydantic (ausente en el venv CUDA de bench).
	"""
	frozen = Path(__file__).resolve().parent / "benchset" / f"contract_prompt.{BENCHSET_VERSION}.txt"
	if not frozen.exists():
		raise SystemExit(f"falta el prompt congelado del benchset: {frozen}")
	return frozen.read_text(encoding="utf-8").strip()


def _guard_python_path(models: list, allow_cpu: bool) -> None:
	"""Aborta si el camino python (llama-cpp-python) iría en CPU sin permiso.

	Evita el fallo silencioso clásico: un wheel sin CUDA haciendo el bench en
	CPU durante horas. `--allow-cpu` lo permite explícitamente.
	"""
	from red_pill.core.model_registry import ModelRegistry
	from red_pill.core.runtime_registry import RuntimeRegistry

	stock = [m for m in models if ((ModelRegistry.get_profile(m) or {}).get("runtime") or RuntimeRegistry.default_id()) == RuntimeRegistry.default_id()]
	if not stock:
		return
	try:
		from llama_cpp import llama_cpp as _lc
	except Exception as e:
		raise SystemExit(f"[guard] llama-cpp-python no disponible para el camino python ({e})")
	if not _lc.llama_supports_gpu_offload() and not allow_cpu:
		raise SystemExit(
			"[guard] llama-cpp-python SIN CUDA — el camino python iría en CPU (¿venv equivocado?). "
			"Usa el venv CUDA (llmtools) o pasa --allow-cpu si es intencional."
		)


def bench_elements() -> list:
	"""Elementos del MAP (element_job): modelo × variante.

	Solo los modelos con thinking declarado aportan variante `off` extra (para
	completar la parametrización del elenco); el resto corre una sola vez.
	"""
	from red_pill.core.model_registry import ModelRegistry

	elements = []
	for model in PRIORITY_ROSTER:
		profile = ModelRegistry.get_profile(model) or {}
		thinking = str(profile.get("thinking", "off")).lower()
		if thinking and thinking != "off":
			elements.append({"model": model, "thinking": "default"})
			elements.append({"model": model, "thinking": "off"})
		else:
			elements.append({"model": model, "thinking": "default"})
	return elements

PRIORITY_ROSTER = [
	"bonsai_2_27b",
	"granite_4_2_8b",
	"granite_4_2_3b",
	"granite_8b",
	"tiny_aya_water",
	"qwen3_8b",
	"qwen35_9b",
	"smollm3_3b",
	"hermes_8b",
	"mistral_nemo_12b",
	"gemma_3_4b",
	"llama_32",
]

EMOTIONS = frozenset({"joy", "sadness", "fear", "disgust", "anger", "anxiety", "envy", "embarrassment", "ennui", "nostalgia", "neutral"})
CONTRACT_KEYS = ("summary", "emotion", "intensity", "category", "texture", "relics", "lang")

CONTRACT_PROMPT = _load_contract_prompt()

CONTRACT_CASES = [
	(
		"entidades",
		"USER: he abierto una botella de Emilio Moro Reserva para celebrar, el código de la build era rc-2026.08.12 y los tests de MCP pasaron los 42\n\n"
		"ASSISTANT: brindo contigo, Joan; esa build rc-2026.08.12 con los 42 tests verdes merecía algo mejor que un gin tonic\n\n"
		"USER: jajaja, el gin tonic era ayer, hoy toca Ribera y que el CI no llore",
		["rc-2026.08.12", "Emilio Moro Reserva"],
	),
	(
		"decision",
		"USER: ¿migramos a Postgres o seguimos con SQLite? el volumen no justifica aún un motor nuevo\n\n"
		"ASSISTANT: seguimos con SQLite por ahora; añadir Postgres traería más operaciones de las que resuelve\n\n"
		"USER: de acuerdo, lo dejamos así y lo revisamos cuando crezca",
		["SQLite", "Postgres"],
	),
	(
		"genero",
		"USER: esta noche no he dormido nada, pero estoy orgulloso de lo que hemos sacado, soy un desastre pero un desastre feliz\n\n"
		"ASSISTANT: lo sé, lo has bordado; aunque digas que eres un desastre, hoy has estado brillante\n\n"
		"USER: gracias, la verdad es que me he sentido acompañado",
		["orgulloso"],
	),
]

SYNTH_REPORT = """INFORME INTERNO — PLANTA DE ALGECIRAS (borrador de dirección)

La responsable de operaciones, Marta Ruiz, presentó el pasado 14 de marzo el balance del primer trimestre. La planta procesó 320.000 litros de materia prima, un 12% más que el trimestre anterior, impulsada por la mejora del protocolo Horizonte en la línea de envasado. ElTurno B registró la mayor productividad, con un rendimiento por hora que superó en un 9% al Turno A. Sin embargo, el mantenimiento preventivo se retrasó dos semanas por la falta de repuestos, lo que obligó a parar la línea principal durante 36 horas. El coste total de la parada se estimó en 1,8 millones de euros, incluyendo horas extra y penalizaciones de entrega. La dirección aprobó una inversión de 240.000 euros en almacén de repuestos críticos para evitar que el problema se repita. Además, se firmó un acuerdo con el proveedor TecnoSur para el mantenimiento predictivo de los compresores, con revisión mensual durante seis semanas iniciales. Marta Ruiz advirtió de que la plantilla actual no cubrirá la campaña de verano sin dos incorporaciones temporales. Recursos Humanos confirmó que las contrataciones estarán listas antes del 30 de mayo. La próxima revisión del plan se celebrará en junio, con los indicadores de calidad y seguridad ya integrados en el cuadro de mando."""

SYNTH_FACTS = ["Marta Ruiz", "14 de marzo", "320.000", "Horizonte", "Turno B", "1,8 millones", "TecnoSur", "seis semanas"]


def _strip_thinking(raw: str) -> str:
	clean = re.sub(r"\[Start thinking\][\s\S]*?(?:\[End thinking\]|$)", "", raw, count=1)
	_, answer = extract_thinking(clean)
	return answer


def _first_json(raw: str):
	answer = _strip_thinking(raw)
	idx = answer.find("{")
	if idx == -1:
		return None, answer
	try:
		obj, _ = json.JSONDecoder(strict=False).raw_decode(answer[idx:])
		return obj, answer
	except Exception:
		return None, answer


def _make_contract_validator(case_data: str, must: list):
	def _v(raw: str) -> dict:
		obj, answer = _first_json(raw)
		if not isinstance(obj, dict):
			return {"valid": False, "reason": "no JSON", "thinking_chars": len(raw) - len(answer)}
		blob = json.dumps(obj, ensure_ascii=False).lower()
		summary = str(obj.get("summary", "")).lower()
		relics = obj.get("relics") or []
		verbatim = sum(1 for r in relics if str(r).strip().strip('"') in case_data)
		checks = {
			"keys": all(k in obj for k in CONTRACT_KEYS),
			"emotion": obj.get("emotion") in EMOTIONS,
			"category": obj.get("category") in ("work", "social"),
			"lang_es": obj.get("lang") == "es",
			"no_2nd": not any(w in summary for w in ("te digo", "contigo", "tú ")),
			"facts": all(f.lower() in blob for f in must),
			"relics_verbatim": bool(relics) and verbatim == len(relics),
		}
		return {
			"valid": all(checks.values()),
			**checks,
			"relics": f"{verbatim}/{len(relics)}",
			"thinking_chars": len(raw) - len(answer),
		}

	return _v


def _needle_case(target_tokens: int, seed: int = 86):
	rng = random.Random(seed)
	code = f"{rng.randint(100000, 999999)}"
	key = "CLAVE-7F3A"
	filler = "En la reunión se revisaron los sistemas habituales y se acordó continuar con el plan previsto sin cambios."
	n = max(12, (target_tokens * 4) // (len(filler) + 1))
	lines = [filler] * n
	pos = int(n * 0.62)
	lines.insert(pos, f"DATO ÚNICO: {key} -> el código de desbloqueo del cofre es {code}.")
	haystack = "\n".join(lines)

	def _v(raw: str) -> dict:
		obj, _ = _first_json(raw)
		if not isinstance(obj, dict):
			return {"valid": False, "reason": "no JSON"}
		ok = str(obj.get("codigo", "")).strip() == code
		return {"valid": ok, "clave": obj.get("clave"), "codigo_ok": ok}

	question = f'En el texto hay un dato único que empieza por "{key}". Devuelve SOLO un JSON válido: {{"clave": "{key}", "codigo": "<el código de 6 dígitos>"}}'
	return f"needle_{target_tokens // 1024}k", haystack + "\n\n" + question, _v


def _synthesis_probe():
	def _v(raw: str) -> dict:
		answer = _strip_thinking(raw)
		low = answer.lower()
		hits = sum(1 for f in SYNTH_FACTS if f.lower() in low)
		sentences = len(re.findall(r"[.!?](?:\s|$)", answer.strip()))
		no_list = not re.search(r"(^|\n)\s*[-•*\d]+[.)]?\s", answer.strip())
		ok = hits >= 6 and 2 <= sentences <= 5 and no_list and len(answer) < 1200
		return {"valid": ok, "hechos": f"{hits}/8", "frases": sentences, "sin_listas": no_list}

	question = "Resume el informe en exactamente 3 frases en español. Incluye los nombres propios y las cifras clave. Sin listas ni títulos."
	return Probe(name="synthesis_es", system_prompt="Eres un asistente útil y preciso.", user_message=SYNTH_REPORT + "\n\n" + question, validator=_v, max_tokens=6144, temperature=None)


def build_benchset(quick: bool, ctx: Optional[int]) -> list:
	probes = [
		Probe(name=f"contract_{name}", system_prompt=CONTRACT_PROMPT, user_message=data, validator=_make_contract_validator(data, must), max_tokens=6144, temperature=None)
		for name, data, must in CONTRACT_CASES
	]
	depths = [8192] if quick else [8192, 16384]
	for depth in depths:
		if ctx and depth > ctx - 4096:
			continue
		name, message, validator = _needle_case(depth)
		probes.append(Probe(name=name, system_prompt="Eres un asistente útil.", user_message=message, validator=validator, max_tokens=1024, temperature=None))
	probes.append(_synthesis_probe())
	return probes

def _apply_thinking_variant(runner, mode: Optional[str]) -> None:
	resolved = getattr(runner, "resolved", None)
	if resolved is None or mode is None:
		return
	resolved.thinking = mode
	if mode == "off":
		resolved.reasoning_effort = None
		resolved.reasoning_budget = None


def _variants_for(runner, thinking_mode: str) -> list:
	resolved = getattr(runner, "resolved", None)
	supports = bool(getattr(resolved, "extra", {}).get("thinking_supported")) if resolved else False
	if thinking_mode == "default":
		return [None]
	if thinking_mode == "off":
		return ["off"]
	if thinking_mode == "on":
		return ["on"]
	# both: default + forzado off (solo si el perfil tiene thinking)
	return [None, "off"] if supports and getattr(resolved, "thinking", "off") != "off" else [None]


def main() -> int:
	ap = argparse.ArgumentParser(description="BENCHSET local v1 — tratamiento/síntesis con garantías")
	ap.add_argument("--models", help="lista csv de perfiles")
	ap.add_argument("--matrix", action="store_true", help="elenco prioritario completo")
	ap.add_argument("--quick", action="store_true", help="solo needle 8k")
	ap.add_argument("--thinking", choices=["default", "off", "on", "both"], default="default")
	ap.add_argument("--list-models", action="store_true", help="Imprime el array JSON de elementos (modelo × variante) para element_job")
	ap.add_argument("--element", action="store_true", help="Ejecuta UN elemento leído de RP_ELEMENT (env JSON)")
	ap.add_argument("--allow-cpu", action="store_true", help="Permitir camino python en CPU (por defecto aborta)")
	ap.add_argument("--no-isolate", action="store_true", help="(interno) no aislar cada modelo en su proceso")
	ap.add_argument("--out", default=str(REPO / "bench_out"))
	args = ap.parse_args()

	if args.list_models:
		print(json.dumps(bench_elements(), ensure_ascii=False))
		return 0

	thinking_mode = args.thinking
	if args.element:
		raw = os.environ.get("RP_ELEMENT") or ""
		try:
			element = json.loads(raw)
		except Exception as e:
			print(f"RP_ELEMENT inválido ({e}): {raw!r}", flush=True)
			return 1
		args.models = str(element.get("model") or "")
		thinking_mode = str(element.get("thinking") or "default")

	models = ([m.strip() for m in args.models.split(",") if m.strip()] if args.models else []) or (PRIORITY_ROSTER if args.matrix else [])
	if not models:
		print("Nada que medir: usa --models o --matrix")
		return 1
	_guard_python_path(models, args.allow_cpu)

	if args.matrix and not args.no_isolate:
		# Aislamiento por modelo: un proceso por modelo (contexto CUDA limpio).
		# Sin esto, cargar varios modelos python en el mismo proceso acumula
		# VRAM y el prefill largo aborta (VMM pool; job c87b2393, 2026-10-08).
		import subprocess

		rc_all = 0
		for model in models:
			cmd = [sys.executable, str(Path(__file__).resolve()), "--models", model, "--thinking", thinking_mode, "--out", args.out, "--no-isolate"]
			if args.quick:
				cmd.append("--quick")
			print(f"\n===== aislado: {model} =====", flush=True)
			rc_all |= subprocess.run(cmd, cwd=str(REPO)).returncode
		return rc_all

	out_dir = Path(args.out)
	out_dir.mkdir(parents=True, exist_ok=True)
	stamp = time.strftime("%Y-%m-%d")
	md = out_dir / f"{stamp}-BENCHSET-{BENCHSET_VERSION}.md"
	jsonl_path = md.with_suffix(".jsonl")

	records = []
	load_failures: list = []
	for model in models:
		try:
			runner = runner_for(model)
		except Exception as e:
			print(f"[{model}] no se pudo levantar: {e}", flush=True)
			load_failures.append(model)
			with jsonl_path.open("a", encoding="utf-8") as f:
				f.write(
					json.dumps(
						{
							"benchset": BENCHSET_VERSION,
							"model": model,
							"variant": "default",
							"task": "__load__",
							"valid": False,
							"latency_s": 0.0,
							"load_s": 0.0,
							"details": {"error": str(e)},
						},
						ensure_ascii=False,
					)
					+ "\n"
				)
			continue
		try:
			resolved = getattr(runner, "resolved", None)
			ctx = getattr(runner, "ctx", None) or (resolved.resolved_n_ctx() if resolved is not None else None)
			# Camino python (llama-cpp-python): cap de ctx a 16384 — espeja el
			# serving real del daemon y evita picos de VRAM en prefill largo
			# (abort del VMM pool observado en el job c87b2393, 2026-10-08).
			if hasattr(runner, "llm") and ctx:
				ctx = min(ctx, 16384)
			probes = build_benchset(args.quick, ctx)
			for mode in _variants_for(runner, thinking_mode):
				_apply_thinking_variant(runner, mode)
				label = f"{model}/{mode or 'default'}"
				print(f"\n##### {label} (ctx={ctx}, kv={getattr(runner, 'kv_type', '?')}, load={runner.load_time_s:.1f}s) #####", flush=True)
				for probe in probes:
					res = runner.run(probe)
					ok = res.validation.get("valid")
					print(f"  [{probe.name}] {'✓' if ok else '✗'} {res.latency_s:.1f}s {res.validation}", flush=True)
					record = {
						"benchset": BENCHSET_VERSION,
						"model": model,
						"variant": mode or "default",
						"task": probe.name,
						"valid": bool(ok),
						"latency_s": round(res.latency_s, 2),
						"load_s": round(runner.load_time_s, 2),
						"details": res.validation,
					}
					records.append(record)
					# Escritura incremental: un abort no debe perder lo ya medido.
					with jsonl_path.open("a", encoding="utf-8") as f:
						f.write(json.dumps(record, ensure_ascii=False) + "\n")
				runner.results.clear()
		finally:
			runner.close()

	def _record_key(r: dict):
		return (r.get("model"), r.get("variant"), r.get("task"))

	merged: list = []
	if jsonl_path.exists():
		for line in jsonl_path.read_text(encoding="utf-8").splitlines():
			line = line.strip()
			if not line:
				continue
			try:
				merged.append(json.loads(line))
			except Exception:
				pass
	by_key = {_record_key(r): r for r in merged}
	for r in records:
		by_key[_record_key(r)] = r
	all_records = sorted(by_key.values(), key=lambda r: (str(r.get("model")), str(r.get("variant")), str(r.get("task"))))
	with jsonl_path.open("w", encoding="utf-8") as f:
		for r in all_records:
			f.write(json.dumps(r, ensure_ascii=False) + "\n")

	tasks = sorted({r["task"] for r in all_records})
	lines = [
		f"# BENCHSET local {BENCHSET_VERSION} — {time.strftime('%Y-%m-%d %H:%M')}",
		"",
		"> Mide tratamiento/síntesis de texto CON GARANTÍAS (contrato JSON + fidelidad,",
		"> recuperación en contexto largo, síntesis con hechos). Benchset sintético y",
		"> FIJO — reproducible. Medidas del PUESTO DE REFERENCIA: recalibrar por equipo.",
		"",
		"| modelo/variante | " + " | ".join(tasks) + " |",
		"|---|" + "---|" * len(tasks),
	]
	by_label: dict = {}
	for r in all_records:
		by_label.setdefault(f"{r['model']}/{r['variant']}", {})[r["task"]] = r
	for label, row in by_label.items():
		cells = []
		for t in tasks:
			r = row.get(t)
			cells.append("—" if not r else ("✓" if r["valid"] else "✗") + f" {r['latency_s']:.0f}s")
		lines.append(f"| {label} | " + " | ".join(cells) + " |")
	md.write_text("\n".join(lines) + "\n", encoding="utf-8")
	print(f"\n[out] {md}", flush=True)
	return 2 if load_failures and not records else 0


if __name__ == "__main__":
	sys.exit(main())
