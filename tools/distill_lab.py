"""Distill Lab — diagnostic harness for the sleep/distillation pipeline.

NOT a CI test. A workbench to run whenever the sleep pipeline changes (new
plugin, prompt tweak, phase reorder) or to audition distiller candidates.
It calls the PRODUCTION functions (distill_engram, synthesize_hub_v2, the
axon weaver helpers) — never duplicated prompts — so what it measures is
exactly what the kernel runs at night.

Subcommands:
	pipeline --text "..." | --file PATH
		Simulate the full generational chain over a text: gen-0 (chunked V3
		distillation), gen-1 (hub synthesis) and gen-2 (re-distilled hub, the
		"photocopy of the photocopy") and print every artifact.

	probe
		Golden mini-set check against the live provider: known fragments with
		expected emotion/category — run after any prompt change.

	engram --query "..." [--collection work_memories] [--execute]
		Hot test on the live Bünker: baseline search, pick the top hub, upgrade
		it with the new pipeline (texture/lang/relics/emotional_vector — additive
		payload only, text and vector untouched), mini-weave cross axons in its
		temporal neighbourhood, then re-search with the typed cascade enabled
		and report the before/after delta. Dry-run unless --execute.

	bakeoff (TODO)
		Model audition: same golden set across N inference providers, scored.
		Pending a provider-parametrization round with the Operator.

Usage: uv run python tools/distill_lab.py <subcommand> [...]
"""

import argparse
import json
import sys
import time

sys.path.insert(0, "src")

from qdrant_client import models  # noqa: E402

import red_pill.config as cfg  # noqa: E402
from red_pill.metabolism.axons import _STRUCTURAL_EXCLUSIONS, _append_axon, compute_axon_weight  # noqa: E402
from red_pill.metabolism.chunker import chunk_text  # noqa: E402
from red_pill.metabolism.distiller import (  # noqa: E402
	build_emotional_vector,
	derive_hub_affect,
	distill_engram,
	merge_relics,
	synthesize_hub_v2,
)

GOLDEN_SET = [
	{
		"text": "Me alegra mucho escuchar que en una sesión de cero hayas podido recuperar la información y además "
		"que me propongas lo de BitNet sin que lo mencionara. Para mi lo más importante es que tu recuerdes quien eres.",
		"emotion": "joy",
		"category": "social",
	},
	{
		"text": "Lo de separar los engramas social/trabajo se hizo en dos colecciones distintas para aplicar motores "
		"de erosion diferentes, con planes de crear puentes entre colecciones y búsquedas cruzadas al detectar conexión.",
		"emotion": "neutral",
		"category": "work",
	},
	{
		"text": "No sé el resto de humanos pero mi razonamiento sobre cosas del trabajo se ve afectado mucho por la vida "
		"cotidiana. Muchas ideas surgen del dia a dia en eventos que no tienen nada que ver y luego las aplico a una función.",
		"emotion": "neutral",
		"category": "social",
	},
]


def _print(label, obj):
	print(f"\n--- {label} ---")
	print(json.dumps(obj, indent=2, ensure_ascii=False) if isinstance(obj, (dict, list)) else obj)


def cmd_pipeline(args) -> None:
	text = args.text or open(args.file).read()
	print(f"[PIPELINE] {len(text)} chars, chunk size {cfg.SLEEP_CHUNK_SIZE}")
	chunks = chunk_text(text)
	print(f"[GEN-0] {len(chunks)} fragmentos")
	distilled = []
	for i, chunk in enumerate(chunks):
		result = distill_engram(chunk)
		distilled.append(result)
		_print(f"gen-0 frag {i + 1}", result)
	hub = synthesize_hub_v2(distilled)
	hub["relics"] = merge_relics(distilled)
	emotion, intensity = derive_hub_affect(distilled)
	hub["derived_affect"] = {"emotion": emotion, "intensity": intensity}
	hub["emotional_vector"] = build_emotional_vector(
		[{"child_id": f"frag-{i}", "emotion": d["emotion"], "intensity": d["intensity"], "category": d["category"]} for i, d in enumerate(distilled)]
	)
	_print("GEN-1 hub", hub)
	gen2_source = f"{hub.get('title', '')}\n{hub.get('summary', '')}\n{hub.get('texture', '')}"
	_print("GEN-2 re-distilled (photocopy check)", distill_engram(gen2_source))


