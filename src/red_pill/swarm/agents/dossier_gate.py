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


def detect_findings(before: Dict[str, Any], after: Dict[str, Any]) -> bool:
	"""¿Hubo hallazgo entre dos estados? (definición L2: claim/pregunta/
	contradicción NUEVA — no cuenta rellenar contenido ni responder lo ya listado)."""
	def q_count(s: Dict[str, Any]) -> int:
		q = s.get("open_questions")
		return len(q) if isinstance(q, list) else 0

	def c_count(s: Dict[str, Any]) -> int:
		c = s.get("claims")
		return len(c) if isinstance(c, list) else 0

	return (
		q_count(after) > q_count(before)
		or c_count(after) > c_count(before)
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

		# Hallazgo del pase recién terminado: comparamos el estado ANTES del pase
		# (prev_counts) con el estado actual. El propio pase actualiza el state.yaml;
		# el gate solo mide la diferencia de contadores.
		prev_q = int(state.get("prev_open_questions", -1))
		prev_c = int(state.get("prev_claims", -1))
		had_findings = False
		if prev_q >= 0 and prev_c >= 0:
			before = {"open_questions": list(range(prev_q)), "claims": list(range(prev_c)), "contradictions": False}
			after = state
			had_findings = detect_findings(before, after)
		state = apply_hallazgo(state, had_findings)

		# Guardar snapshot de contadores para la próxima evaluación de hallazgo.
		state["prev_open_questions"] = len(state.get("open_questions") or [])
		state["prev_claims"] = len(state.get("claims") or [])

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
		job_id = self._enqueue_next_pass(kwargs, next_pass, state)
		return {"status": "success", "verdict": "continue", "next_pass": next_pass, "summary": f"pase siguiente encolado: {next_pass} ({job_id[:8] if job_id else '?'})", "state": state}

	def _enqueue_next_pass(self, kwargs: Dict[str, Any], next_pass: str, state: Dict[str, Any]) -> Optional[str]:
		"""Carga la receta del pase siguiente, inyecta dossier_dir/mission_id y la
		encola como dag_job con el mismo mission_id. Devuelve el job_id o None."""
		from red_pill.cognitive.queue_manager import CognitiveQueueManager
		from red_pill.jobs.recipes import load_recipe

		dossier_dir = kwargs.get("dossier_dir")
		mission_id = kwargs.get("mission_id")
		if not mission_id:
			raise RuntimeError("dossier_gate: mission_id requerido para re-encolar el pase siguiente.")
		if not dossier_dir:
			raise RuntimeError("dossier_gate: dossier_dir requerido para re-encolar el pase siguiente.")

		_source, payload, _prio, _parent, is_seed = load_recipe(f"dossier-{next_pass}")
		if is_seed:
			# La receta seed lleva modelos flash: hay que inyectar la config real
			# del loop (la receta del pase anterior trae el model en su payload,
			# no aquí). Si no hay modelo real disponible, el submit fallaría:
			# subimos el error — nunca encolamos un pase sin config de modelos.
			raise RuntimeError(f"receta dossier-{next_pass} es seed sin config real: copia su config a .red-pill/jobs/ (NOTE_MODEL_POLICY_ROLES).")
		payload.setdefault("mission_id", mission_id)
		payload["dossier_dir"] = str(dossier_dir)
		payload["manifest"]["stages"] = _inject_gate_params(payload["manifest"]["stages"], str(dossier_dir), mission_id)
		qm = CognitiveQueueManager()
		return qm.enqueue_task(source="dag_job", payload=payload, priority=5, mission_id=mission_id)


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
