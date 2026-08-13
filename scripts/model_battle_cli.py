#!/usr/bin/env python3
"""model_battle_cli.py — Bake-off harness using the llama.cpp CLI binary.

Same probes as `model_battle.py` (Titanium's distillation harness), but
executes via the `llama-cli` binary instead of the Python bindings. This
gives us:

  - **GPU acceleration** (CUDA-backed, same backend as production via SIP).
  - **Behavioral equivalence with production** (same binary, same kernels,
    same quantization math). What we measure here is what production does.
  - **No port required** (CLI mode, not server mode).

Trade-off: ~1-2s subprocess spawn overhead per probe (loading model each
time). For 3-5 probes per model this is negligible.

Usage:
  python scripts/model_battle_cli.py <model_name> <path/to.gguf> [prompt_path]
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llama_cli_runner import CliProbe, LlamaCliRunner

DEFAULT_PROMPT = "/home/joan/Documents/IA/sharing/src/red_pill/metabolism/prompts/distiller_v3.txt"
prompt_path = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_PROMPT
PROMPT = open(prompt_path).read()
PROMPT = PROMPT.replace("{agent_name}", "Aleth").replace("{operator_name}", "Joan")
print(f"[prompt] {prompt_path}", flush=True)

PROBES = {
	"entidades": "USER: he abierto una botella de Emilio Moro Reserva para celebrar, el código de la build era rc-2026.08.12 y los tests de MCP pasaron los 42\n\nASSISTANT: brindo contigo, Joan; esa build rc-2026.08.12 con los 42 tests verdes merecía algo mejor que un gin tonic\n\nUSER: jajaja, el gin tonic era ayer, hoy toca Ribera y que el CI no llore",
	"decision": "USER: ¿migramos a Postgres o seguimos con SQLite? el volumen no justifica aún un motor nuevo\n\nASSISTANT: seguimos con SQLite por ahora; añadir Postgres traería más operaciones de las que resuelve\n\nUSER: de acuerdo, lo dejamos así y lo revisamos cuando crezca",
	"filosofico": "USER: no somos nuestros recuerdos, lo que nos define son nuestros actos, ¿no crees?\n\nASSISTANT: discrepo en parte; sin memoria no hay continuidad del yo que actúa, los actos sueltos no hacen identidad\n\nUSER: mmm, eso me recuerda a la charla que tuvimos sobre el gato de Schrödinger",
}


def _validator(raw: str) -> dict:
	"""Titanium's validator adapted to our output format."""
	m = re.search(r"\{[\s\S]*\}", raw)
	if not m:
		return {"valid": False, "reason": "no JSON"}
	try:
		obj = json.loads(m.group(0))
	except Exception as e:
		return {"valid": False, "reason": f"json: {e}"}
	s = str(obj.get("summary", ""))
	SPANISH_2ND = ("te digo", "te pregunto", "te cuento", "contigo", "tú ")
	THIRD = ("dijo ", "respondió ", "preguntó ", "comentó ", "Joan me", "le digo")
	bad = [w for w in SPANISH_2ND if w in s]
	relics = obj.get("relics", [])
	raw_lower = raw.lower()
	verb = [r for r in relics if str(r).lower().strip().strip('"') in raw_lower]
	tp = [w for w in THIRD if w in s]
	return {
		"valid": True,
		"lang": obj.get("lang"),
		"mode_b": bool(tp),
		"bad_2nd": bad,
		"relics": {"got": len(relics), "verbatim": len(verb)},
	}


def main(model_name: str, gguf_path: str, _prompt_unused: str = None):
	print(f"\n##### {model_name} (CLI/GPU) #####", flush=True)
	# Models whose GGUF ships a broken Jinja template (e.g. mradermacher's
	# Mistral-Nemo uses `selectattr("tool_calls", "undefined")` which the
	# bundled jinja engine doesn't recognize). Substituting a simple
	# [INST]/[/INST] template fixes them.
	ct_file = None
	if "Nemo" in gguf_path or "nemo" in model_name:
		ct_file = "/home/joan/Documents/IA/sharing/configs/chat_templates/mistral_nemo_simple.jinja"
	runner = LlamaCliRunner(model_name, gguf_path, chat_template_file=ct_file)
	for pname, raw_data in PROBES.items():
		probe = CliProbe(
			name=pname,
			system_prompt=PROMPT,
			user_message="DATA:\n" + raw_data,
			validator=_validator,
			max_tokens=450,
			temperature=0.1,
		)
		t0 = time.time()
		r = runner.run(probe)
		dt = time.time() - t0
		v = r.validation
		ok = "OK" if v.get("valid") else f"FAIL({v.get('reason')})"
		mb = "MODE_B" if v.get("mode_b") else "—"
		bad = "+".join(v.get("bad_2nd", [])) or "—"
		rec = v.get("relics", {})
		print(f"[{pname}] {dt:.1f}s {ok} lang={v.get('lang')} {mb} bad={bad} relics={rec.get('got', 0)}/{rec.get('verbatim', 0)}", flush=True)
		# Print summary snippet
		m = re.search(r'"summary":\s*"([^"]*)"', r.raw_output)
		if m:
			print(f"  S: {m.group(1)[:200]}", flush=True)


if __name__ == "__main__":
	if len(sys.argv) < 3:
		print(__doc__, file=sys.stderr)
		sys.exit(1)
	main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
