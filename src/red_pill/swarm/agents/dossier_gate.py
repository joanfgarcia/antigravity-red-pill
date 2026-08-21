"""DossierGateMinion — el gate del loop de ideación (RFC_DOSSIER_IDEACION §3.4/§3.6).

Pieza de CÓDIGO de la capa de ideación: la tabla de transición determinista que
decide qué pase sigue (o qué estado de parada alcanza el dossier). El gate NO
usa LLM — si la transición la eligiera un agente, volvería el goal drift de
AutoGPT (§1). Los PASES son agénticos; la SELECCIÓN es mecánica.

El dossier vive en una CARPETA (`Aleth_Core/ideas/<id>/` según L1): el README.md
es la ficha humana; `state.yaml` es el estado de máquina que este minion lee y
actualiza. Cada pase (germinación/investigación/síntesis/prueba) es una receta
dag_job (`configs/jobs/dossier-<pase>.yaml`); el gate es la ÚLTIMA etapa de cada
receta y, si el veredicto no es terminal, re-encola el pase siguiente con el
MISMO mission_id (§3.6: el ciclo vive fuera del árbol acíclico).

Estados de parada mapeados a la cola (§3.6):
	matured/dead         → el job completa (el motivo viaja en el resumen)
	awaiting_operator    → JobPauseRequested (PAUSED, cero intentos, se retoma con job resume)
	parked               → JobPauseRequested (pausa deliberada)
	superseded           → JobPauseRequested (v1: pausa con aviso; el dossier nuevo lo crea el operador)

Tope de pases (L2, ancla 3): DOBLE, parametrizable.
	- fijo (max_passes, default 20): red de seguridad anti-goal-drift.
	- dinámico (max_silent_passes, default 3): pasadas seguidas SIN hallazgos.
	Hallazgo = claim nuevo con evidencia, pregunta abierta nueva, o contradicción
	detectada. NO cuenta rellenar contenido ni responder preguntas ya listadas.

La lógica pura vive en `compute_verdict()` para testearla exhaustivamente; el
minion solo hace I/O (leer/escribir state.yaml, re-encolar).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from red_pill.swarm.base import Minion

# ── Límites por defecto (L2, parametrizables por la receta del gate) ──────────
DEFAULT_MAX_PASSES = 20
DEFAULT_MAX_SILENT_PASSES = 3

# Pases de la v1 (L3): germinación, investigación, síntesis, prueba de hipótesis.
PASSES = ("germination", "research", "synthesis", "hypothesis")

# Estados de parada (taxonomía completa §3.2).
_TERMINAL = ("matured", "dead")
_PAUSE_STATES = ("awaiting_operator", "parked", "superseded")


def compute_verdict(state: Dict[str, Any], limits: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
	"""Tabla de transición determinista (§3.4). Entrada: estado del dossier
	(state.yaml). Salida: {verdict, next_pass?}.

	Orden de evaluación (primera regla que aplique):

	1. status ya terminal/de pausa declarado por un pase previo → se respeta.
	2. Tope fijo: pases_ejecutados >= max_passes → awaiting_operator.
	3. type task → matured (una tarea no itera; el gate ni debería correr en ella).
	4. Criterio de madurez (L4): sin preguntas abiertas + claims con evidencia +
	sin contradicciones + viable → matured. VA ANTES del tope dinámico: un
	dossier maduro lo es aunque haya habido pasadas sin hallazgos.
	5. Tope DINÁMICO: pasadas_sin_hallazgos >= max_silent_passes →
	awaiting_operator. Antes de las reglas de continuación: si los pases ya no
	producen hallazgos y el dossier no madura, el loop no progresa — parar con
	juicio humano, no iterar en bucle (si fuera después, un dossier estancado
	iteraría sin fin).
	6. domain vacío / open_questions sin definir → germination.
	7. open_questions no vacío → research.
	8. claims vacío o algún claim sin evidencia → research.
	9. contradictions o viable == false → hypothesis (probar antes de decidir).
	10. viable == null → synthesis (aún no evaluado: coherencia pendiente).
	11. Por defecto → research (sigue explorando).
	"""
	limits = limits or {}
	max_passes = int(limits.get("max_passes", DEFAULT_MAX_PASSES))
	max_silent = int(limits.get("max_silent_passes", DEFAULT_MAX_SILENT_PASSES))

	status = state.get("status") or "spark"
	if status in _TERMINAL:
		return {"verdict": status}
	if status in _PAUSE_STATES:
		return {"verdict": status, "reason": state.get("pause_reason")}

	if int(state.get("pases_ejecutados", 0)) >= max_passes:
		return {"verdict": "awaiting_operator", "reason": f"tope fijo de pases alcanzado ({max_passes})"}

	if state.get("type") == "task":
		return {"verdict": "matured", "reason": "type task: no itera"}

	domain = state.get("domain")
	questions = state.get("open_questions")
	claims = state.get("claims")
	claims_ok = isinstance(claims, list) and len(claims) > 0 and all((c.get("evidence") if isinstance(c, dict) else False) for c in claims)
	no_questions = isinstance(questions, list) and len(questions) == 0
	if no_questions and claims_ok and not state.get("contradictions") and state.get("viable") is True:
		return {"verdict": "matured", "reason": "criterio L4: sin preguntas abiertas, claims con evidencia, coherente y viable"}

	if int(state.get("pasadas_sin_hallazgos", 0)) >= max_silent:
		return {
			"verdict": "awaiting_operator",
			"reason": f"tope dinámico alcanzado: {max_silent} pasadas sin hallazgos (el loop no progresa)",
		}

	if not domain or questions is None:
		return {"verdict": "continue", "next_pass": "germination"}

	if isinstance(questions, list) and len(questions) > 0:
		return {"verdict": "continue", "next_pass": "research"}

	if not claims_ok:
		return {"verdict": "continue", "next_pass": "research"}

	if state.get("contradictions") or state.get("viable") is False:
		return {"verdict": "continue", "next_pass": "hypothesis"}

	if state.get("viable") is None:
		return {"verdict": "continue", "next_pass": "synthesis"}

	return {"verdict": "continue", "next_pass": "research"}


def apply_hallazgo(state: Dict[str, Any], had_findings: bool) -> Dict[str, Any]:
	"""Actualiza los contadores del loop tras un pase (L2 dinámico).

	had_findings = el pase produjo algún hallazgo (claim/pregunta/contradicción
	nueva). Con hallazgo → se resetea `pasadas_sin_hallazgos`; sin él → +1.
	Siempre incrementa `pases_ejecutados`. Devuelve el estado nuevo.
	"""
	state = dict(state)
	state["pases_ejecutados"] = int(state.get("pases_ejecutados", 0)) + 1
	if had_findings:
		state["pasadas_sin_hallazgos"] = 0
	else:
		state["pasadas_sin_hallazgos"] = int(state.get("pasadas_sin_hallazgos", 0)) + 1
	return state


def _claim_key(c: Any) -> str:
	"""Clave estable de un claim para comparar entre pases."""
	if isinstance(c, dict):
		return str(c.get("id") or c.get("claim") or c)
	return str(c)


def detect_findings(before: Dict[str, Any], after: Dict[str, Any]) -> bool:
	"""¿Hubo hallazgo entre dos estados? (definición L2: claim/pregunta/
	contradicción NUEVA). Comparación por CONTENIDO, no por conteo: responder
	una pregunta y abrir otra en el mismo pase ES un hallazgo aunque el conteo
	no cambie; una contradicción que PERSISTE de un pase anterior NO lo es."""
	def _qs(s: Dict[str, Any]) -> set:
		q = s.get("open_questions")
		return {str(x) for x in q} if isinstance(q, list) else set()

	def _cs(s: Dict[str, Any]) -> set:
		c = s.get("claims")
		return {_claim_key(x) for x in c} if isinstance(c, list) else set()

	return (
		bool(_qs(after) - _qs(before))
		or bool(_cs(after) - _cs(before))
		or (bool(after.get("contradictions")) and not bool(before.get("contradictions")))
	)


class DossierGateMinion(Minion):
	"""Minion de lógica pura: lee el dossier, ejecuta la tabla, re-encola o para.

	Params (kwargs de la etapa `type: command` con `minion: dossier_gate`):
		dossier_dir   — carpeta del dossier (obligatorio).
		mission_id    — mission_id del loop (obligatorio para re-encolar).
		max_passes / max_silent_passes — topes L2 (opcionales, defaults arriba).
	"""

	name: str = "Dossier-Gate"
	specialization: str = "ideation_loop_gate"

	async def execute(self, task: str, **kwargs: Any) -> Dict[str, Any]:
		from pathlib import Path

		import yaml

		dossier_dir = Path(kwargs.get("dossier_dir") or task)
		state_path = dossier_dir / "state.yaml"

		if not state_path.is_file():
			return {"status": "error", "error": f"dossier state.yaml no encontrado en {dossier_dir}"}

		state = yaml.safe_load(state_path.read_text(encoding="utf-8")) or {}
		limits = {
			"max_passes": int(kwargs.get("max_passes", DEFAULT_MAX_PASSES)),
			"max_silent_passes": int(kwargs.get("max_silent_passes", DEFAULT_MAX_SILENT_PASSES)),
		}

		# Idempotencia (contrato del runner: steps tolerantes a re-ejecución).
		# Un resume tras pausa re-ejecuta este gate para el MISMO job: los
		# contadores del loop solo avanzan la primera vez que este job lo corre.
		job_id = str(kwargs.get("job_id") or "")
		rerun = bool(job_id) and state.get("last_gate_job_id") == job_id
		if not rerun:
			# Hallazgo del pase recién terminado: comparar el snapshot del estado
			# ANTERIOR (listas reales, no conteos) con el estado actual. El propio
			# pase actualiza el state.yaml; el gate solo mide la diferencia.
			before = {
				"open_questions": state.get("prev_questions_snapshot") or [],
				"claims": state.get("prev_claims_snapshot") or [],
				"contradictions": bool(state.get("prev_contradictions")),
			}
			had_findings = bool(state.get("prev_seen")) and detect_findings(before, state)
			state = apply_hallazgo(state, had_findings)

			# Snapshot para la próxima evaluación (contenido, no conteos).
			state["prev_questions_snapshot"] = [str(q) for q in (state.get("open_questions") or [])]
			state["prev_claims_snapshot"] = [_claim_key(c) for c in (state.get("claims") or [])]
			state["prev_contradictions"] = bool(state.get("contradictions"))
			state["prev_seen"] = True
			if job_id:
				state["last_gate_job_id"] = job_id

		verdict = compute_verdict(state, limits)
		state["verdict"] = verdict.get("verdict")
		state_path.write_text(yaml.safe_dump(state, allow_unicode=True, sort_keys=False), encoding="utf-8")

		if verdict["verdict"] in _TERMINAL:
			return {"status": "success", "verdict": verdict["verdict"], "summary": f"dossier {verdict['verdict']}: {verdict.get('reason', '')}", "state": state}

		if verdict["verdict"] in _PAUSE_STATES:
			from red_pill.jobs.drivers.base import JobPauseRequested

			raise JobPauseRequested(f"dossier {verdict['verdict']}: {verdict.get('reason', 'requiere juicio del operador')}")

		# continue → re-encolar el pase siguiente con el MISMO mission_id (§3.6).
		next_pass = verdict.get("next_pass")
		if next_pass not in PASSES:
			return {"status": "error", "error": f"pase desconocido '{next_pass}'", "state": state}
		next_job_id: Optional[str] = self._enqueue_next_pass(kwargs, next_pass, state)
		return {"status": "success", "verdict": "continue", "next_pass": next_pass, "summary": f"pase siguiente encolado: {next_pass} ({next_job_id[:8] if next_job_id else '?'})", "state": state}

	def _enqueue_next_pass(self, kwargs: Dict[str, Any], next_pass: str, state: Dict[str, Any]) -> Optional[str]:
		"""Delegado en `enqueue_pass` (única puerta de encolado del loop)."""
		dossier_dir = kwargs.get("dossier_dir")
		mission_id = kwargs.get("mission_id")
		if not mission_id:
			raise RuntimeError("dossier_gate: mission_id requerido para re-encolar el pase siguiente.")
		if not dossier_dir:
			raise RuntimeError("dossier_gate: dossier_dir requerido para re-encolar el pase siguiente.")
		return enqueue_pass(next_pass, str(dossier_dir), str(mission_id), current_job_id=str(kwargs.get("job_id") or ""))


def _interpolate_dossier_prompts(stages: List[Dict[str, Any]], dossier_dir: str) -> List[Dict[str, Any]]:
	"""Sustituye el literal `{dossier_dir}` en los prompts de TODAS las etapas
	(recursivo). `str.replace`, NUNCA `str.format`: cualquier otra llave del
	prompt rompería el render. Sin esto, el pase agéntico recibía el
	placeholder crudo y no sabía dónde vive el dossier."""
	import copy

	out = copy.deepcopy(stages)

	def _walk(nodes: List[Dict[str, Any]]) -> None:
		for s in nodes:
			if isinstance(s.get("prompt"), str):
				s["prompt"] = s["prompt"].replace("{dossier_dir}", dossier_dir)
			if isinstance(s.get("sub_etapas"), list):
				_walk(s["sub_etapas"])

	_walk(out)
	return out


def enqueue_pass(next_pass: str, dossier_dir: str, mission_id: str, priority: int = 5, current_job_id: str = "") -> Optional[str]:
	"""Encola UN pase del loop de ideación — la única puerta de encolado del
	loop (arranque del primer pase y re-encolado del gate, §3.6 del RFC).

	Renderiza la receta para ESTE dossier (interpola `{dossier_dir}` en los
	prompts, inyecta params al gate, fija el mission_id del loop) y aplica las
	MISMAS garantías que el submit del CLI/MCP: `validate()` (fail-safe de
	modelos) y `expand_manifest()` (aplana `type: dag`). Devuelve el job_id.

	IDEMPOTENTE POR MISIÓN: el loop mantiene UN job vivo por `mission_id`
	(pases secuenciales). Si la misión ya tiene un job vivo distinto del
	actual, NO se encola un duplicado — se devuelve el existente. Esto hace
	seguro el re-run del gate (contrato at-least-once del runner: resume tras
	pausa o crash re-ejecuta el step) y cubre también el crash entre la
	persistencia del state y el enqueue. FRUSTRATED queda fuera del guard: un
	pase muerto no debe bloquear la resurrección manual del loop.

	Arranque manual de un dossier (hasta que exista camino de chispa):
		uv run python -c "from red_pill.swarm.agents.dossier_gate import enqueue_pass; \
			print(enqueue_pass('germination', '/ruta/a/Aleth_Core/ideas/<id>', 'dossier-<id>'))"
	"""
	from red_pill.cognitive.queue_manager import CognitiveQueueManager
	from red_pill.jobs.drivers.dag import DagJobDriver
	from red_pill.jobs.recipes import load_recipe

	if next_pass not in PASSES:
		raise ValueError(f"pase desconocido '{next_pass}' (válidos: {PASSES}).")
	qm = CognitiveQueueManager()
	alive = [
		t for t in qm.list_tasks(statuses=["PENDING", "PROCESSING", "PAUSING", "PAUSED", "BLOCKED"], mission_id=mission_id)
		if t.get("id") != current_job_id
	]
	if alive:
		return alive[0].get("id")
	_source, payload, _prio, _parent, is_seed = load_recipe(f"dossier-{next_pass}")
	if is_seed:
		raise RuntimeError(
			f"receta dossier-{next_pass} es seed sin config real: copia la config activa a "
			"<repo-del-kernel>/.red-pill/jobs/ — el runner resuelve recetas subiendo desde SU CWD, "
			"no desde el dossier (NOTE_MODEL_POLICY_ROLES)."
		)
	payload["mission_id"] = mission_id  # asignación: pisa el 'dossier-loop' de fábrica
	payload["dossier_dir"] = str(dossier_dir)
	stages = _interpolate_dossier_prompts(payload["manifest"]["stages"], str(dossier_dir))
	payload["manifest"]["stages"] = _inject_gate_params(stages, str(dossier_dir), mission_id)
	DagJobDriver.validate(payload)
	payload = DagJobDriver.expand_manifest(payload)
	return qm.enqueue_task(source="dag_job", payload=payload, priority=priority, mission_id=mission_id)


def _inject_gate_params(stages: List[Dict[str, Any]], dossier_dir: str, mission_id: str) -> List[Dict[str, Any]]:
	"""La ÚLTIMA etapa de la receta de pase es el gate: le inyectamos los params
	(dossier_dir, mission_id) para que pueda leer el dossier y re-encolar."""
	import copy

	out = copy.deepcopy(stages)
	if not out:
		return out
	gate = out[-1]
	if gate.get("minion") == "dossier_gate":
		gate.setdefault("params", {})
		gate["params"]["dossier_dir"] = str(dossier_dir)
		gate["params"]["mission_id"] = mission_id
	return out
