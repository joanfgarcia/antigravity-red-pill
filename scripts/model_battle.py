#!/usr/bin/env python3
"""model_battle.py — Bake-off ligero de candidatos a destilador.

Mide, para un GGUF dado, la calidad de síntesis con un prompt de destilador
sobre 3 probes (entidades, decision, filosofico):

deixis (3ª persona nombrada, sin tú/te/contigo para MODE B; o 2ª pers para MODE A)
relics verbatim (substring literal del DATA)
lang, tiempo por probe, carga

Uso:
python model_battle.py <nombre> <ruta-gguf> [ruta-prompt]

Si no se pasa ruta-prompt, usa distiller_v3.txt (nuestro, MODE A 2ª persona).
Para usar el prompt MODE B de Titanium (3ª persona nombrada):
python model_battle.py llama_32 <gguf> <repo>/src/red_pill/metabolism/prompts/distiller_v3_voice.txt

Nota: requiere el venv del daemon (llama-cpp-python) y VRAM libre
(no debe estar el daemon sirviendo modelo en GPU).
"""

import gc
import json
import re
import sys
import time
from pathlib import Path

from llama_cpp import Llama

DEFAULT_PROMPT = str(Path(__file__).resolve().parent.parent / "src" / "red_pill" / "metabolism" / "prompts" / "distiller_v3.txt")
prompt_path = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_PROMPT
PROMPT = open(prompt_path).read()
PROMPT = PROMPT.replace("{agent_name}", "Aleth").replace("{operator_name}", "Joan")
print(f"[prompt] {prompt_path}", flush=True)

PROBES = {
	"entidades": "USER: he abierto una botella de Emilio Moro Reserva para celebrar, el código de la build era rc-2026.08.12 y los tests de MCP pasaron los 42\n\nASSISTANT: brindo contigo, Joan; esa build rc-2026.08.12 con los 42 tests verdes merecía algo mejor que un gin tonic\n\nUSER: jajaja, el gin tonic era ayer, hoy toca Ribera y que el CI no llore",
	"decision": "USER: ¿migramos a Postgres o seguimos con SQLite? el volumen no justifica aún un motor nuevo\n\nASSISTANT: seguimos con SQLite por ahora; añadir Postgres traería más operaciones de las que resuelve\n\nUSER: de acuerdo, lo dejamos así y lo revisamos cuando crezca",
	"filosofico": "USER: no somos nuestros recuerdos, lo que nos define son nuestros actos, ¿no crees?\n\nASSISTANT: discrepo en parte; sin memoria no hay continuidad del yo que actúa, los actos sueltos no hacen identidad\n\nUSER: mmm, eso me recuerda a la charla que tuvimos sobre el gato de Schrödinger",
}
THIRD = ("dijo ", "respondió ", "preguntó ", "comentó ", "the user", "the assistant", "el usuario dijo")
SECOND = ("te digo", "te pregunto", "te cuento", "contigo", "tu ", "tú ")
BAD_2ND = ("te digo que", "te pregunto", "te dices", "contigo", "te propongo")


def main(mname, path):
	print(f"\n##### {mname} #####", flush=True)
	t0 = time.time()
	llm = Llama(model_path=path, n_ctx=6144, n_gpu_layers=-1, use_mmap=False, verbose=False)
	print(f"loaded in {time.time() - t0:.1f}s", flush=True)
	out = llm.create_chat_completion(messages=[{"role": "user", "content": "di ok"}], temperature=0.0, max_tokens=50)
	print("fit OK:", out["choices"][0]["message"]["content"][:60], flush=True)
	for pname, raw in PROBES.items():
		t0 = time.time()
		out = llm.create_chat_completion(
			messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": "DATA:\n" + raw}], temperature=0.1, max_tokens=450
		)
		dt = time.time() - t0
		c = out["choices"][0]["message"]["content"]
		m = re.search(r"\{[\s\S]*\}", c)
		try:
			obj = json.loads(m.group(0))
			s = str(obj.get("summary", ""))
			tp = [w for w in THIRD if w in s]
			sp = [w for w in SECOND if w in s]
			relics = obj.get("relics", [])
			verb = [r for r in relics if str(r).lower().strip().strip('"') in raw.lower()]
			bad_deixis = [w for w in BAD_2ND if w in s]
			print(f"[{pname}] {dt:.1f}s lang={obj.get('lang')} 3rd={tp} 2nd={sp} bad={'+'.join(bad_deixis) or 'OK'} relics={len(relics)}/{len(verb)}")
			print("  S:", s[:220])
		except Exception:
			print(f"[{pname}] {dt:.1f}s RAW:", c[:160])
		print(flush=True)
	del llm
	gc.collect()


if __name__ == "__main__":
	main(sys.argv[1], sys.argv[2])
