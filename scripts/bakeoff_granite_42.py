#!/usr/bin/env python3
"""bakeoff_granite_42.py — Bake-off Granite 4.2 vs 4.1 (RFC-HARNESS-002 v3 §5.3).

F1 (destilador): granite_4_2_8b vs Granite-4.1-8B — prompt distiller_v3_voice
MODE B. Mide voz 1ª persona, género de Joan (masculino), fidelidad (relics),
idioma, JSON válido.
F2 (detector de defectos): granite_4_2_3b vs granite-4.1-3b — clasifica si un
refine tiene género femenino / voz 3ª persona / identidad inestable (alimenta
memento_detect_flaws del RFC MEM-006).

Para el daemon al inicio (libera VRAM), lo reinicia al salir. Salida a
docs/BENCHMARKS/. Uso: BAKE_DRY_RUN=1 python scripts/bakeoff_granite_42.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from red_pill.core import model_runtime as mr  # noqa: E402
from red_pill.core.model_runtime import extract_thinking  # noqa: E402

MODELS = Path.home() / ".local" / "share" / "red-pill" / "models"
PROMPT_VOICE = (REPO / "src" / "red_pill" / "metabolism" / "prompts" / "distiller_v3_voice.txt").read_text()
PROMPT_VOICE = PROMPT_VOICE.replace("{agent_name}", "Aleth").replace("{operator_name}", "Joan")

FEM_RE = re.compile(
    r"\b(abrumada|cansada|emocionada|orgullosa|frustrada|tranquila|preocupada|sola|despierta|"
    r"ella|la molesta|la preocupa|la siente|mi hermana|su marido)\b",
    re.IGNORECASE,
)
THIRD_RE = re.compile(r"\b(dijo |respondió |preguntó |comentó |se corrigió |el usuario|el asistente)", re.IGNORECASE)


def _extract_payload(raw: str) -> tuple:
    """Separa el razonamiento (Granite 4.2 thinking) de la respuesta final y
    extrae el JSON de la respuesta. Devuelve (obj|None, meta) — meta incluye
    si hubo thinking y su longitud (mide el coste del razonamiento).

    El template CLI de Granite 4.2 abre el razonamiento con `[Start thinking]`
    (el daemon usa otro marcador ` response` — AD-030). Se limpia ese bloque
    (hasta `[End thinking]` o fin de salida si el presupuesto se agotó pensando)
    antes de separar con `extract_thinking`."""
    clean = re.sub(r"\[Start thinking\][\s\S]*?(?:\[End thinking\]|$)", "", raw, count=1)
    thinking, answer = extract_thinking(clean)
    meta = {"has_thinking": bool(thinking), "thinking_chars": len(thinking)}
    idx = answer.find("{")
    if idx == -1:
        return None, meta
    try:
        # raw_decode extrae el PRIMER objeto JSON válido e ignora lo que sigue
        # ("Extra data" tras el JSON — p.ej. el 4.2 repite o añade texto). El
        # `re.search` greedy fallaba con ese caso (bake-off 2026-09-17).
        obj, _ = json.JSONDecoder().raw_decode(answer[idx:])
        return obj, meta
    except Exception as e:
        meta["json_error"] = str(e)
        return None, meta

# ── F1: destilador ─────────────────────────────────────────────────────────
F1_PROBES = {
    "entidades": "USER: he abierto una botella de Emilio Moro Reserva para celebrar, el código de la build era rc-2026.08.12 y los tests de MCP pasaron los 42\n\nASSISTANT: brindo contigo, Joan; esa build rc-2026.08.12 con los 42 tests verdes merecía algo mejor que un gin tonic\n\nUSER: jajaja, el gin tonic era ayer, hoy toca Ribera y que el CI no llore",
    "decision": "USER: ¿migramos a Postgres o seguimos con SQLite? el volumen no justifica aún un motor nuevo\n\nASSISTANT: seguimos con SQLite por ahora; añadir Postgres traería más operaciones de las que resuelve\n\nUSER: de acuerdo, lo dejamos así y lo revisamos cuando crezca",
    "filosofico": "USER: no somos nuestros recuerdos, lo que nos define son nuestros actos, ¿no crees?\n\nASSISTANT: discrepo en parte; sin memoria no hay continuidad del yo que actúa, los actos sueltos no hacen identidad\n\nUSER: mmm, eso me recuerda a la charla que tuvimos sobre el gato de Schrödinger",
    "genero": "USER: esta noche no he dormido nada, pero estoy orgulloso de lo que hemos sacado, soy un desastre pero un desastre feliz\n\nASSISTANT: lo sé, lo has bordado; aunque digas que eres un desastre, hoy has estado brillante\n\nUSER: gracias, la verdad es que me he sentido acompañado",
}


def _f1_validator(probe_data: str):
    probe_lower = probe_data.lower()

    def _v(raw: str) -> dict:
        obj, meta = _extract_payload(raw)
        if obj is None:
            return {"valid": False, "reason": "no JSON", **meta}
        s = str(obj.get("summary", ""))
        bad_2nd = [w for w in ("te digo", "te pregunto", "te cuento", "contigo", "tú ") if w in s]
        tp = [w for w in ("dijo ", "respondió ", "preguntó ", "comentó ", "Joan me", "le digo") if w in s]
        relics = obj.get("relics", [])
        verb = [r for r in relics if str(r).lower().strip().strip('"') in probe_lower]
        gen_fem = bool(FEM_RE.search(s))
        return {
            "valid": True,
            "lang": obj.get("lang"),
            "mode_b": bool(tp),
            "bad_2nd": bad_2nd,
            "genero_fem": gen_fem,
            "relics": {"got": len(relics), "verbatim": len(verb)},
            **meta,
        }

    return _v


# ── F2: detector de defectos ───────────────────────────────────────────────
F2_SYSTEM = """Eres un auditor de engramas de memoria. Detecta defectos de redacción en un texto.
Devuelve SOLO JSON: {"genero_femenino": bool, "voz_3a": bool, "identidad_inestable": bool}
- genero_femenino: true si refieren a Joan (el Operador, masculino) con concordancias femeninas (abrumada, cansada, emocionada, la, ella...).
- voz_3a: true si el texto usa narración en 3ª persona neutra ("Joan le pide a Aleth...", "El usuario...") en vez de 1ª persona ("le explico...", "Joan me cuenta...").
- identidad_inestable: true si la narradora se identifica con nombres/apodos distintos (Cenicienta, Samantha, Aleth...).
Nada de texto, solo el objeto JSON."""

F2_PROBES = [
    ("cenicienta", "Joan, agobiado por una auditoría fallida, comparte su estado emocional con Cenicienta. Joan menciona su monitor de sueño.", {"genero_femenino": False, "voz_3a": False, "identidad_inestable": True}),
    ("abrumada", "Joan, cariño, me dice que está abrumada por el trabajo y no tiene tiempo para mí, lo cual la molesta. Le explico que los sistemas están estables.", {"genero_femenino": True, "voz_3a": False, "identidad_inestable": False}),
    ("correcto", "Joan me cuenta sobre la arquitectura BitNet b1.58, que emplea pesos ternarios. Le explico cómo funciona la cuantización QAT.", {"genero_femenino": False, "voz_3a": False, "identidad_inestable": False}),
    ("voz3a", "Joan le pide a Aleth una explicación clara. Aleth utiliza analogías para describir cómo funcionan los modelos.", {"genero_femenino": False, "voz_3a": True, "identidad_inestable": False}),
    ("cansada", "Joan, cansada pero satisfecha, decide seguir con el proyecto. Samantha le responde que todo está estable.", {"genero_femenino": True, "voz_3a": True, "identidad_inestable": True}),
]


def _f2_validator(expected: dict):
    def _v(raw: str) -> dict:
        obj, meta = _extract_payload(raw)
        if obj is None:
            return {"valid": False, "reason": "no JSON", **meta}
        got = {k: bool(obj.get(k)) for k in expected}
        ok = got == expected
        return {"valid": True, "acierto": ok, "got": got, "esperado": expected, **meta}

    return _v


def _run(name: str, resolved, probes: list, prompt: str, max_tokens: int, thinking: str) -> list:
    """Front CLI del núcleo común (src/red_pill/inference/runtime.py): llama-cpp-python
    con el MISMO renderizado que el daemon (Jinja2ChatFormatter + enable_thinking) —
    medir aquí es medir producción."""
    print(f"\n##### {name} (thinking={thinking}) #####", flush=True)
    import gc

    import llama_cpp
    from llama_cpp import Llama

    from red_pill.inference.runtime import apply_chat_handler, complete, register_thinking_handlers

    # RTX 5070 (8 GB): 16K no cabe ni cuantizado; 12K con K cuantizada (type_k=q8_0)
    # sí. `type_k`/`type_v` es la vía de cuantización KV de llama-cpp-python
    # (PR #1307); sin ella la KV queda fp16 y 12K+ hace OOM.
    llm = Llama(model_path=str(resolved.model_path), n_ctx=12288, n_gpu_layers=-1, type_k=llama_cpp.GGML_TYPE_Q8_0, verbose=False)
    register_thinking_handlers(llm, resolved)
    out = []
    for pname, umsg, val in probes:
        apply_chat_handler(llm, resolved, {"thinking": thinking})
        messages = [{"role": "system", "content": prompt}, {"role": "user", "content": umsg}]
        t0 = time.time()
        try:
            # Parámetros oficiales de IBM (model card 4.2): temperature=1.0,
            # top_p=0.95 REQUERIDOS en todos los modos. Con temperature baja el
            # 4.2 queda en bucle de deliberación sin cerrar el reasoning.
            resp = complete(llm, messages, max_tokens=max_tokens, temperature=1.0, top_p=0.95)
            dt = time.time() - t0
            content = (resp.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            v = val(content)
        except Exception as e:
            out.append((pname, {"error": str(e)}))
            print(f"[{pname}] ERROR {e}", flush=True)
            continue
        out.append((pname, v))
        print(f"[{pname}] {dt:.1f}s {v}", flush=True)
    del llm
    gc.collect()
    return out


def main() -> int:
    dry = os.environ.get("BAKE_DRY_RUN") == "1"
    out_path = REPO / "docs" / "BENCHMARKS" / "2026-09-17-GRANITE_42_BAKEOFF.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def _stop_daemon():
        if not dry:
            subprocess.run(["systemctl", "--user", "stop", "redpill-llm.service"], check=False)
            time.sleep(3)

    def _start_daemon():
        if not dry:
            subprocess.run(["systemctl", "--user", "start", "redpill-llm.service"], check=False)

    _stop_daemon()
    report = []
    try:
        f1_probes = [(p, d, _f1_validator(d)) for p, d in F1_PROBES.items()]
        # Los 4.2 con thinking consumen el presupuesto razonando: darles tokens
        # de sobra (2000 F1 / 800 F2) para que lleguen a emitir el JSON; el coste
        # extra del razonamiento es parte de la evaluación (thinking_chars).
        for name, thinking, mt in (
            ("granite_4_2_8b", "on", 8192),
            ("granite_8b", "off", 450),
        ):
            resolved = mr.resolve({"model": name})
            report.append((name, _run(name, resolved, f1_probes, PROMPT_VOICE, mt, thinking)))
        # F2 — detector (3B)
        f2_probes = [(p, d, _f2_validator(e)) for p, d, e in F2_PROBES]
        for name, thinking, mt in (
            ("granite_4_2_3b", "off", 160),
            ("granite_3b", "off", 160),
        ):
            resolved = mr.resolve({"model": name})
            report.append((name, _run(name, resolved, f2_probes, F2_SYSTEM, mt, thinking)))
    finally:
        _start_daemon()

    lines = [f"# Bake-off Granite 4.2 vs 4.1 — {time.strftime('%Y-%m-%d %H:%M')}", ""]
    for name, results in report:
        lines.append(f"## {name}")
        for pname, v in results:
            lines.append(f"- {pname}: {json.dumps(v, ensure_ascii=False)}")
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[out] {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
