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
	_is_template_echo,
	audit_engram_quality,
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


def cmd_chunk(args) -> None:
	text = args.text or open(args.file).read()
	size = args.size if hasattr(args, "size") and args.size else cfg.SLEEP_CHUNK_SIZE
	print(f"[CHUNK EVAL] {len(text)} chars, target chunk size {size}")
	chunks = chunk_text(text, size=size)
	print(f"[CHUNKER OUTPUT] {len(chunks)} chunk(s) producidos:")
	for i, c in enumerate(chunks):
		print(f"\n--- Chunk {i + 1} ({len(c)} chars) ---")
		print(c)


def cmd_telegram(args) -> None:
	raw_data = open(args.file, "r", encoding="utf-8").read()
	try:
		data = json.loads(raw_data)
		if isinstance(data, list):
			texts = [str(item.get("text", "")) for item in data if item.get("text")]
			full_text = "\n".join(texts)
		elif isinstance(data, dict):
			full_text = str(data.get("text", "") or data.get("content", "") or raw_data)
		else:
			full_text = raw_data
	except Exception:
		full_text = raw_data

	print(f"[TELEGRAM TEST] Procesando archivo: {args.file} ({len(full_text)} chars)")
	override_params = {}
	if hasattr(args, "temp") and args.temp is not None:
		override_params["temperature"] = args.temp
	if hasattr(args, "model") and args.model:
		override_params["provider_alias"] = args.model

	override_prompt = open(args.prompt_file).read() if hasattr(args, "prompt_file") and args.prompt_file else None
	yaml_path = args.config_yaml if hasattr(args, "config_yaml") and args.config_yaml else None

	chunks = chunk_text(full_text)
	print(f"[GEN-0] {len(chunks)} fragmentos obtenidos tras chunking")
	distilled = []
	for i, chunk in enumerate(chunks):
		res = distill_engram(
			chunk,
			override_prompt=override_prompt,
			override_params=override_params if override_params else None,
			config_yaml_path=yaml_path,
		)
		distilled.append(res)
		_print(f"gen-0 fragmento {i + 1}", res)

	if distilled:
		hub = synthesize_hub_v2(
			distilled,
			override_prompt=override_prompt,
			override_params=override_params if override_params else None,
			config_yaml_path=yaml_path,
		)
		hub["relics"] = merge_relics(distilled)


def cmd_test_fixtures(args) -> None:
	"""Ejecuta el pipeline de destilación metabólica sobre el banco de pruebas oficial."""
	import pathlib

	fixture_path = pathlib.Path("tests/fixtures/distiller_test_cases.json")
	if not fixture_path.exists():
		print(f"[ERROR] Fixtures file not found at {fixture_path}")
		return

	cases = json.loads(fixture_path.read_text(encoding="utf-8"))
	print(f"[TEST FIXTURES] Running pipeline benchmark on {len(cases)} test cases...")

	override_prompt = open(args.prompt_file).read() if args.prompt_file else None
	override_params = {}
	if args.temp is not None:
		override_params["temperature"] = args.temp
	if args.model is not None:
		override_params["model"] = args.model
	yaml_path = args.config_yaml

	for i, case in enumerate(cases, 1):
		print("\n========================================================")
		print(f"TEST CASE {i}/{len(cases)}: {case.get('id')} — {case.get('description')}")
		print("========================================================")
		chunks = chunk_text(case["text"])
		print(f"[GEN-0] {len(chunks)} fragmentos")
		distilled = []
		for j, chunk in enumerate(chunks, 1):
			res = distill_engram(
				chunk,
				override_prompt=override_prompt,
				override_params=override_params if override_params else None,
				config_yaml_path=yaml_path,
			)
			distilled.append(res)
			_print(f"gen-0 frag {j}", res)

		if distilled:
			hub = synthesize_hub_v2(
				distilled,
				override_prompt=override_prompt,
				override_params=override_params if override_params else None,
				config_yaml_path=yaml_path,
			)
			hub["relics"] = merge_relics(distilled)
			_print("GEN-1 Hub Resultante", hub)


