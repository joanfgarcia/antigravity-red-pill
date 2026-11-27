"""Runner del pase agéntico: pendientes, re-destilado y checkpoint (RFC-002 §4.5.1)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from red_pill.memento.render import compute_hash, extract_body, update_frontmatter_fields

from . import runtime
from .distill import distill_session
from .fragments import work_units
from .refine import cross_ref_candidates, refine_session
from .runtime import Transport

logger = logging.getLogger(__name__)


def pending_agentic(
	registry: Any,
	root: Optional[Path] = None,
	force: bool = False,
	redistill_since: Optional[str] = None,
	*,
	phase: Optional[str] = None,
) -> List[Tuple[str, str, str]]:
	"""[(source, session_id, reason)] — sesiones renderizadas sin pase agéntico o con distill stale (§4.5.1).

	Recuperación ante crash (2026-09-07): el registry solo se guardaba al final
	del run — si el proceso moría (reboot), las sesiones ya destiladas en disco
	quedaban sin marcado `agentic` y se re-procesaban. Si `root` se pasa, una
	sesión sin `agentic` pero con `distill/`+`refine/` en disco se considera
	TERMINADA y no vuelve a la cola salvo `force=True` (re-procesado explícito).

	`redistill_since` (ISO): en modo `force`, SOLO se incluyen las sesiones cuyo
	`agentic.distilled_at` es anterior (o ausente). Así una redestilación
	reanudable reprocesa únicamente las que faltan, no las ya re-procesadas en
	la ronda (watchdog de reanudación, 2026-09-15).

	MEM-006 (2026-09-23): con `MEMENTO_ANNOTATE_FROM_RAW` ON, una sesión con
	`annotate/_meta.json` fresco (prompt_version vigente) se considera ya
	procesada aunque falte el marcado `agentic` — el rebuild masivo y el
	nocturno comparten el criterio de frescura y no se pisan (antes: solape
	31/31 en las never-distilled)."""
	import red_pill.config as cfg

	annotate_version: Optional[str] = None
	gate_pipeline: Optional[Dict[str, Any]] = None
	if root is not None and bool(getattr(cfg, "MEMENTO_ANNOTATE_FROM_RAW", False)):
		annotate_version = runtime.annotate_prompt_version()
	# E-97e9d2: con el flag OFF no existe la fase de notas (refine legacy necesita
	# las secciones de la corrida, no material previo). Devolver targets aquí solo
	# servía para que el pase los "procesara" sin escribir una nota.
	if phase == "annotate" and not bool(getattr(cfg, "MEMENTO_ANNOTATE_FROM_RAW", False)):
		logger.warning("[phase annotate] MEMENTO_ANNOTATE_FROM_RAW=false: sin sesiones que anotar.")
		return []
	if root is not None and bool(getattr(cfg, "MEMENTO_ANNOTATE_GATE", False)):
		from red_pill.memento import gating

		gate_pipeline = gating.current_pipeline()

	pending = []
	for source, sessions in registry.state["registry"].items():
		for session_id, entry in sessions.items():
			if not entry.get("dir"):
				continue
			agentic = entry.get("agentic")
			if agentic and redistill_since and str(agentic.get("distilled_at") or "") >= redistill_since:
				continue  # ya re-procesada en esta ronda
			if phase == "annotate":
				# Fase de notas: solo interesan las destiladas a las que les faltan
				# (o están viejas). Nunca re-destilar desde aquí.
				if not agentic:
					continue
				if force:
					pending.append((source, session_id, "annotate"))
				elif agentic.get("annotate_pending"):
					pending.append((source, session_id, "annotate"))
				elif annotate_version is not None and root is not None and not _annotate_fresh(root, entry["dir"], annotate_version):
					pending.append((source, session_id, "annotate"))
				continue
			if not agentic:
				if not force and root is not None and _distill_refine_present(root, entry["dir"]):
					continue  # ya destilada en disco, pero el marcado se perdió (crash)
				if not force and root is not None and gate_pipeline is not None:
					# MEM-010 F2b: el nocturno CONSULTA el gate (solo lectura; el
					# sweep del rebuild es quien sella) — skip/fast-path → no re-procesar.
					from red_pill.memento import gating

					gate_decision = gating.evaluate(root, entry["dir"], pipeline=gate_pipeline)
					if gate_decision is None or gate_decision.get("action") == "skip":
						continue
				elif not force and root is not None and annotate_version is not None and _annotate_fresh(root, entry["dir"], annotate_version):
					continue  # ya anotada desde raw (rebuild/nocturno) — no re-procesar
				pending.append((source, session_id, "missing"))
			elif agentic.get("hash") != entry.get("memento_hash"):
				if agentic.get("distill_hash") == entry.get("memento_hash"):
					# 2026-11-18: la fase de polaroids ya atestiguó ESTE hash; lo que
					# falta son las notas, no el destilado. Marcarlo `stale` compraba
					# un re-destilado completo y, peor, hacía que el janitor
					# `memento_stale` disparase `--heal-stale` sobre material al día.
					pending.append((source, session_id, "annotate"))
				else:
					pending.append((source, session_id, "stale"))
			elif force:
				# Re-procesado explícito: incluir las ya destiladas válidas
				# (p.ej. --only-long para re-distillar las truncadas).
				pending.append((source, session_id, "redistill"))
	return pending


def _distill_refine_present(root: Path, dir_rel: str) -> bool:
	"""True si la sesión ya tiene distill/ y refine/ con contenido en disco."""
	base = root / dir_rel
	distill = base / "distill"
	refine = base / "refine"
	return (distill.is_dir() and any(distill.glob("*.md"))) and (refine.is_dir() and any(refine.glob("*.md")))


def _annotate_fresh(root: Path, dir_rel: str, current_version: str) -> bool:
	"""MEM-006: `annotate/_meta.json` con el prompt_version vigente → la sesión ya
	pasó por el pase annotate (rebuild o nocturno); el nocturno no debe repetirla."""
	meta = root / dir_rel / "annotate" / "_meta.json"
	if not meta.exists():
		return False
	try:
		data = json.loads(meta.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return False
	return bool(data.get("annotate_prompt_version") == current_version)


def session_max_work_unit_chars(root: Path, dir_rel: str) -> int:
	"""Longitud (chars) del work unit más largo de una sesión (0 si no hay).

	Se usa para detectar sesiones "cortadas": work units que exceden la ventana
	del modelo anterior y se truncaron en el transporte (2026-09-14)."""
	try:
		return max((len(unit.content) for unit in work_units(root / dir_rel)), default=0)
	except Exception:
		return 0


def _is_llm_connection_error(exc: Exception) -> bool:
	"""True si la excepción indica que el LLM local no responde (connection refused / aborted / TIMEOUT).

	Distingue "el LLM no está o se colgó" (→ deferral) de un fallo real del
	trabajo. Los timeouts se incluyen desde 2026-09-15: una generación que
	excede `MEMENTO_LLM_TIMEOUT` es un cuelgue (watchdog), no un error del job.
	"""
	name = type(exc).__name__
	msg = str(exc)
	if name in (
		"NewConnectionError",
		"ConnectionError",
		"ConnectionRefusedError",
		"RemoteDisconnected",
		"ReadTimeout",
		"ConnectTimeout",
		"Timeout",
	):
		return True
	if "Connection refused" in msg or "Failed to establish a new connection" in msg or "Connection aborted" in msg:
		return True
	if "Remote end closed connection" in msg:
		return True
	if "timed out" in msg or "timedout" in msg.lower():
		return True
	low = msg.lower()
	# GPU ocupada sin alternativa (device_fallback=[gpu]): no es fallo del trabajo,
	# es entorno → deferral (2026-10-05, pin GPU-only de jobs de memoria).
	if "insufficient free vram" in low:
		return True
	# 2026-11-27 (ciclo 8a315ef2): el daemon VIVO pero incapaz de cargar el modelo
	# responde 503 — "VRAM insuficiente ... ningún KV cabe a ctx=..." o "No usable
	# device". `/v1/models` contesta 200, así que `llm_available()` lo daba por
	# bueno y los 60 pasos del nocturno se contaron como fallos de trabajo,
	# marcados `success`. Es entorno, no la sesión: se difiere.
	response = getattr(exc, "response", None)
	if getattr(response, "status_code", None) == 503:
		return True
	if "service unavailable" in low:
		return True
	if "vram insuficiente" in low or "ningún kv cabe" in low or "no usable device" in low:
		return True
	return False


# Fases del pase. Cada una puede servirse de un modelo distinto (task `distill`
# y task `annotate` en task_profiles.yaml), y cambiar de modelo en el daemon
# cuesta una carga: ~1,4 s a ~9 s según el modelo. Intercalar distill+annotate
# por sesión son DOS swaps por sesión (40 en una noche de 20); correr el pase
# por fases son dos por corrida.
PHASES = ("distill", "annotate")


def _distill_current(root: Path, entry: Dict[str, Any]) -> bool:
	"""¿La sesión ya tiene polariods de la versión de hash vigente?"""
	agentic = entry.get("agentic") or {}
	distill_ok = bool(agentic.get("distill_hash")) and agentic.get("distill_hash") == entry.get("memento_hash")
	return distill_ok or (bool(agentic) and agentic.get("hash") == entry.get("memento_hash"))


def run_agentic(
	root: Path,
	registry: Any,
	targets: List[Tuple[str, str]],
	transport: Transport,
	checkpoint_path: Optional[Path] = None,
	redistill_since: Optional[str] = None,
	*,
	phase: Optional[str] = None,
) -> Dict[str, int]:
	"""Distill → Refine → sello de significance + decisión shadow del gate, por sesión.

	`phase` (2026-10-30) parte el pase como lo hace el sueño REAL: una corrida
	dedicada a las polaroids y otra a las notas. Intercaladas, cada sesión
	obliga al daemon a cambiar de modelo dos veces (distill y annotate sirven
	modelos distintos); por fases, dos veces por CORRIDA.

	- `phase="distill"`: solo `distill_session`. No sella `agentic` (lo hace
	annotate, que es quien conoce la significance) pero sí `agentic.distill_hash`
	— el marcador honesto de "estas polaroids son de este hash".
	- `phase="annotate"`: solo `annotate_session`, y SOLO sobre sesiones cuyas
	polaroids ya están al día. Si faltan, la sesión se salta y se cuenta en
	`stats["skipped_distill"]` (en producción el DAG ya encadena annotate
	detrás de distill, así que es una red de seguridad, no el camino).
	EXIGE `MEMENTO_ANNOTATE_FROM_RAW` ON: la fase no tiene sustituto legacy
	(refine necesita las secciones destiladas en la MISMA corrida, o sea
	`phase=None`). Con el flag OFF se saltan las sesiones y se cuentan en
	`stats["skipped_annotate_disabled"]` sin tocar disco (E-97e9d2, 2026-11-19).
	- `phase=None`: comportamiento histórico, por sesión. Se conserva para el
	fan-out por sesión (`--target`) y para los tests existentes.

	Si `checkpoint_path` se da (modo bounded del script_job), se escribe un
	checkpoint JSON `{"processed": N, "total": T}` tras CADA sesión — la cuenta
	se lee del registry (no del lote actual), para que el resume tras un
	pause/kill continúe con el número correcto aunque el `--limit` del
	relanzamiento cambie. Con `redistill_since` (ronda), el checkpoint cuenta
	solo las sesiones de la ronda (reanudación del re-destilado).
	"""
	from datetime import datetime, timezone

	import red_pill.config as cfg

	min_significance = float(getattr(cfg, "MEMENTO_REFINE_MIN_SIGNIFICANCE", 0.3))
	gate_threshold = float(getattr(cfg, "MEMENTO_GATE_MIN_SIGNIFICANCE", 0.5))
	# RULE 4: lectura única del flag annotate (MEM-006). OFF → refine legacy
	# (solo válido en `phase=None`; ver guarda de la fase de notas abajo).
	use_annotate = bool(getattr(cfg, "MEMENTO_ANNOTATE_FROM_RAW", False))
	if use_annotate:
		from .annotate import annotate_session
	stats = {"processed": 0, "failed": 0, "would_ingest": 0, "static_ascended": 0}
	# E-97e9d2 (2026-11-19): la fase de notas con el flag OFF no tenía material.
	# `sections` solo existe si ESTA corrida destiló (`phase in (None, "distill")`),
	# así que el camino legacy acababa en `refine_session(sections=[])`: refine
	# vacía `refine/*.md` antes de iterar las secciones y después no escribe nada
	# → el pase borraba notas previas, sellaba `significance: 0.0` y marcaba la
	# sesión como anotada (`annotate_pending: False`), sin log de descarte. Se
	# salta en bloque, sin tocar el disco, y se declara en las stats.
	if phase == "annotate" and not use_annotate:
		stats["skipped_annotate_disabled"] = len(targets)
		stats["aborted_annotate_disabled"] = True
		logger.error(
			f"[phase annotate] MEMENTO_ANNOTATE_FROM_RAW=false: la fase de notas no tiene "
			f"sustituto legacy (refine exige las secciones de esta misma corrida) — "
			f"{len(targets)} sesión(es) saltadas sin escribir ni sellar nada. Encender el flag "
			f"o correr el pase histórico (sin --phase)."
		)
		# Una línea por sesión: el error de arriba explica el porqué UNA vez; esto deja
		# en el log qué sesiones concretas quedaron sin notas.
		for _source, session_id in targets:
			logger.info(f"[phase annotate] {session_id}: saltada (MEMENTO_ANNOTATE_FROM_RAW=false) — disco intacto")
		return stats
	# Umbral de deferral por LLM caído (2026-09-08): si N sesiones consecutivas
	# fallan por conexión al LLM local, el recurso no está disponible y esto NO
	# es un error del trabajo — abortar para que el runner lo difiera y lo
	# reintente cuando la GPU/LLM se liberen (regla job_dag_execution). No
	# acumular cientos de "failed" quemando intentos.
	CONSECUTIVE_CONNECTION_FAILURES = 3
	consecutive_failures = 0

	for source, session_id in targets:
		entry = registry.get(source, session_id)
		if not entry or not entry.get("dir"):
			continue
		if phase == "titles":
			# AD-148: fase propia, independiente de distill/annotate. Trabaja sobre
			# las notas ya escritas y solo renombra/sella; si falla a medias, el
			# checkpoint por nota permite reanudar sin volver a llamar al modelo.
			from . import titles as titles_mod

			result = titles_mod.run_titles(root, entry["dir"], session_id, source, transport)
			prev = entry.get("agentic") or {}
			entry["agentic"] = {
				**prev,
				"titles_version": titles_mod.title_prompt_version(),
				"titles_notes": int(result.get("titled") or 0),
				"titles_pending": int(result.get("pending") or 0),
				# AD-151: una nota ilegible se queda quieta y visible; si esto no
				# aparece en el registro, la sesión parece titulada al día.
				"titles_corrupt": int(result.get("corrupt") or 0),
			}
			stats["processed"] += 1
			if hasattr(registry, "save"):
				registry.save()
			if checkpoint_path is not None:
				_advance_checkpoint(checkpoint_path, registry, len(targets), redistill_since=redistill_since)
			continue
		if phase == "annotate" and not _distill_current(root, entry):
			# Fase de notas sin polaroids al día: no anotar sobre material viejo.
			# No es un fallo — la fase de distill lo resolverá en su corrida.
			stats["skipped_distill"] = stats.get("skipped_distill", 0) + 1
			logger.info(f"[phase annotate] {session_id}: sin polaroids al día — saltada")
			continue
		try:
			sections = None
			if phase in (None, "distill"):
				sections = distill_session(root, entry["dir"], session_id, source, transport)
			if phase == "distill":
				# Solo polaroids: la significance la pone la fase de notas. Se deja
				# el marcador de hash para que annotate sepa que el material es éste.
				prev = entry.get("agentic") or {}
				entry["agentic"] = {
					**prev,
					"distill_hash": entry.get("memento_hash"),
					"distilled_at": datetime.now(timezone.utc).isoformat(),
					"sections": len(sections or []),
					"engine": runtime.served_engine(),
					"distill_prompt_version": runtime.distill_prompt_version(),
					"annotate_pending": True,
				}
				stats["processed"] += 1
				if hasattr(registry, "save"):
					registry.save()
				if checkpoint_path is not None:
					_advance_checkpoint(checkpoint_path, registry, len(targets), redistill_since=redistill_since)
				continue
			if use_annotate:
				max_significance = annotate_session(root, entry["dir"], session_id, source, transport)
			else:
				candidates = cross_ref_candidates(registry, source, session_id)
				# En la rama de notas `sections` es None (no se destiló en esta corrida);
				# refine sólo corre en el camino histórico (`phase=None`), donde sí existe.
				max_significance = refine_session(root, entry["dir"], session_id, source, sections or [], candidates, transport, min_significance)
		except Exception as e:
			logger.warning(f"Agentic pass failed for {session_id}: {e}")
			stats["failed"] += 1
			if _is_llm_connection_error(e):
				consecutive_failures += 1
				# El fan-out del nocturno corre UN proceso por sesión (`--target`):
				# ahí no hay "3 consecutivos" que esperar. Un solo 503/VRAM ya dice
				# que el modelo no se puede cargar; si no, cada una de las 60 hojas
				# quema su step y el ciclo acaba en `success` sin producir nada
				# (ciclo 8a315ef2, 2026-11-27).
				if consecutive_failures >= CONSECUTIVE_CONNECTION_FAILURES or len(targets) == 1:
					stats["aborted_llm_down"] = True
					stats["defer_reason"] = f"{type(e).__name__}: {e}"
					logger.error(
						f"LLM local caído tras {consecutive_failures} fallo(s) consecutivo(s) "
						f"({session_id}) — abortando con deferral; {stats['processed']} ya procesadas quedan marcadas."
					)
					return stats
			else:
				consecutive_failures = 0  # fallo de otra naturaleza: no cuenta para el deferral
			continue

		consecutive_failures = 0  # una sesión OK resetea el contador

		would_ingest = max_significance >= gate_threshold
		index_file = root / entry["dir"] / "memento" / "index.md"
		if index_file.exists():
			# Invariante §4.5.1: el sello NO puede mover el cuerpo. La verificación
			# compara el hash del body ANTES vs DESPUÉS del sello (mismo fichero en
			# disco) — NUNCA contra el memento_hash del registry, que puede estar
			# stale por un re-render concurrente (2026-09-10: assert falso positivo
			# mató el backfill de 595 sesiones).
			before = compute_hash(extract_body(index_file.read_text(encoding="utf-8")))
			update_frontmatter_fields(index_file, {"significance": round(max_significance, 2)})
			after = compute_hash(extract_body(index_file.read_text(encoding="utf-8")))
			if before != after:
				# §4.5.1 violado: el frontmatter tocó el body (bug real del renderer).
				# Contar como fallo de esta sesión y CONTINUAR — el run no debe morir
				# por una sesión (crash-recovery ya cubre el resume).
				logger.error(
					f"§4.5.1 VIOLADO: el sello de significance movió el cuerpo de {session_id} — hash antes={before[:12]} después={after[:12]}."
				)
				stats["failed"] += 1
				consecutive_failures = 0
				continue
		prev_agentic = entry.get("agentic") or {}
		entry["agentic"] = {
			"distilled_at": datetime.now(timezone.utc).isoformat(),
			"hash": entry.get("memento_hash"),
			"distill_hash": entry.get("memento_hash"),
			# En la fase de notas no hay `sections` en memoria: se conserva la
			# cuenta de la fase de polaroids (o 0 si el marcado se perdió).
			"sections": len(sections) if sections is not None else int(prev_agentic.get("sections") or 0),
			"max_significance": round(max_significance, 2),
			"gate_would_ingest": would_ingest,
			# `engine` es quien puso la voz. En la fase de notas el modelo cargado
			# es el juez, no el destilador: se conserva el de la fase de polaroids.
			"engine": (prev_agentic.get("engine") or runtime.served_engine()) if phase == "annotate" else runtime.served_engine(),
			"distill_prompt_version": (
				(prev_agentic.get("distill_prompt_version") or runtime.distill_prompt_version())
				if phase == "annotate"
				else runtime.distill_prompt_version()
			),
			"refine_prompt_version": runtime.refine_prompt_version(),
			# Quién juzgó. Con el pase por fases puede NO ser quien puso la voz —
			# es justo el dato que hace falta para decidir si K2-7B es mejor juez.
			"engine_annotate": runtime.served_engine() if use_annotate else prev_agentic.get("engine_annotate"),
			"annotate_pending": False,
		}
		if use_annotate:
			# Trazabilidad del pase real (MEM-006): versión de prompt y notas del
			# meta por sesión, para que el registry diga la verdad con el flag ON.
			meta_notes = None
			try:
				import json as _json

				meta_notes = _json.loads((root / entry["dir"] / "annotate" / "_meta.json").read_text(encoding="utf-8")).get("notas")
			except Exception:
				pass
			entry["agentic"]["annotate_prompt_version"] = runtime.annotate_prompt_version()
			entry["agentic"]["annotate_notes"] = meta_notes
		stats["processed"] += 1
		stats["would_ingest"] += int(would_ingest)
		# Guardado incremental (2026-09-07): persistir el marcado POR SESIÓN para
		# que un crash/reboot no pierda lo ya hecho y re-procese (RFC-002 §4.5.1).
		if hasattr(registry, "save"):
			registry.save()
		if checkpoint_path is not None:
			_advance_checkpoint(checkpoint_path, registry, len(targets), redistill_since=redistill_since)

	# Fase 4 §3.3: ascenso estático tras el pase agéntico. En sombra por defecto
	# (MEMENTO_STATIC_ASCENSION_ENABLED=false → solo cuenta cuántos ascenderían);
	# el experimento de calibración (§6.9) lo flipea a true.
	if bool(getattr(cfg, "MEMENTO_STATIC_ASCENSION_ENABLED", False)):
		try:
			from red_pill.memento.ascension import ascend_by_threshold

			asc_stats = ascend_by_threshold(root, registry)
			stats["static_ascended"] = asc_stats.get("ascendidos", 0)
		except Exception as e:
			logger.warning(f"[STATIC-ASCENSION] fallo en run_agentic: {e}")
	return stats


def _advance_checkpoint(checkpoint_path: Path, registry: Any, total: int, redistill_since: Optional[str] = None) -> None:
	"""Escribe el checkpoint del modo bounded: `{"processed": N, "total": T}`.

	`processed` = sesiones con marcado `agentic` en el registry (no las del
	lote actual): así el resume tras pause/kill refleja el progreso GLOBAL y el
	driver cierra por contador cuando se alcanza el total.

	Con `redistill_since` (ronda de re-destilación), `processed` cuenta SOLO las
	sesiones de la ronda (distilled_at >= ronda): el contador refleja cuántas de
	las largas se han re-procesado y el bounded cierra al alcanzar el total de la
	ronda — no al contar todo el registry (que ya tenía agentic de antes)."""
	import json

	processed = 0
	for source, sessions in registry.state["registry"].items():
		if not isinstance(sessions, dict):
			continue
		for entry in sessions.values():
			agentic = entry.get("agentic")
			if not agentic:
				continue
			if redistill_since and str(agentic.get("distilled_at") or "") < redistill_since:
				continue
			processed += 1
	checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
	tmp = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
	tmp.write_text(json.dumps({"processed": processed, "total": total}), encoding="utf-8")
	tmp.replace(checkpoint_path)  # escritura atómica: el driver jamás lee un JSON a medias