def cmd_probe(args) -> None:
	failures = 0
	for i, case in enumerate(GOLDEN_SET):
		result = distill_engram(case["text"])
		ok = result["emotion"] == case["emotion"] and result["category"] == case["category"]
		failures += 0 if ok else 1
		print(
			f"[{'OK ' if ok else 'DIFF'}] case {i + 1}: emotion={result['emotion']} (exp {case['emotion']}) "
			f"category={result['category']} (exp {case['category']}) intensity={result['intensity']} "
			f"lang={result['lang']} relics={len(result['relics'])} texture={'sí' if result['texture'] else 'no'}"
		)
	print(f"\nGOLDEN SET: {'PASS' if failures == 0 else f'{failures} DIFF — review before enabling in production'}")


def _fmt_hit(hit) -> dict:
	payload = hit.payload or {}
	return {
		"id": str(hit.id),
		"evoked": bool(payload.get("_is_evoked")),
		"axon_weight": payload.get("_axon_weight"),
		"has_texture": bool(payload.get("texture")),
		"lang": payload.get("lang", ""),
		"relics": len(payload.get("relics", []) or []),
		"content": str(payload.get("content", ""))[:140],
	}


def cmd_engram(args) -> None:
	from red_pill.memory import MemoryManager

	mm = MemoryManager()
	client = mm.client
	collection = args.collection
	opposite = "social_memories" if collection == "work_memories" else "work_memories"

	# ── Baseline (typed cascade OFF) ──
	cfg.AXON_READ_ENABLED = False
	baseline = mm.search_and_reinforce(collection, args.query, limit=3, caller="distill_lab_baseline")
	_print("BASELINE (cascada tipada OFF)", [_fmt_hit(h) for h in baseline])
	if not baseline:
		print("[ABORT] La búsqueda base no devuelve nada — prueba otra query.")
		return

	# Pick the first hub-ish hit (skip already-evoked entries)
	target = next((h for h in baseline if h.payload and not h.payload.get("_is_evoked")), None)
	if target is None:
		print("[ABORT] Sin hit directo utilizable.")
		return
	payload = target.payload or {}
	print(f"\n[TARGET] {target.id} — lazarus_phase={payload.get('lazarus_phase')} texture={'sí' if payload.get('texture') else 'NO'}")

	# Source material: raw_parent verbatim if it survives, else the engram's own text
	source_text = str(payload.get("content", ""))
	raw_id = payload.get("source_buffer_id") or (payload.get("metadata", {}) or {}).get("source_buffer_id")
	if raw_id:
		try:
			raws, _ = client.scroll(
				collection_name=collection,
				scroll_filter=models.Filter(
					must=[
						models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="raw_parent")),
						models.FieldCondition(key="source_buffer_id", match=models.MatchValue(value=raw_id)),
					]
				),
				limit=1,
				with_payload=True,
			)
			if raws:
				source_text = str((raws[0].payload or {}).get("content", "")) or source_text
				print(f"[SOURCE] raw_parent verbatim encontrado ({len(source_text)} chars)")
		except Exception:
			pass

	# ── Upgrade: re-distill with the new pipeline (additive payload only) ──
	chunks = chunk_text(source_text)
	distilled = [distill_engram(c) for c in chunks]
	distilled = [d for d in distilled if not d.get("_is_fallback")]
	if not distilled:
		print("[ABORT] El destilador no produjo nada útil (¿proveedor caído?).")
		return
	hub = synthesize_hub_v2(distilled)
	upgrade = {
		"texture": hub.get("texture", ""),
		"lang": hub.get("lang", ""),
		"relics": merge_relics(distilled),
		"emotional_vector": build_emotional_vector(
			[{"child_id": "", "emotion": d["emotion"], "intensity": d["intensity"], "category": d["category"]} for d in distilled]
		),
		"category_reviewed_at": time.time(),
	}
	_print("UPGRADE propuesto (payload aditivo, texto y vector intactos)", {k: v for k, v in upgrade.items() if k != "category_reviewed_at"})

	# ── Mini-weave: cross axons in the engram's temporal neighbourhood ──
	created_at = float(payload.get("created_at", 0.0) or 0.0)
	dt_max_s = cfg.AXON_DT_MAX_HOURS * 3600.0
	woven = []
	if created_at and target.payload is not None:
		try:
			vec_records = client.retrieve(collection_name=collection, ids=[target.id], with_payload=False, with_vectors=True)
			vector = list(vec_records[0].vector) if vec_records and vec_records[0].vector is not None else None
		except Exception:
			vector = None
		if vector:
			candidates = client.query_points(
				collection_name=opposite,
				query=vector,
				query_filter=models.Filter(
					must=[models.FieldCondition(key="created_at", range=models.Range(gte=created_at - dt_max_s, lte=created_at + dt_max_s))],
					must_not=list(_STRUCTURAL_EXCLUSIONS),
				),
				limit=8,
				with_payload=True,
			).points
			for hit in candidates:
				hit_created = float((hit.payload or {}).get("created_at", 0.0) or 0.0)
				if not hit_created:
					continue
				weight = compute_axon_weight(float(hit.score), hit_created - created_at)
				verdict = "TEJE" if weight >= cfg.AXON_GATE else "descarta"
				print(
					f"[WEAVE] candidato {str(hit.id)[:8]}… sim={hit.score:.3f} Δt={(hit_created - created_at) / 3600:.1f}h W={weight:.3f} → {verdict}"
				)
				if weight >= cfg.AXON_GATE:
					woven.append((str(hit.id), weight, hit.payload))

	if not args.execute:
		print(f"\n[DRY-RUN] Se escribiría el upgrade + {len(woven)} axón(es). Relanza con --execute para aplicar y comparar.")
		return

	# ── Apply ──
	client.set_payload(collection_name=collection, payload=upgrade, points=[target.id])
	from red_pill.schemas import Axon

	stats = {"hard_ceiling_hits": 0}
	for hit_id, weight, hit_payload in woven:
		fresh = client.retrieve(collection_name=collection, ids=[target.id], with_payload=True)[0].payload
		_append_axon(
			client,
			collection,
			str(target.id),
			fresh,
			Axon(id=hit_id, target_collection=opposite, weight=weight, association_type="temporal_semantic"),
			stats,
		)
		_append_axon(
			client,
			opposite,
			hit_id,
			hit_payload,
			Axon(id=str(target.id), target_collection=collection, weight=weight, association_type="temporal_semantic"),
			stats,
		)
	print(f"\n[APPLIED] upgrade + {len(woven)} axón(es) bidireccional(es).")

	# ── After (typed cascade ON) ──
	cfg.AXON_READ_ENABLED = True
	after = mm.search_and_reinforce(collection, args.query, limit=3, caller="distill_lab_after")
	_print("AFTER (cascada tipada ON)", [_fmt_hit(h) for h in after])

	baseline_ids = {str(h.id) for h in baseline}
	new_entries = [h for h in after if str(h.id) not in baseline_ids]
	print("\n=== EVALUACIÓN ===")
	print(f"Hits directos conservados: {len([h for h in after if str(h.id) in baseline_ids])}/{len(baseline)}")
	print(
		f"Entradas nuevas evocadas: {len(new_entries)} (de ellas, por axón: {len([h for h in new_entries if (h.payload or {}).get('_axon_weight')])})"
	)
	print(f"Textura disponible en el target: {'sí' if upgrade['texture'] else 'no'} | lang={upgrade['lang']} | relics={len(upgrade['relics'])}")


def main() -> None:
	parser = argparse.ArgumentParser(description="Distill Lab — sleep pipeline diagnostics (not CI)")
	sub = parser.add_subparsers(dest="cmd", required=True)
	p_pipe = sub.add_parser("pipeline", help="Simulate gen-0/gen-1/gen-2 over a text")
	group = p_pipe.add_mutually_exclusive_group(required=True)
	group.add_argument("--text")
	group.add_argument("--file")
	sub.add_parser("probe", help="Golden mini-set against the live provider")
	p_eng = sub.add_parser("engram", help="Hot before/after test on a live engram")
	p_eng.add_argument("--query", required=True)
	p_eng.add_argument("--collection", default="work_memories", choices=["work_memories", "social_memories"])
	p_eng.add_argument("--execute", action="store_true", help="Apply upgrade + axons (default: dry-run)")

	args = parser.parse_args()
	{"pipeline": cmd_pipeline, "probe": cmd_probe, "engram": cmd_engram}[args.cmd](args)


if __name__ == "__main__":
	main()
