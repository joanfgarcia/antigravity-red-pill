"""Gating previo de rebuilds Memento (MEM-010 F2) — motor de decisión.

Decide POR SESIÓN si un delta del pipeline exige reprocesar (`process`),
saltar (`skip`) o re-puntuar sin re-extraer (`rescore`), y sella la decisión en
`_session.json` (`stages.gate`) con la firma nueva y el motivo. Sustituye el
todo-o-nada del fingerprint opaco: el manifest estructurado (F1) se compara por
componentes y cada delta se traduce a un predicado sobre la evidencia de la
sesión (flags, métricas).

Contrato de la decisión (`stages.gate.latest`):
	{run_id, at, action, state, reason, policy, delta, from_fingerprint,
	to_fingerprint, input_hash, outcome}
	- action: skip | process | rescore | forced
	- state:  pending | skipped | done | failed  (skipped/done/failed = terminal)
	- history: upsert por run_id, cap HISTORY_CAP.

Fast-path (run-independiente): misma firma + mismo input + sin parcial + estado
terminal ⇒ sin escritura (idempotencia del sweep). `_partial.json` presente
manda: re-emisión `resume-partial` (MEM-009). El ledger global y la remediación
`--rebuild-run` son F3; la migración one-shot, F2b.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from red_pill.memento.ledger import sanitize_text
from red_pill.memento.record import mutate_session_record, read_session_record

from .agentic import runtime
from .agentic.fragments import work_units

logger = logging.getLogger(__name__)

STAGE = "annotate"
POLICY_VERSION = "gate-policy-v1"
HISTORY_CAP = 10
EMITTABLE_ACTIONS = ("process", "rescore", "forced")
TERMINAL_STATES = ("skipped", "done", "failed")


# ── lectura ──────────────────────────────────────────────────────────────────


def read_gate(root: Path, dir_rel: str) -> Dict[str, Any]:
	"""Bloque `stages.gate` (vacío si no existe)."""
	stages = read_session_record(root, dir_rel).get("stages") or {}
	gate = stages.get("gate")
	return gate if isinstance(gate, dict) else {}


def read_meta(root: Path, dir_rel: str) -> Dict[str, Any]:
	"""`annotate/_meta.json` (vacío si no existe o no parsea)."""
	try:
		data = json.loads((root / dir_rel / "annotate" / "_meta.json").read_text(encoding="utf-8"))
		return data if isinstance(data, dict) else {}
	except (OSError, json.JSONDecodeError):
		return {}


# ── pipeline vigente ─────────────────────────────────────────────────────────


def current_pipeline() -> Dict[str, Any]:
	"""Manifest vigente (se computa UNA vez por sweep y se pasa a cada sesión)."""
	manifest = runtime.annotate_manifest()
	return {
		"manifest": manifest,
		"manifest_hash": runtime.annotate_manifest_hash(),
		"legacy_fingerprint": runtime.annotate_prompt_version(),
	}


def session_input_hash(root: Path, dir_rel: str) -> Optional[str]:
	"""Hash normativo de la entrada de la sesión (delegado en annotate)."""
	from .agentic.annotate import session_input_hash as _sih

	value, _source = _sih(root, dir_rel, work_units(root / dir_rel))
	return value


# ── sellado ──────────────────────────────────────────────────────────────────


def _now() -> str:
	return datetime.now(timezone.utc).isoformat()


def seal(
	root: Path,
	dir_rel: str,
	*,
	run_id: str,
	action: str,
	state: str,
	reason: str,
	to_fingerprint: str,
	from_fingerprint: Optional[str] = None,
	input_hash: Optional[str] = None,
	delta: Optional[List[str]] = None,
	outcome: Optional[Dict[str, Any]] = None,
	policy: str = POLICY_VERSION,
) -> Dict[str, Any]:
	"""Sella/actualiza la decisión del run (upsert por run_id) bajo UN lock.

	El motivo y el outcome pasan por el contrato de saneado (MEM-010 §3.6) en
	este punto único, de modo que `_session.json` no persiste secretos/rutas/ANSI."""
	entry: Dict[str, Any] = {
		"run_id": run_id,
		"at": _now(),
		"action": action,
		"state": state,
		"reason": sanitize_text(reason, 512),
		"policy": policy,
		"delta": sorted(delta or []),
		"from_fingerprint": from_fingerprint,
		"to_fingerprint": to_fingerprint,
		"input_hash": input_hash,
		"outcome": _sanitize_outcome(outcome),
	}

	def mutate(block: Dict[str, Any]) -> Dict[str, Any]:
		history = [e for e in (block.get("history") or []) if isinstance(e, dict)]
		for i, prev in enumerate(history):
			if prev.get("run_id") == run_id:
				history[i] = entry
				break
		else:
			history.append(entry)
		return {"stage": STAGE, "latest": entry, "history": history[-HISTORY_CAP:]}

	return dict(mutate_session_record(root, dir_rel, "gate", mutate)["latest"])


def _sanitize_outcome(outcome: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
	if not outcome:
		return outcome
	clean = dict(outcome)
	if "error" in clean:
		clean["error"] = sanitize_text(clean["error"], 1024)
	return clean


def mark_outcome(
	root: Path,
	dir_rel: str,
	*,
	run_id: str,
	state: str,
	outcome: Optional[Dict[str, Any]] = None,
) -> None:
	"""Cierre del paso: estado terminal + outcome en `latest` Y en su entrada."""
	clean = _sanitize_outcome(outcome)

	def mutate(block: Dict[str, Any]) -> Dict[str, Any]:
		latest = dict(block.get("latest") or {})
		if latest.get("run_id") != run_id:
			logger.warning("mark_outcome: run_id %s no es el latest de %s (ignorado)", run_id, dir_rel)
			return block
		latest["state"] = state
		latest["outcome"] = clean
		latest["at"] = _now()
		history = [e for e in (block.get("history") or []) if isinstance(e, dict)]
		for i, prev in enumerate(history):
			if prev.get("run_id") == run_id:
				merged = dict(prev)
				merged.update({"state": state, "outcome": clean, "at": latest["at"]})
				history[i] = merged
				break
		return {"stage": STAGE, "latest": latest, "history": history[-HISTORY_CAP:]}

	mutate_session_record(root, dir_rel, "gate", mutate)


# ── predicados ───────────────────────────────────────────────────────────────


def manifest_delta(old_manifest: Optional[Dict[str, Any]], new_manifest: Dict[str, Any]) -> Optional[List[str]]:
	"""Componentes cambiados entre manifests; None si no hay base comparable."""
	if not isinstance(old_manifest, dict):
		return None
	old_schema = old_manifest.get("schema")
	if old_schema != new_manifest.get("schema"):
		return ["schema"]
	old_components = old_manifest.get("components") or {}
	new_components = new_manifest.get("components") or {}
	delta = [
		key
		for key in sorted(set(old_components) | set(new_components))
		if json.dumps(old_components.get(key), sort_keys=True) != json.dumps(new_components.get(key), sort_keys=True)
	]
	return delta


def _notes_near_dups(annotate_dir: Path, threshold: float) -> int:
	"""Pares near-dup entre las notas FINALES de la sesión (mismo cómputo que la métrica)."""
	from .agentic.annotate import _tokens

	texts: List[str] = []
	for path in sorted(annotate_dir.glob("*.md")):
		try:
			raw = path.read_text(encoding="utf-8", errors="replace")
		except OSError:
			continue
		parts = raw.split("\n---\n", 1)
		body = parts[1] if len(parts) == 2 else raw
		texts.append(" ".join(body.split()))
	toks = [_tokens(t) for t in texts]
	pairs = 0
	for i in range(len(toks)):
		for j in range(i + 1, len(toks)):
			a, b = toks[i], toks[j]
			if a and b and len(a & b) / min(len(a), len(b)) > threshold:
				pairs += 1
	return pairs


def _component_action(
	component: str,
	meta: Dict[str, Any],
	metrics: Dict[str, Any],
	annotate_dir: Path,
	pipeline: Dict[str, Any],
) -> Tuple[str, str]:
	flags = meta.get("flags") or {}
	components = (pipeline.get("manifest") or {}).get("components") or {}
	if component in ("extract_work", "extract_social", "fragment_view", "schema"):
		return "process", "extract/vista cambiaron (sustancial: cambia el texto)"
	if component in ("voice_rewrite_prompt", "voice_rewrite_enabled"):
		voice_flags = int(flags.get("voice") or 0)
		first_person = float(metrics.get("pct_primera_persona") or 0.0)
		if voice_flags > 0 or first_person < 100.0:
			return "process", f"voz: {voice_flags} flags / {first_person:.1f}% 1a persona"
		return "skip", "voz sin defecto en esta sesión"
	if component == "bio":
		if int(flags.get("gender") or 0) > 0 or int(flags.get("identity") or 0) > 0 or int(metrics.get("bio_leaks") or 0) > 0:
			return "process", "bio: flags/leaks presentes"
		return "skip", "bio sin defecto en esta sesión"
	if component in ("work_scope", "social_scope"):
		routes = meta.get("routes") or {}
		min_margin = metrics.get("min_margin")
		dead_zone = float(((components.get("thresholds") or {}).get("dead_zone")) or 0.05)
		if int(routes.get("none") or 0) > 0 or (min_margin is not None and float(min_margin) < 2 * dead_zone):
			return "process", "scopes: notas en zona muerta"
		return "skip", "scopes sin efecto en esta sesión"
	if component == "dedup_policy":
		threshold = float((components.get("dedup_policy") or {}).get("threshold") or 0.6)
		if _notes_near_dups(annotate_dir, threshold) > 0:
			return "process", "dedup: near-dups residuales al umbral vigente"
		return "skip", "dedup sin near-dups residuales"
	if component in ("dual_score", "thresholds"):
		return "rescore", "scorer/umbrales: re-puntuar sin re-extraer"
	return "process", f"delta desconocido: {component}"


_PRIORITY = {"skip": 0, "rescore": 1, "process": 2}


def predicate_action(
	delta: List[str],
	meta: Dict[str, Any],
	metrics: Dict[str, Any],
	annotate_dir: Path,
	pipeline: Dict[str, Any],
) -> Tuple[str, str]:
	"""Traduce el delta a (acción, motivo) con prioridad process > rescore > skip
	(un delta mixto no puede quedar tapado por el primer componente: RFC §3.2)."""
	actions = [_component_action(c, meta, metrics, annotate_dir, pipeline) for c in sorted(set(delta))]
	best = max(actions, key=lambda pair: _PRIORITY[pair[0]])
	reasons = [f"{a}: {r}" for a, r in actions if a == best[0]]
	return best[0], "; ".join(reasons)


# ── evaluación + sello ───────────────────────────────────────────────────────


def evaluate(
	root: Path,
	dir_rel: str,
	*,
	pipeline: Dict[str, Any],
	engine: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
	"""Decisión para la sesión; None si el fast-path la salta (sin escritura)."""
	gate = read_gate(root, dir_rel)
	latest = gate.get("latest") or {}
	meta = read_meta(root, dir_rel)
	annotate_dir = root / dir_rel / "annotate"
	partial = (annotate_dir / "_partial.json").exists()
	input_hash = session_input_hash(root, dir_rel)
	current_hash = pipeline["manifest_hash"]

	if (
		latest.get("to_fingerprint") == current_hash
		and latest.get("input_hash") == input_hash
		and not partial
		and latest.get("state") in TERMINAL_STATES
	):
		return None  # fast-path: firma e input vigentes + terminal ⇒ nada que hacer
	if partial:
		return {"action": "process", "state": "pending", "reason": "resume-partial", "delta": [], "input_hash": input_hash}
	if latest.get("state") == "pending" and latest.get("to_fingerprint") == current_hash:
		# Re-emisión fiel (cubre `forced` de la remediación y pendientes a medias
		# entre re-invocaciones de `--list`): no se re-evalúan predicados.
		return {
			"action": str(latest.get("action") or "process"),
			"state": "pending",
			"reason": str(latest.get("reason") or "pendiente"),
			"delta": latest.get("delta") or [],
			"input_hash": input_hash,
			"keep_run_id": str(latest.get("run_id") or ""),  # la remediación no la pisa el sweep
		}
	if latest.get("input_hash") and input_hash and latest.get("input_hash") != input_hash:
		return {"action": "process", "state": "pending", "reason": "input cambió (re-render)", "delta": ["input"], "input_hash": input_hash}
	if engine and str(meta.get("engine") or "") and str(meta.get("engine")) != str(engine):
		return {"action": "process", "state": "pending", "reason": f"engine distinto: {meta.get('engine')} → {engine}", "delta": ["engine"], "input_hash": input_hash}

	old_manifest = meta.get("manifest")
	delta = manifest_delta(old_manifest, pipeline["manifest"])
	if delta is None:
		if str(meta.get("annotate_prompt_version") or "") == str(pipeline["legacy_fingerprint"]):
			return {"action": "skip", "state": "skipped", "reason": "versión vigente sin manifest (nada cambió)", "delta": [], "input_hash": input_hash}
		return {"action": "process", "state": "pending", "reason": "legacy sin manifest (delta desconocido)", "delta": ["legacy"], "input_hash": input_hash}
	if not delta:
		return {"action": "skip", "state": "skipped", "reason": "sin delta de manifest", "delta": [], "input_hash": input_hash}
	action, reason = predicate_action(delta, meta, meta.get("metrics") or {}, annotate_dir, pipeline)
	return {"action": action, "state": "skipped" if action == "skip" else "pending", "reason": reason, "delta": delta, "input_hash": input_hash}


def gate_session(
	root: Path,
	dir_rel: str,
	*,
	run_id: str,
	pipeline: Dict[str, Any],
	engine: Optional[str] = None,
) -> Dict[str, Any]:
	"""Evalúa y sella (salvo fast-path). Devuelve el resultado + `emit`."""
	decision = evaluate(root, dir_rel, pipeline=pipeline, engine=engine)
	if decision is None:
		latest = read_gate(root, dir_rel).get("latest") or {}
		return {"dir": dir_rel, "fast_path": True, "action": latest.get("action"), "state": latest.get("state"), "reason": latest.get("reason"), "emit": False}
	meta = read_meta(root, dir_rel)
	entry = seal(
		root,
		dir_rel,
		run_id=str(decision.get("keep_run_id") or run_id),
		action=decision["action"],
		state=decision["state"],
		reason=decision["reason"],
		delta=decision.get("delta"),
		from_fingerprint=str(meta.get("annotate_prompt_version") or "") or None,
		to_fingerprint=str(pipeline["manifest_hash"]),
		input_hash=decision.get("input_hash"),
	)
	emit = entry["action"] in EMITTABLE_ACTIONS and entry["state"] == "pending"
	return {"dir": dir_rel, "fast_path": False, "emit": emit, **entry}


# ── migración one-shot (F2b) ─────────────────────────────────────────────────


def _annotations_from_disk(annotate_dir: Path) -> List[Dict[str, Any]]:
	"""Notas finales en disco → lista apta para `compute_note_metrics`."""
	from red_pill.memento.ascension import parse_refine

	items: List[Dict[str, Any]] = []
	for path in sorted(annotate_dir.glob("*.md")):
		try:
			fm, body = parse_refine(path.read_text(encoding="utf-8", errors="replace"))
		except Exception:
			continue
		item: Dict[str, Any] = {"title": str(fm.get("title") or ""), "text": " ".join(body.split())}
		for key in ("work_score", "social_score"):
			raw_score = fm.get(key)
			if raw_score is None:
				continue
			try:
				item[key] = float(str(raw_score))
			except ValueError:
				pass
		items.append(item)
	return items


def migrate_session(root: Path, dir_rel: str, *, pipeline: Dict[str, Any], write: bool = True) -> str:
	"""Migración one-shot de una meta legacy: completa `manifest`+`metrics`+`input_hash`
	cuando la versión sellada ES la vigente (adopción, sin re-anotar); versiones
	irresolubles se reportan como `legacy-unknown` y NO se tocan (decisión del
	sweep). Devuelve `fresh|adopted|legacy-unknown|sin-meta|error`."""
	from red_pill.memento.agentic.annotate import compute_note_metrics

	meta_path = root / dir_rel / "annotate" / "_meta.json"
	meta = read_meta(root, dir_rel)
	if not meta:
		return "sin-meta"
	if meta.get("manifest"):
		return "fresh"
	if str(meta.get("annotate_prompt_version") or "") != str(pipeline["legacy_fingerprint"]):
		return "legacy-unknown"
	meta["manifest"] = pipeline["manifest"]
	meta["manifest_hash"] = pipeline["manifest_hash"]
	meta["metrics"] = compute_note_metrics(_annotations_from_disk(root / dir_rel / "annotate"), dedup_threshold=runtime.memento_dedup_threshold())
	meta["input_hash"] = session_input_hash(root, dir_rel)
	meta["input_hash_source"] = "index" if (root / dir_rel / "memento" / "index.md").exists() else "units"
	if write:
		from red_pill.memento.record import write_json_atomic

		write_json_atomic(meta_path, meta)
	return "adopted"
