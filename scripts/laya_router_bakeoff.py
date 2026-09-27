#!/usr/bin/env python3
"""Bake-off F1 del router System One (AD-039): Laya-multilingual como
clasificador previo `dominio × voz` para elegir prompt (y modelo).

- Corre con el venv CPU `~/.local/share/red-pill/laya-venv` (torch CPU +
  `laya`, NUNCA el venv del daemon; no toca la GPU ni el puerto 8760).
- Entrada: notas `annotate/*.md` del árbol Memento (frontmatter `dual_route`
  como baseline + cuerpo como estado). Sin imports del repo (parser propio).
- Preguntas (una sola pasada por nota): `dominio` (work/social/otro) y `actor`
  (joan/aleth/tercer/extern) con confianzas.
- Salida en `state/laya_bakeoff/`: `sample.json`, `predictions.json`,
  `report.md` + resumen por stdout. Exit 0 siempre que el reporte exista
  (un mal acuerdo también es un resultado: gate F1→F2 explícito).

Gate F1→F2 (AD-039): acuerdo con baseline/juez ≥0,80 en dominio +
calibración sana + tasa de escalado aceptable; si no: fine-tune o se aparca.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

LAYA_VENV_PY = Path.home() / ".local/share/red-pill/laya-venv/bin/python"
DEFAULT_MEMO_ROOT = Path.home() / ".local/share/red-pill/memento"
DEFAULT_OUT = Path("state/laya_bakeoff")

QUESTIONS = {
    "dominio": {
        "type": "choice",
        "instructions": "De què tracta aquesta nota de memòria?",
        "criteria": {
            "work": "feina tècnica: enginyeria, programari, sistemes, models",
            "social": "vida personal: relacions, emocions, família, salut",
            "altre": "cap de les anteriors o indeterminable",
        },
    },
    "actor": {
        "type": "choice",
        "instructions": "Qui fa l'acció principal que descriu la nota?",
        "criteria": {
            "joan": "en Joan, l'operador",
            "aleth": "l'assistent Aleth",
            "tercer": "una tercera persona",
            "extern": "una entitat externa (sistema, empresa, eina)",
        },
    },
}


def _parse_frontmatter(txt: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)", txt, re.S)
    fm: dict = {}
    body = txt
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip().strip("'\"")
        body = m.group(2)
    body = re.sub(r"\s+", " ", body).strip()
    return fm, body


def collect_notes(root: Path, max_chars: int) -> list[dict]:
    rows = []
    for path in sorted(root.rglob("annotate/*.md")):
        try:
            txt = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm, body = _parse_frontmatter(txt)
        route = str(fm.get("dual_route") or "").strip().lower()
        route = route if route in ("work", "social") else "none"
        rows.append(
            {
                "id": str(path.relative_to(root)),
                "route": route,
                "flags": str(fm.get("quality_flags") or ""),
                "text": body[:max_chars],
            }
        )
    return rows


def stratified(rows: list[dict], n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    buckets: dict[str, list[dict]] = {"work": [], "social": [], "none": []}
    for r in rows:
        buckets[r["route"]].append(r)
    per, out = max(1, n // 3), []
    for k in ("work", "social", "none"):
        b = buckets[k]
        rng.shuffle(b)
        out.extend(b[:per])
    rng.shuffle(out)
    return out[:n]


def ensure_predictor() -> None:
    """Hijo aislado: el venv laya corre el predict (este proceso NO importa torch)."""
    probe = subprocess.run(
        [str(LAYA_VENV_PY), "-c", "import laya; print(laya.__version__ if hasattr(laya,'__version__') else 'ok')"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if probe.returncode != 0:
        raise RuntimeError(f"venv laya no usable: {probe.stderr[-500:]}")


def predict_batch(sample: list[dict], device: str) -> list[dict]:
    helper = (
        "import json,sys,time,laya;"
        f"agent=laya.load('convaiinnovations/laya',subfolder='multilingual',device={device!r});"
        "Q=" + json.dumps(QUESTIONS) + ";"
        "inp=json.load(sys.stdin);out=[];"
        "t0=time.time();"
        "r=agent.predict(inp['text'],Q);"
        "print(json.dumps({'pred':r,'lat_s':round(time.time()-t0,3)}))"
    )
    results = []
    for note in sample:
        p = subprocess.run(
            [str(LAYA_VENV_PY), "-c", helper],
            input=json.dumps({"text": note["text"]}),
            capture_output=True,
            text=True,
            timeout=600,
        )
        if p.returncode != 0:
            results.append({"id": note["id"], "error": p.stderr[-300:]})
            continue
        try:
            results.append({"id": note["id"], **json.loads(p.stdout)})
        except Exception as e:
            results.append({"id": note["id"], "error": f"parse: {e}"})
    return results


def _choice(pred: dict, axis: str) -> tuple[str, float]:
    try:
        a = pred["pred"]["answers"][axis]
        return str(a.get("choice", "?")), float(a.get("answer_confidence", a.get("confidence", 0.0)))
    except Exception:
        return "?", 0.0


def report(sample: list[dict], preds: list[dict]) -> tuple[str, dict]:
    by_id = {s["id"]: s for s in sample}
    agree = conf_ok = conf_tot = 0
    lat: list[float] = []
    conf_buckets: dict[str, list[int]] = {"<0.6": [0, 0], "0.6-0.8": [0, 0], ">=0.8": [0, 0]}
    actor_dist: dict[str, int] = {}
    errors = 0
    for pr in preds:
        if "error" in pr:
            errors += 1
            continue
        note = by_id[pr["id"]]
        dom, dc = _choice(pr, "dominio")
        act, _ = _choice(pr, "actor")
        actor_dist[act] = actor_dist.get(act, 0) + 1
        lat.append(float(pr.get("lat_s", 0)))
        # baseline: dual_route (none→otro)
        base = note["route"] if note["route"] in ("work", "social") else "altre"
        hit = dom == ("altre" if base == "altre" else base)
        agree += hit
        key = "<0.6" if dc < 0.6 else ("0.6-0.8" if dc < 0.8 else ">=0.8")
        conf_buckets[key][1] += 1
        conf_buckets[key][0] += hit
        conf_tot += 1
        conf_ok += dc
    n = max(1, conf_tot)
    lat_sorted = sorted(lat)
    p50 = lat_sorted[len(lat_sorted) // 2] if lat_sorted else 0
    p95 = lat_sorted[int(len(lat_sorted) * 0.95)] if lat_sorted else 0
    esc = {t: sum(1 for pr in preds if "error" not in pr and _choice(pr, "dominio")[1] < t) for t in (0.7, 0.8)}
    stats = {
        "n": len(sample),
        "evaluadas": conf_tot,
        "errores": errors,
        "acuerdo_dominio_vs_baseline": round(agree / n, 3),
        "confianza_media": round(conf_ok / n, 3),
        "calibracion": {k: {"n": t, "acierto": round(h / max(1, t), 3)} for k, (h, t) in conf_buckets.items()},
        "lat_s_p50": round(p50, 2),
        "lat_s_p95": round(p95, 2),
        "tasa_escalado_conf_baja": {str(t): round(v / n, 3) for t, v in esc.items()},
        "distribucion_actor": actor_dist,
    }
    gate = stats["acuerdo_dominio_vs_baseline"] >= 0.80
    md = (
        "# Bake-off F1 router System One (Laya-multilingual, CPU)\n\n"
        f"- Acuerdo dominio vs baseline (dual_route): **{stats['acuerdo_dominio_vs_baseline']}**\n"
        f"- Confianza media: {stats['confianza_media']} | calibración: {json.dumps(stats['calibracion'], ensure_ascii=False)}\n"
        f"- Latencia/nota p50/p95: {stats['lat_s_p50']}s / {stats['lat_s_p95']}s\n"
        f"- Tasa de escalado (conf < 0.7 / 0.8): {json.dumps(stats['tasa_escalado_conf_baja'])}\n"
        f"- Distribución actor: {json.dumps(stats['distribucion_actor'], ensure_ascii=False)}\n"
        f"- Gate F1→F2 (≥0.80): **{'PASA' if gate else 'NO PASA'}** → {'matriz de prompts + flag' if gate else 'fine-tune con 14k o aparcar'}\n"
    )
    return md, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--max-chars", type=int, default=1500)
    ap.add_argument("--memo-root", default=str(DEFAULT_MEMO_ROOT))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    ensure_predictor()
    rows = collect_notes(Path(args.memo_root), args.max_chars)
    if not rows:
        print("BAKEOFF: sin notas en el árbol", flush=True)
        return 2
    sample = stratified(rows, args.n, args.seed)
    (out / "sample.json").write_text(json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
    preds = predict_batch(sample, args.device)
    (out / "predictions.json").write_text(json.dumps(preds, ensure_ascii=False, indent=1), encoding="utf-8")
    md, stats = report(sample, preds)
    (out / "report.md").write_text(md, encoding="utf-8")
    stats["wall_min"] = round((time.time() - t0) / 60, 1)
    print(md, flush=True)
    print("STATS " + json.dumps(stats, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
