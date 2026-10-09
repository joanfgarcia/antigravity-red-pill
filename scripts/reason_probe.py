"""Sonda de razonamiento NPU — RP_ELEMENT {model, prompt_id} → runner_for → jsonl.

Complementa al benchset (contrato/needle/síntesis) con pruebas cualitativas de
razonamiento (multi-paso, lógica, fidelidad). Salida al desk: no es medida de
puesto, es snapshot para leer "cómo razona" cada motor.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_battle_lib import Probe, runner_for  # noqa: E402

PROMPTS = {
	"mates": (
		"Resuelve paso a paso: En una granja hay 23 animales entre gallinas y "
		"conejos. En total hay 62 patas. ¿Cuántas gallinas y cuántos conejos hay? "
		"Da el resultado final.",
		512,
	),
	"logica": (
		"Tres amigos —Ana, Luis y Sofía— tienen edades distintas. Ana no es la "
		"mayor. Luis es mayor que Sofía. ¿Quién es el mayor y quién el menor? "
		"Justifica en una frase.",
		256,
	),
	"sintesis": (
		"INFORME: La planta procesó 320.000 litros, un 12% más que el trimestre "
		"anterior. La parada por falta de repuestos costó 36 horas y 1,8 millones "
		"de euros. Se invirtieron 240.000 euros en repuestos críticos y se firmó "
		"un acuerdo con TecnoSur. Marta Ruiz avisa de falta de personal para el "
		"verano; RRHH confirma contratos antes del 30 de mayo.\n\n"
		"Escribe un resumen en exactamente 3 frases, en español, con nombres y cifras.",
		512,
	),
}


def main() -> int:
	element = json.loads(os.environ["RP_ELEMENT"])
	model = str(element["model"])
	pid = str(element["prompt_id"])
	user_message, budget = PROMPTS[pid]
	probe = Probe(
		name=f"reason_{pid}",
		system_prompt="Eres un asistente útil y preciso.",
		user_message=user_message,
		validator=lambda raw: {"valid": True},
		max_tokens=budget,
		temperature=None,
	)
	runner = runner_for(model)
	try:
		res = runner.run(probe)
	finally:
		runner.close()
	out = Path(os.path.expanduser("~/Documents/IA/Aleth_Core/notes/2026-10-08-benchset/reason_probes.jsonl"))
	out.parent.mkdir(parents=True, exist_ok=True)
	with out.open("a", encoding="utf-8") as f:
		f.write(json.dumps({"model": model, "prompt_id": pid, "latency_s": round(res.latency_s, 1), "raw": res.raw_output[:4000]}, ensure_ascii=False) + "\n")
	print(f"[{model}/{pid}] {res.latency_s:.0f}s · {len(res.raw_output)} chars", flush=True)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