def cmd_upgrade_all(args) -> None:
	"""Itera sobre los engramas existentes en el Bünker (work_memories / social_memories)
	que tengan resumen clínico/3ª persona o carezcan de textura/lang, recupera su
	raw_parent original y los re-destila con el nuevo pipeline autobiográfico v3."""
	from red_pill.memory import MemoryManager

	mm = MemoryManager()
	client = mm.client
	collections = [args.collection] if args.collection else ["work_memories", "social_memories"]
	limit = args.limit or 50

	print(f"[RE-DISTILL BÜNKER] Auditando y migrando hasta {limit} engramas en {collections}...")
	upgraded_count = 0

	for col in collections:
		if not client.collection_exists(col):
			continue
		try:
			points, _ = client.scroll(
				collection_name=col,
				scroll_filter=models.Filter(
					must_not=[
						models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="raw_parent")),
						models.FieldCondition(key="lazarus_phase", match=models.MatchValue(value="sequence_chunk")),
					]
				),
				limit=limit,
				with_payload=True,
			)
		except Exception as e:
			print(f"[ERROR] No se pudieron leer puntos de {col}: {e}")
			continue

		for point in points:
			payload = point.payload or {}
			summary = str(payload.get("summary") or payload.get("content") or "")
			has_texture = bool(payload.get("texture"))

			if not args.force:
				# Evaluamos semánticamente si el engrama sufre de tono clínico de 3ª persona o formato antiguo
				needs_upgrade = (
					audit_engram_quality(summary)
					if args.smart_audit
					else (not has_texture or summary.startswith("Joan ") or " informed that" in summary)
				)
				if not needs_upgrade:
					continue

			# Recover raw source
			raw_id = payload.get("source_buffer_id") or (payload.get("metadata", {}) or {}).get("source_buffer_id")
			source_text = str(payload.get("content", ""))
			if raw_id:
				try:
					raws, _ = client.scroll(
						collection_name=col,
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
				except Exception:
					pass

			if not source_text:
				continue

			chunks = chunk_text(source_text)
			distilled = [distill_engram(c) for c in chunks if not _is_template_echo(c)]
			distilled = [d for d in distilled if not d.get("_is_fallback")]
			if not distilled:
				continue

			hub = synthesize_hub_v2(distilled)
			upgrade_payload = {
				"summary": f"{hub['title']}\n{hub['summary']}" if hub.get("title") else hub["summary"],
				"texture": hub.get("texture", ""),
				"lang": hub.get("lang", ""),
				"relics": merge_relics(distilled),
				"distiller_version": "v3",
				"hub_depth": payload.get("hub_depth") or 2,
				"emotional_vector": build_emotional_vector(
					[{"child_id": "", "emotion": d["emotion"], "intensity": d["intensity"], "category": d["category"]} for d in distilled]
				),
				"category_reviewed_at": time.time(),
			}

			upgraded_count += 1
			print(f"\n[UPGRADE #{upgraded_count}] ID: {point.id} ({col})")
			print(f"  - ANTERIOR: {summary[:120]}...")
			print(f"  + NUEVO:    {upgrade_payload['summary'][:120]}...")
			print(f"  + TEXTURA:  {upgrade_payload['texture'][:120]}...")

			if args.execute:
				client.set_payload(collection_name=col, payload=upgrade_payload, points=[point.id])
				print("  -> APLICADO EN QDRANT ✅")

	print(f"\n[FINAL] Total engramas procesados para re-destilado: {upgraded_count}")
	if not args.execute and upgraded_count > 0:
		print("[DRY-RUN] Modo simulación. Relanza con --execute para aplicar los cambios en el Bünker.")


def main() -> None:
	parser = argparse.ArgumentParser(description="Distill Lab — sleep pipeline diagnostics & prompt workbench")
	parser.add_argument("--config-yaml", help="Path to alternative distiller_params.yaml")
	parser.add_argument("--prompt-file", help="Path to alternative prompt .txt file")
	parser.add_argument("--temp", type=float, help="Override LLM temperature")
	parser.add_argument("--model", help="Override LLM provider model alias")

	sub = parser.add_subparsers(dest="cmd", required=True)

	p_pipe = sub.add_parser("pipeline", help="Simulate gen-0/gen-1/gen-2 over a text")
	g_pipe = p_pipe.add_mutually_exclusive_group(required=True)
	g_pipe.add_argument("--text")
	g_pipe.add_argument("--file")

	sub.add_parser("probe", help="Golden mini-set against the live provider")
	sub.add_parser("fixtures", help="Run benchmark suite on tests/fixtures/distiller_test_cases.json")

	p_chunk = sub.add_parser("chunk", help="Evaluate the text chunking algorithm")
	g_chunk = p_chunk.add_mutually_exclusive_group(required=True)
	g_chunk.add_argument("--text")
	g_chunk.add_argument("--file")
	p_chunk.add_argument("--size", type=int, help="Target chunk size in characters")

	p_tele = sub.add_parser("telegram", help="Test distillation on a Telegram JSON conversation")
	p_tele.add_argument("--file", required=True, help="Path to Telegram conversation file")

	p_eng = sub.add_parser("engram", help="Hot before/after test on a live engram")
	p_eng.add_argument("--query", required=True)
	p_eng.add_argument("--collection", default="work_memories", choices=["work_memories", "social_memories"])
	p_eng.add_argument("--execute", action="store_true", help="Apply upgrade + axons (default: dry-run)")

	p_upg = sub.add_parser("upgrade-all", help="Batch re-distill legacy engrams in Bünker to 1st-person autobiographical format")
	p_upg.add_argument("--collection", choices=["work_memories", "social_memories"])
	p_upg.add_argument("--limit", type=int, default=50, help="Max engrams to process (default: 50)")
	p_upg.add_argument(
		"--smart-audit", action="store_true", help="Use LLM semantic judgment (engram_quality_auditor) to decide if engram needs re-distilling"
	)
	p_upg.add_argument("--force", action="store_true", help="Force re-distilling even if texture is present")
	p_upg.add_argument("--execute", action="store_true", help="Apply payload changes to Qdrant (default: dry-run)")

	args = parser.parse_args()
	handler = {
		"pipeline": cmd_pipeline,
		"probe": cmd_probe,
		"fixtures": cmd_test_fixtures,
		"chunk": cmd_chunk,
		"telegram": cmd_telegram,
		"engram": cmd_engram,
		"upgrade-all": cmd_upgrade_all,
	}[args.cmd]
	handler(args)


if __name__ == "__main__":
	main()
