"""DagJobDriver — plantilla genérica de composición recursiva (RFC_JOB_DAG v0.7).

Ejecuta un ÁRBOL de etapas en la cola central: cada etapa es ATOMICA (un minion
del MinionFactory, agéntico o no) o COMPUESTA (sub_etapas con topología local).
sleep (y el forge histórico) son recetas de este árbol — el dag_job implementa la
mecánica una sola vez (checkpoint, on_fail, telemetría, fan-out, control
transferible, GPU probe, fail-safe de modelos).

Manifest recursivo (§4.1 del RFC):

	stages:
		# Etapa ATOMICA (hoja): un minion agéntico o no-agéntico.
		- id: impl
		type: agent                 # agent | command | compound
		minion: agent               # id del MinionFactory — validado contra type
		backend: opencode-go
		model: opencode-go/deepseek-v4-pro
		prompt: <FULL role prompt>
		on_fail: stop

		- id: lint
		type: command
		minion: ruff_linter         # alias de command_runner

		# Etapa COMPUESTA (sub-DAG) con intención paralela (la ejecución la decide
		# el orquestador según max_parallel_level — `parallel` es INTENCIÓN).
		- id: panel-adversarial
		type: compound
		parallel: true
		on_fail: warn
		sub_etapas:
			- id: lens-correctness
			type: agent
			minion: agent
			model: opencode/big-pickle
			- id: judge
			type: agent
			minion: agent
			model: opencode-go/kimi-k2.7-code
			depends_on: [lens-correctness]

		# Etapa RECURSIVA (sub-etapa a su vez compuesta) — D5.
		- id: mision-deep
		type: compound
		on_fail: stop
		sub_etapas:
			- id: pre-flight
			type: agent
			minion: agent
			- id: full-sleep
			type: compound
			parallel: true          # nivel 2
			sub_etapas:
				- id: maintenance
				type: command
				minion: janitor_cleanup

Checkpoint (autoritativo, en BD): { completed_stage_ids, results, stage_flags }.
Los ids se APLANAN POR RUTA (`panel-adversarial/lens-correctness`) para que el
orden topológico y el resume sean deterministas a cualquier profundidad. Cada
etapa atómica persiste SU resultado en `.cell/reports/<ruta>.json` (opción 3 del
RFC: el DAG serializa, los minions NO se tocan). En etapas AGÉNTICAS el envelope
del minion va a `.cell/reports/<ruta>.envelope.json` y `<ruta>.json` queda para
el reporte de rol que escribe el propio agente (contrato zero-trust); el padre solo marca
stage_flags[sub]=done y delega el detalle — no hay orden de hilos que normalizar.

`parallel` es INTENCIÓN declarativa: una etapa compuesta puede declararla a
cualquier profundidad; el orquestador decide cuándo paraleliza realmente
(max_parallel_level, default 2). Nivel > cota → secuencial sin error.

CONTROL TRANSFERIBLE: el checkpoint del DAG es la moneda compartida main-loop ↔
driver (job_transfer → ejecuta etapas inline → job_checkpoint {completed_stage_ids}
→ job_resume) sobre el árbol completo.

payload:
	{
		"mission_id": str,
		"manifest": {
			"workdir": str,
			"stages": [ ...arbol recursivo... ]
		},
		"max_parallel_level"?: int,   # default 2 (paralelismo real permitido)
		"max_concurrency"?: int,      # cota de sub-etapas concurrentes (default 4)
		"backend"?: str, "model"?: str, "effort"?: str,   # defaults para agent
		"timeout"?: int, "title"?: str,
	}
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import json
import logging
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from red_pill.jobs.drivers.base import JobDeferred, JobPauseRequested, ResumableJobDriver, StepOutcome

logger = logging.getLogger(__name__)

_MAX_PARALLEL_LEVEL_DEFAULT = 2
_MAX_CONCURRENCY_DEFAULT = 4

# Tipos de etapa del manifest (ampliados por decisión de operador 2026-08-07:
# `type` explícito + `minion` con validación cruzada — la redundancia sirve para
# detectar divergencias en el submit, no para definir el comportamiento).
_TYPE_AGENT = "agent"
_TYPE_COMMAND = "command"
_TYPE_COMPOUND = "compound"
_TYPE_DAG = "dag"  # cuarto tipo (RFC_JOB_DAG §4.5): composición por referencia
_VALID_TYPES = (_TYPE_AGENT, _TYPE_COMMAND, _TYPE_COMPOUND, _TYPE_DAG)


class _GroupPauseGate:
	"""Puerta de pausa compartida por las etapas de UN grupo paralelo del DAG.

	La sonda de pausa de cada etapa en vuelo registra aquí su solicitud
	(`request_pause`) y consulta si TODAS las etapas aún corriendo son pausables
	(`can_pause`). La regla del operador: la pausa a mitad de un grupo paralelo
	solo se honra cuando todos los que siguen en vuelo son pausables; si alguno
	no lo es, se difiere y se reevalúa en cada frontera de completación, de modo
	que el trabajo ya completado (pausables o no) se preserva en el checkpoint.
	"""
	def __init__(self, group: List[Tuple[str, Dict[str, Any]]]):
		self._lock = threading.Lock()
		self._running = {path for path, _ in group}
		self._pausable = {path: bool(stage.get("pausable", True)) for path, stage in group}
		self._pause_requested = False

	def finished(self, path: str) -> None:
		with self._lock:
			self._running.discard(path)

	def request_pause(self) -> None:
		with self._lock:
			self._pause_requested = True

	def can_pause(self) -> bool:
		with self._lock:
			return all(self._pausable[p] for p in self._running)

	def pause_requested(self) -> bool:
		with self._lock:
			return self._pause_requested


def _gpu_health_probe() -> Tuple[bool, int, int]:
	"""Probe de salud GPU real (D7), generalizado desde sleep.py: nvidia-smi exit 0
	+ VRAM efectiva + -ngl efectivo. Devuelve (usable, free_mb, ngl).
	"""
	if not shutil.which("nvidia-smi"):
		return False, 0, 0
	try:
		free_out = subprocess.run(
			["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
			capture_output=True,
			text=True,
			timeout=5,
		)
		if free_out.returncode != 0:
			return False, 0, 0
		free_mb = int(free_out.stdout.strip().split("\n")[0].strip())
	except Exception:
		return False, 0, 0

	ngl = -1
	try:
		ps = subprocess.run(["pgrep", "-af", "llama-server"], capture_output=True, text=True, timeout=5)
		for line in (ps.stdout or "").splitlines():
			low = line.lower()
			if "-ngl" in low:
				parts = line.split()
				for i, part in enumerate(parts):
					if part.startswith("-ngl"):
						try:
							# Soporta `-ngl=33`, `-ngl33` y `-ngl 33` (valor en el
							# siguiente token).
							if "=" in part:
								ngl = int(part.split("=")[-1])
							elif part != "-ngl" and part[4:].lstrip("-").isdigit():
								ngl = int(part[4:])
							elif i + 1 < len(parts):
								ngl = int(parts[i + 1])
						except Exception:
							ngl = 0
						break
	except Exception:
		pass

	return True, free_mb, ngl


def _resolve_minion_kind(minion_id: str) -> Optional[str]:
	"""Resuelve el minion vía MinionFactory y devuelve 'agent' | 'command' | 'logic' | None.

	None = minion_id no registrado. 'logic' = minion de lógica pura (echo, janitor,
	healer, smith, samantha) — no-agéntico pero sin comando externo. Distinción
	crítica para el fail-safe de modelos: solo 'agent' exige `model`+`prompt`.
	"""
	from red_pill.swarm.agents.agent import AgentMinion
	from red_pill.swarm.agents.command import CommandMinion
	from red_pill.swarm.factory import MinionFactory

	minion = MinionFactory.create(minion_id)
	if minion is None:
		return None
	if isinstance(minion, AgentMinion):
		return _TYPE_AGENT
	if isinstance(minion, CommandMinion):
		return _TYPE_COMMAND
	return "logic"


def _iter_leaves(stages: List[Dict[str, Any]], prefix: str = ""):
	"""Itera las etapas ATOMICAS (hojas) del árbol como (ruta, etapa), DFS estable."""
	for s in stages:
		path = f"{prefix}/{s['id']}" if prefix else s["id"]
		if s.get("type") == _TYPE_COMPOUND:
			yield from _iter_leaves(s.get("sub_etapas", []), path)
		else:
			yield path, s


def _flatten_ids(stages: List[Dict[str, Any]], prefix: str = "") -> List[str]:
	"""Todos los ids aplanados por ruta (incluidos compuestos), orden DFS."""
	out: List[str] = []
	for s in stages:
		path = f"{prefix}/{s['id']}" if prefix else s["id"]
		out.append(path)
		if s.get("type") == _TYPE_COMPOUND:
			out.extend(_flatten_ids(s.get("sub_etapas", []), path))
	return out


def _count_leaves(stages: List[Dict[str, Any]]) -> int:
	return sum(1 for _ in _iter_leaves(stages))


def _apply_recipe_defaults(stages: List[Dict[str, Any]], defaults: Dict[str, Any]) -> None:
	"""Copia los defaults agénticos top-level de una RECETA referenciada a sus
	etapas `agent` sin valor propio. Sin esto, validate() aprobaba la etapa
	contra el payload de la receta y el runtime la ejecutaba contra el payload
	del PADRE — el fail-safe de modelos quedaba burlado por composición."""
	for s in stages:
		if s.get("type") == _TYPE_AGENT:
			for key in ("backend", "model", "effort"):
				if not s.get(key) and defaults.get(key):
					s[key] = defaults[key]
		elif s.get("type") == _TYPE_COMPOUND:
			_apply_recipe_defaults(s.get("sub_etapas", []), defaults)


def _resolve_on_fail(stages: List[Dict[str, Any]], leaf_path: str) -> str:
	"""`on_fail` efectivo de una hoja: el suyo, o el del ancestro más cercano.

	`on_fail` en una etapa COMPUESTA era letra muerta (solo se leía en hojas):
	un `on_fail: stop` de fase se aceptaba en el manifest y no acotaba nada. Con
	recetas que el propio sistema puede escribir (REP-RAP), un campo que el
	validador admite y el motor ignora es una vía de deriva silenciosa. Lo más
	específico gana: la hoja pisa a su ancestro. La resolución es POR RUTA — un
	homónimo de otra rama jamás decide el on_fail de esta.
	"""
	parts = leaf_path.split("/")
	node = _find_node_by_path(stages, leaf_path)
	if node and node.get("on_fail"):
		return str(node["on_fail"])
	for i in range(len(parts) - 1, 0, -1):  # ancestros por ruta, del más cercano al raíz
		ancestor = _find_node_by_path(stages, "/".join(parts[:i]))
		if ancestor and ancestor.get("on_fail"):
			return str(ancestor["on_fail"])
	return "warn"


def _find_node_by_path(stages: List[Dict[str, Any]], path: str) -> Optional[Dict[str, Any]]:
	"""Resuelve una etapa por su RUTA aplanada (`panel/lens-a`), descendiendo nivel
	a nivel. Las RUTAS son únicas (validate); los ids sueltos NO lo son entre
	ramas (F1/implementor y F2/implementor conviven) — resolver por id global
	devolvía el homónimo de otra rama, con su on_fail/parallel equivocados."""
	nodes = stages
	node: Optional[Dict[str, Any]] = None
	for part in path.split("/"):
		node = next((s for s in nodes if s.get("id") == part), None)
		if node is None:
			return None
		nodes = node.get("sub_etapas", []) if node.get("type") == _TYPE_COMPOUND else []
	return node


class DagJobDriver(ResumableJobDriver):
	source = "dag_job"
	min_vram_mb = 0  # los recursos se gestionan por etapa en preflight (GPU probe)

	# Marca de inicio del step en curso (monotónica) — base de la cota de tiempo.
	_step_started: Optional[float] = None

	# ── Validación en el submit (recursiva sobre el árbol) ─────────────────────
	@classmethod
	def validate(cls, payload: Dict[str, Any]) -> None:
		if not payload.get("mission_id"):
			raise ValueError("dag_job payload requires 'mission_id'.")
		manifest = payload.get("manifest")
		if not isinstance(manifest, dict) or not manifest.get("workdir"):
			raise ValueError("dag_job manifest requires 'workdir'.")
		stages = manifest.get("stages")
		if not isinstance(stages, list) or not stages:
			raise ValueError("dag_job manifest requires 'stages' (non-empty).")
		seen: List[str] = []
		cls._validate_stages(stages, payload, seen, path="")

	@classmethod
	def _validate_stages(cls, stages: List[Dict[str, Any]], payload: Dict[str, Any], seen: List[str], path: str, recipe_stack: Optional[List[str]] = None) -> None:
		if recipe_stack is None:
			recipe_stack = []
		for s in stages:
			sid = s.get("id")
			if not sid:
				raise ValueError("dag_job stage requires 'id'.")
			stage_path = f"{path}/{sid}" if path else sid
			if stage_path in seen:
				raise ValueError(f"dag_job duplicate stage path '{stage_path}' (los ids son únicos globalmente).")
			seen.append(stage_path)

			stype = s.get("type")
			if stype not in _VALID_TYPES:
				raise ValueError(f"dag_job stage '{stage_path}' type '{stype}' not in agent|command|compound|dag.")
			# `on_fail` se documenta en el manifest (RFC §7) pero nunca se validaba:
			# una errata quedaba como 'warn' silencioso. Vale en cualquier nivel —
			# en compuestos lo heredan sus hojas (_resolve_on_fail).
			on_fail = s.get("on_fail")
			if on_fail is not None and on_fail not in ("warn", "stop"):
				raise ValueError(f"dag_job stage '{stage_path}' on_fail '{on_fail}' not in warn|stop.")
			if stype == _TYPE_DAG:
				# Composición por REFERENCIA (RFC_JOB_DAG §4.5): la etapa ejecuta
				# OTRA receta dag_job como sub-misión. Se valida resolviendo la
				# receta en el submit y validando su árbol recursivamente.
				recipe_ref = s.get("recipe")
				if not isinstance(recipe_ref, str) or not recipe_ref:
					raise ValueError(f"dag_job stage '{stage_path}' type dag requires 'recipe' (nombre o ruta de receta).")
				if s.get("minion") or s.get("sub_etapas"):
					raise ValueError(f"dag_job dag stage '{stage_path}' must not carry minion/sub_etapas (vienen de la receta).")
				if recipe_ref in recipe_stack:
					raise ValueError(f"dag_job receta cíclica: '{recipe_ref}' ya está en la cadena {recipe_stack}.")
				sub_source, sub_payload, _prio, _parent, _is_seed = cls._load_recipe(recipe_ref)
				if sub_source != "dag_job":
					raise ValueError(f"dag_job stage '{stage_path}' recipe '{recipe_ref}' es source '{sub_source}', no dag_job.")
				sub_stages = (sub_payload.get("manifest") or {}).get("stages")
				if not isinstance(sub_stages, list) or not sub_stages:
					raise ValueError(f"dag_job stage '{stage_path}' recipe '{recipe_ref}' no tiene manifest.stages.")
				cls._validate_stages(sub_stages, sub_payload, seen, path=stage_path, recipe_stack=recipe_stack + [recipe_ref])
			elif stype == _TYPE_COMPOUND:
				if s.get("minion"):
					raise ValueError(f"dag_job compound stage '{stage_path}' must not carry a minion.")
				sub = s.get("sub_etapas")
				if not isinstance(sub, list) or not sub:
					raise ValueError(f"dag_job compound stage '{stage_path}' requires 'sub_etapas' (non-empty).")
				cls._validate_stages(sub, payload, seen, path=stage_path)
			else:
				minion_id = s.get("minion")
				if not minion_id:
					raise ValueError(f"dag_job stage '{stage_path}' requires 'minion'.")
				kind = _resolve_minion_kind(minion_id)
				if kind is None:
					raise ValueError(f"dag_job stage '{stage_path}' minion '{minion_id}' no registrado en MinionFactory.")
				if stype == _TYPE_AGENT:
					if kind != _TYPE_AGENT:
						raise ValueError(f"dag_job stage '{stage_path}' type mismatch: minion '{minion_id}' no es agéntico.")
					# Fail-safe de modelos (fleco 3 del RFC): TODA etapa agéntica del
					# árbol exige model real (no el placeholder 'flash' del harness).
					model = s.get("model") or payload.get("model")
					if not model or model == "flash":
						raise ValueError(
							f"dag_job stage '{stage_path}' (agent) sin modelo configurado. "
							"'flash' es el placeholder del default, no una config activa. "
							"Indica 'model' con un modelo real (p.ej. opencode-go/deepseek-v4-pro). "
							"Bloqueado por seguridad (fail-safe de modelos)."
						)
					if not s.get("prompt"):
						raise ValueError(f"dag_job agent stage '{stage_path}' requires 'prompt'.")
				else:
					if kind == _TYPE_AGENT:
						raise ValueError(f"dag_job stage '{stage_path}' type mismatch: minion '{minion_id}' es agéntico, no '{stype}'.")
			for dep in s.get("depends_on", []):
				# las deps referencian hermanos (ids del mismo nivel)
				dep_path = f"{path}/{dep}" if path else dep
				if dep_path not in seen:
					raise ValueError(f"dag_job stage '{stage_path}' depends_on unknown '{dep}'.")

	@classmethod
	def _load_recipe(cls, reference: str) -> Tuple[str, Dict[str, Any], int, Optional[str], bool]:
		"""Resuelve una receta con el MISMO mecanismo del CLI (RECIPE_DIRS)."""
		from red_pill.jobs.recipes import load_recipe

		return load_recipe(reference, base_dir=None)

	@classmethod
	def expand_manifest(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
		"""Aplana las etapas `type: dag` a `compound` con las stages de la receta.

		Se llama en el SUBMIT (CLI/MCP) tras validate: el job se persiste con el
		árbol ya expandido, de modo que step()/checkpoint/resume trabajan SIEMPRE
		sobre compounds y hojas — el determinismo del resume no depende de que la
		receta siga igual en disco (RFC_JOB_DAG §4.5). Devuelve un payload nuevo
		(sin mutar el original).
		"""
		expanded = copy.deepcopy(payload)
		expanded["manifest"]["stages"] = cls._expand_stages(expanded["manifest"]["stages"], recipe_stack=[])
		return expanded

	@classmethod
	def _expand_stages(cls, stages: List[Dict[str, Any]], recipe_stack: List[str]) -> List[Dict[str, Any]]:
		out: List[Dict[str, Any]] = []
		for s in stages:
			if s.get("type") == _TYPE_DAG:
				recipe_ref = s["recipe"]
				if recipe_ref in recipe_stack:
					raise ValueError(f"dag_job receta cíclica: '{recipe_ref}' ya está en la cadena {recipe_stack}.")
				_sub_source, sub_payload, _prio, _parent, _is_seed = cls._load_recipe(recipe_ref)
				sub_stages = copy.deepcopy((sub_payload.get("manifest") or {}).get("stages") or [])
				_apply_recipe_defaults(sub_stages, sub_payload)
				compound: Dict[str, Any] = {"id": s["id"], "type": _TYPE_COMPOUND, "sub_etapas": cls._expand_stages(sub_stages, recipe_stack + [recipe_ref])}
				for key in ("on_fail", "parallel", "depends_on"):
					if s.get(key) is not None:
						compound[key] = s[key]
				out.append(compound)
			elif s.get("type") == _TYPE_COMPOUND:
				node = dict(s)
				node["sub_etapas"] = cls._expand_stages(s.get("sub_etapas", []), recipe_stack)
				out.append(node)
			else:
				out.append(s)
		return out

	# ── Utilidades ─────────────────────────────────────────────────────────────
	def _stages(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
		stages = payload["manifest"].get("stages")
		return list(stages) if isinstance(stages, list) else []

	def _workdir(self, payload: Dict[str, Any]) -> Path:
		"""workdir del manifest, anclado a payload['cwd'] si es relativo.

		`load_recipe` ancla `cwd` a la raíz del proyecto de la receta; sin este
		anclaje, un `workdir: "."` dependía del CWD del proceso runner (frágil
		si el servicio cambia de WorkingDirectory)."""
		raw = Path(payload["manifest"]["workdir"])
		if raw.is_absolute():
			return raw
		base = payload.get("cwd")
		return (Path(base) / raw).resolve() if base else raw.resolve()

	def _ancestor_deps_met(self, stages: List[Dict[str, Any]], prefix: str, completed: List[str]) -> bool:
		"""Todas las deps de los ancestros compuestos de `prefix` satisfechas.

		Una hoja solo puede ejecutarse si TODOS sus ancestros compuestos tienen
		sus `depends_on` completados (el panel con `depends_on: [impl]` no puede
		ejecutar sus lentes antes de `impl`).
		"""
		if not prefix:
			return True
		parts = prefix.split("/")
		level_path = ""
		for i, part in enumerate(parts):
			level_path = f"{level_path}/{part}" if level_path else part
			# nivel en el que vive el ancestro = parte i+1 de la ruta
			parent_prefix = "/".join(parts[:i]) if i else ""
			ancestor = _find_node_by_path(stages, level_path)
			if ancestor is None:
				continue
			for dep in ancestor.get("depends_on", []):
				dep_path = f"{parent_prefix}/{dep}" if parent_prefix else dep
				if dep_path not in completed:
					return False
		return True

	def _status_file(self, payload: Dict[str, Any]) -> Path:
		return self._workdir(payload) / ".cell" / "dag_status.json"

	def _write_status(self, payload: Dict[str, Any], data: Dict[str, Any]) -> None:
		try:
			path = self._status_file(payload)
			path.parent.mkdir(parents=True, exist_ok=True)
			path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
		except OSError as e:
			logger.warning(f"[DagJob] telemetría no escrita: {e}")

	def preflight(self, payload: Dict[str, Any]) -> None:
		workdir = self._workdir(payload)
		if not workdir.is_dir():
			raise JobDeferred(f"workspace {workdir} no disponible")

	# ── GPU probe por etapa (fleco 1) ──────────────────────────────────────────
	def _preflight_stage_gpu(self, stage: Dict[str, Any], stage_path: str, payload: Dict[str, Any]) -> None:
		"""Probe de salud GPU real por etapa — espera (JobDeferred), nunca CPU disfrazada."""
		if not stage.get("requires_gpu"):
			return
		from red_pill.metabolism.ephemeral_server import _check_llm_available

		if _check_llm_available():
			usable, _free, ngl = _gpu_health_probe()
			if usable and (ngl == -1 or ngl > 0):
				return
		usable, free_mb, ngl = _gpu_health_probe()
		if not usable:
			raise JobDeferred(f"GPU no disponible para etapa '{stage_path}' (nvidia-smi no responde).")
		if ngl == 0:
			raise JobDeferred(f"LLM sirve en CPU disfrazada (-ngl 0) para etapa '{stage_path}': esperando GPU.")
		import red_pill.config as cfg

		min_free = int(payload.get("min_vram_mb", getattr(cfg, "SLEEP_MIN_FREE_VRAM_MB", 3500)))
		if free_mb < min_free:
			raise JobDeferred(f"VRAM insuficiente para etapa '{stage_path}' ({free_mb}MB libres < {min_free}MB).")

	# ── Cota de tiempo (política del RUNNER, aplicada aquí) ───────────────────
	def _budget_left(self) -> Optional[float]:
		"""Segundos que quedan de la cota del step, o None si no hay cota."""
		if not self.step_timeout_s or self._step_started is None:
			return None
		return self.step_timeout_s - (time.monotonic() - self._step_started)

	def _budget_spent(self) -> bool:
		"""True si la cota del step se agotó (frontera: ceder, no abatir)."""
		left = self._budget_left()
		return left is not None and left <= 0

	def _stage_timeout(self, stage: Dict[str, Any], payload: Dict[str, Any]) -> int:
		"""Timeout de la etapa ACOTADO por lo que queda del presupuesto del step.

		Sin esto, `control.max_step_minutes` es decorativo: cada etapa aplicaba su
		propio timeout y la suma de etapas secuenciales no tenía techo (una etapa
		colgada bloqueaba el runner entero, con el run-lock R6 impidiendo que
		otro entrara).

		El tope solo se aplica mientras quede presupuesto; una etapa ya lanzada
		en un grupo paralelo conserva su timeout declarado (recortarlo a cero la
		haría fallar por una cota que no es suya). El corte real está en la
		frontera de grupo, cediendo con lo hecho.
		"""
		declared = int(stage.get("timeout") or payload.get("timeout", 600))
		left = self._budget_left()
		if left is None or left <= 0:
			return declared
		return max(1, min(declared, int(left)))

	# ── Ejecución de una etapa ATOMICA ────────────────────────────────────────
	def _run_atomic(self, payload: Dict[str, Any], stage: Dict[str, Any], stage_path: str, gate: Any = None) -> str:
		"""Ejecuta UN minion (factory + execute directo — decisión 2026-08-07) y
		devuelve su resumen.

		Serialización (opción 3 del RFC): los minions de LÓGICA devuelven su dict
		en memoria y el DAG lo escribe en `.cell/reports/<ruta>.json` — ahí ese
		fichero ES el reporte. Las etapas AGÉNTICAS son distintas: el agente
		escribe él mismo su reporte conforme al schema de su rol en esa ruta (el
		contrato zero-trust de forge: validate-report.mjs / gate-check.mjs leen
		ese fichero), así que el envelope del minion va a `<ruta>.envelope.json`
		y NO pisa la evidencia del rol.

		`gate` es el `_GroupPauseGate` del grupo paralelo (None si secuencial).
		La sonda de pausa a mitad de fase SOLO se inyecta si la etapa es
		`pausable` (default true): una etapa no-pausable nunca se auto-pausa y su
		trabajo jamás se descarta.
		"""
		from red_pill.jobs.drivers.base import build_pause_probe
		from red_pill.swarm.factory import MinionFactory

		self._preflight_stage_gpu(stage, stage_path, payload)
		workdir = self._workdir(payload)

		minion = MinionFactory.create(str(stage.get("minion")))
		if minion is None:
			raise RuntimeError(f"dag stage '{stage_path}' minion no registrado.")

		task = stage.get("prompt") or stage.get("command") or ""
		kwargs: Dict[str, Any] = {"cwd": str(workdir), "timeout": self._stage_timeout(stage, payload)}
		for key in ("backend", "model", "effort"):
			if stage.get(key) or payload.get(key):
				kwargs[key] = stage.get(key) or payload.get(key)
		if stage.get("command"):
			kwargs["command"] = stage["command"]
		if isinstance(stage.get("params"), dict):
			kwargs.update(stage["params"])
		# Contexto del job para minions de lógica (sueño): la sonda de pausa a
		# mitad de fase (solo si la etapa es `pausable`) y el cutoff que ancla el
		# drenaje al momento en que ARRANCÓ el job (persistido en el checkpoint,
		# inmune a pause/resume).
		kwargs.setdefault(
			"pause_probe",
			build_pause_probe(self.job_id, gate=gate) if stage.get("pausable", True) else None,
		)
		kwargs.setdefault("sleep_cutoff_ts", getattr(self, "_sleep_cutoff_ts", 0.0))
		kwargs.setdefault("job_id", self.job_id)

		result = asyncio.run(minion.execute(task, **kwargs))

		reports_dir = workdir / ".cell" / "reports"
		suffix = ".envelope.json" if stage.get("type") == _TYPE_AGENT else ".json"
		report_path = reports_dir / f"{stage_path}{suffix}"
		report_path.parent.mkdir(parents=True, exist_ok=True)
		report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

		status = result.get("status")
		if status in ("failed", "error") or (result.get("returncode") not in (None, 0)):
			raise RuntimeError(f"dag stage '{stage_path}' failed: {result.get('error') or result.get('stderr') or ''}")
		summary = str(result.get("summary") or result.get("status") or result.get("response") or stage_path)
		return summary

	# ── step: ejecutar el siguiente frente del árbol ──────────────────────────
	def step(self, payload: Dict[str, Any], checkpoint_data: Dict[str, Any]) -> StepOutcome:
		self._step_started = time.monotonic()
		stages = self._stages(payload)
		completed = list(checkpoint_data.get("completed_stage_ids", []))
		results = dict(checkpoint_data.get("results", {}))
		flags = dict(checkpoint_data.get("stage_flags", {}))
		total_leaves = _count_leaves(stages)

		# Drain cutoff del ciclo de sueño: anclado en el PRIMER step del job y
		# persistido en el checkpoint — un pause/resume no desliza la ventana y
		# no traga engrams escritos mientras el ciclo estuvo detenido. Lo reciben
		# los minions de fase via _run_atomic (kwargs.sleep_cutoff_ts).
		self._sleep_cutoff_ts = float(checkpoint_data.get("sleep_cutoff_ts") or 0)
		if not checkpoint_data:
			self._sleep_cutoff_ts = float(time.time())
			logger.info(f"[DagJob] {self.short_id} drain cutoff pinned at {self._sleep_cutoff_ts:.0f} ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self._sleep_cutoff_ts))})")

		# Re-derivar compuestos completados desde sus hojas: un checkpoint de
		# handoff (job_checkpoint) puede listar solo hojas; sin esto, un
		# depends_on sobre el compuesto nunca se satisface y el runner llamaría
		# a step() para siempre con el mismo checkpoint (bucle estéril).
		for node_path in _flatten_ids(stages):
			if node_path in completed:
				continue
			node = _find_node_by_path(stages, node_path)
			if not node or node.get("type") != _TYPE_COMPOUND:
				continue
			node_leaves = list(_iter_leaves(node.get("sub_etapas", []), node_path))
			if node_leaves and all(lp in completed for lp, _ in node_leaves):
				completed.append(node_path)

		# Frente: hojas (etapas atómicas) no completadas con deps satisfechas.
		front: List[Tuple[str, Dict[str, Any], str]] = []  # (path, stage, prefix)

		for leaf_path, leaf in _iter_leaves(stages):
			if leaf_path in completed:
				continue
			prefix = leaf_path.rsplit("/", 1)[0] if "/" in leaf_path else ""
			if not self._ancestor_deps_met(stages, prefix, completed):
				continue
			deps_ok = all(((f"{prefix}/{d}" if prefix else d) in completed) for d in leaf.get("depends_on", []))
			if deps_ok:
				front.append((leaf_path, leaf, prefix))

		if not front:
			leaves_done = sum(1 for lp, _ in _iter_leaves(stages) if lp in completed)
			done = leaves_done >= total_leaves
			if not done:
				# Sin frente y sin terminar = deps insatisfacibles o checkpoint
				# corrupto. Devolver completed=False con el mismo checkpoint
				# metería al runner en un bucle caliente infinito — mejor fallar
				# con diagnóstico (el disyuntor del runner corta los reintentos).
				raise RuntimeError(
					f"dag sin frente ejecutable: {leaves_done}/{total_leaves} hojas completas "
					f"y ninguna dependencia satisfecha (deps imposibles o checkpoint corrupto)"
				)
			return StepOutcome(
				completed=True,
				new_checkpoint=checkpoint_data,
				summary="dag complete",
				progress={
					"current": leaves_done,
					"total": total_leaves,
					"percent": round(100 * leaves_done / total_leaves) if total_leaves else 0,
				},
				concurrency={
					"parallel_groups": 0,
					"parallel_stages": 0,
					"max_parallel_level": int(payload.get("max_parallel_level", _MAX_PARALLEL_LEVEL_DEFAULT)),
					"actually_parallel": False,
				},
			)

		def _exec_one(path: str, stage: Dict[str, Any], gate: Any = None) -> Tuple[str, str, bool]:
			"""Devuelve (path, summary, failed). El fallo se controla por on_fail."""
			try:
				return path, self._run_atomic(payload, stage, path, gate), False
			except JobPauseRequested:
				# Pausa del operador a mitad de fase (sonda del drenaje): NUNCA es
				# un fallo de etapa — propaga al runner, que sella PAUSED con el
				# checkpoint intacto y reanuda la etapa en el siguiente ciclo.
				raise
			except JobDeferred:
				# Espera de entorno (GPU ocupada, VRAM insuficiente), NO fallo de
				# etapa: se propaga al bucle del step, que cede con lo ya
				# completado o, sin progreso, la re-lanza al runner para
				# re-encolar sin quemar attempts (R1). Capturarla como fallo
				# convertía el deferral en etapa 'done' (warn) o en disyuntor (stop).
				raise
			except Exception as e:
				if _resolve_on_fail(stages, path) == "stop":
					return path, str(e), True
				logger.warning(f"[DagJob] {self.short_id} etapa {path} fallida (warn): {e}")
				return path, f"{path}: FAILED ({str(e)[:80]})", False

		# Agrupar el frente por compuesto padre (prefix) para el paralelismo.
		# Sub-etapas del MISMO nodo compuesto `parallel: true` (nivel ≤ cota) se
		# lanzan juntas; el resto secuencial. Grupos independientes también juntos.
		groups: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
		for leaf_path, leaf, prefix in front:
			groups.setdefault(prefix, []).append((leaf_path, leaf))

		max_conc = int(payload.get("max_concurrency", _MAX_CONCURRENCY_DEFAULT))
		max_parallel_level = int(payload.get("max_parallel_level", _MAX_PARALLEL_LEVEL_DEFAULT))
		all_tasks: List[Tuple[str, str, bool]] = []
		parallel_groups = 0
		parallel_stages = 0

		def _run_group(group: List[Tuple[str, Dict[str, Any]]]) -> Tuple[List[Tuple[str, str, bool]], bool, Optional[str]]:
			"""Corre un grupo paralelo con la puerta de pausa compartida.

			Devuelve (tareas_completadas, pausa_honrada, motivo_deferral). La
			sonda de cada etapa en vuelo registra la solicitud en el gate; la
			pausa se honra SOLO cuando todas las etapas aún en vuelo son
			pausables, reevaluando en cada frontera de completación. Un
			JobDeferred de UNA etapa no descarta a sus hermanas: se sigue
			recogiendo lo que complete y el deferral se decide en el cierre del
			step (ceder con lo hecho, o re-lanzar si no hubo progreso).
			"""
			gate = _GroupPauseGate(group)
			tasks: List[Tuple[str, str, bool]] = []
			paused = False
			deferred: Optional[str] = None
			with concurrent.futures.ThreadPoolExecutor(max_workers=max_conc) as pool:
				futures = {pool.submit(_exec_one, p, s, gate): p for p, s in group}
				for fut in concurrent.futures.as_completed(futures):
					path = futures[fut]
					try:
						tasks.append(fut.result())
					except JobPauseRequested:
						# La sonda la honró en vuelo (todas las restantes en vuelo
						# eran pausables): preservar lo ya completado.
						paused = True
						break
					except JobDeferred as e:
						deferred = str(e)
						gate.finished(path)
						continue
					gate.finished(path)
					if gate.pause_requested() and gate.can_pause():
						# Un no-pausable terminó y los restantes en vuelo son
						# pausables: la pausa diferida se honra aquí.
						paused = True
						break
			return tasks, paused, deferred

		# Cota del step en las fronteras: al agotarse NO se abate el step (eso
		# tiraría las etapas ya hechas y las re-ejecutaría con sus efectos), se
		# CEDE con lo completado. El runner persiste el checkpoint (R4) y vuelve
		# a entrar con presupuesto nuevo, pasando además por pausa/kill/prioridad.
		stopped_on_budget = False
		paused = False
		deferred_reason: Optional[str] = None
		try:
			for prefix, group in groups.items():
				if stopped_on_budget or paused or deferred_reason:
					break
				level = len(prefix.split("/")) if prefix else 0
				parent_parallel = False
				if prefix:
					node = _find_node_by_path(stages, prefix)
					parent_parallel = bool(node and node.get("type") == _TYPE_COMPOUND and node.get("parallel"))
				parallel = parent_parallel and level <= max_parallel_level and len(group) > 1
				if parallel:
					parallel_groups += 1
					parallel_stages += len(group)
					group_tasks, group_paused, group_deferred = _run_group(group)
					all_tasks.extend(group_tasks)
					if group_deferred:
						deferred_reason = group_deferred
					if group_paused:
						paused = True
						break
				else:
					for path, stage in group:
						if all_tasks and self._budget_spent():
							stopped_on_budget = True
							break
						try:
							all_tasks.append(_exec_one(path, stage))
						except JobDeferred as e:
							# No lanzar la siguiente etapa (el entorno no está);
							# lo ya completado se preserva cediendo en el cierre.
							deferred_reason = str(e)
							break
				if all_tasks and self._budget_spent():
					stopped_on_budget = True
		except JobPauseRequested:
			# Etapa secuencial pausable con sonda en vuelo: honrar la pausa
			# preservando las etapas secuenciales ya completadas de este step.
			paused = True

		if deferred_reason and not all_tasks:
			# Sin progreso en este step: deferral limpio al runner (R1, sin attempts).
			raise JobDeferred(deferred_reason)
		if deferred_reason:
			logger.info(
				f"[DagJob] {self.short_id} deferral a mitad de frente ({deferred_reason}): "
				f"cede con {len(all_tasks)} etapa(s) completada(s) en el checkpoint; el runner reentra."
			)

		if stopped_on_budget:
			logger.info(
				f"[DagJob] {self.short_id} cota del step agotada tras {len(all_tasks)} etapa(s): "
				f"cede en frontera con el checkpoint persistido (el runner reentra con presupuesto nuevo)."
			)

		new_results = dict(results)
		new_flags = dict(flags)
		new_completed = list(completed)
		for path, summary, failed in all_tasks:
			if failed:
				raise RuntimeError(f"dag stage '{path}' failed with on_fail=stop: {summary}")
			new_results[path] = summary
			new_flags[path] = "done"
			new_completed.append(path)

		# Propagar completitud de los compuestos: un nodo compuesto se marca done
		# cuando todas sus hojas descendientes lo están.
		for node_path in _flatten_ids(stages):
			if node_path in new_completed:
				continue
			node = _find_node_by_path(stages, node_path)
			if not node or node.get("type") != _TYPE_COMPOUND:
				continue
			if all(leaf_path in new_completed for leaf_path, _ in _iter_leaves(node.get("sub_etapas", []), node_path)):
				new_completed.append(node_path)

		# Orden estable y determinista (crítico para resume/control transferible).
		flat_order = _flatten_ids(stages)
		new_completed = [sid for sid in flat_order if sid in new_completed]

		# Progreso basado SOLO en hojas (los compuestos marcados done no cuentan):
		# si no, un árbol con compuestos inflaría el porcentaje.
		leaves_done = sum(1 for lp, _ in _iter_leaves(stages) if lp in new_completed)

		self._write_status(
			payload,
			{
				"mission_id": payload.get("mission_id"),
				"completed": leaves_done,
				"total": total_leaves,
				"status": "running" if leaves_done < total_leaves else "completed",
				"updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
			},
		)

		done = leaves_done >= total_leaves
		checkpoint = {
			"completed_stage_ids": new_completed,
			"results": new_results,
			"stage_flags": new_flags,
			"sleep_cutoff_ts": self._sleep_cutoff_ts,
		}
		if paused:
			logger.info(
				f"[DagJob] {self.short_id} pausa del operador honrada a mitad de step: "
				f"{leaves_done}/{total_leaves} hojas completas preservadas en el checkpoint."
			)
		return StepOutcome(
			completed=done and not paused,
			new_checkpoint=checkpoint,
			summary=f"dag {leaves_done}/{total_leaves}" + (" (pausado a mitad de step)" if paused else ""),
			progress={"current": leaves_done, "total": total_leaves, "percent": round(100 * leaves_done / total_leaves) if total_leaves else 0},
			concurrency={
				"parallel_groups": parallel_groups,
				"parallel_stages": parallel_stages,
				"max_parallel_level": max_parallel_level,
				"actually_parallel": parallel_groups > 0,
			},
			pause_requested=paused,
		)
