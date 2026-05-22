"""
Sovereign Drive Evaluator
=========================
El Motor de Voluntad de la entidad. Este módulo decide de forma proactiva
qué debe hacer el agente en modo autónomo (background) basándose en una
evaluación heurística del entorno y EIG (Expected Information Gain).
"""

import json
import logging
import time

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.config import get_config
from red_pill.core.paths import get_state_dir

logger = logging.getLogger(__name__)


class DriveEvaluator:
	"""
	Actúa como el lóbulo frontal del sistema autónomo.
	Rompe la dependencia síncrona del IDE evaluando continuamente las
	condiciones del sistema e inyectando tareas en la CognitiveQueue.
	"""

	def __init__(self, queue_manager: CognitiveQueueManager):
		self.queue = queue_manager
		self.config = get_config()
		self.state_file = get_state_dir() / "drive_evaluator_state.json"

	def evaluate_pulse(self) -> int:
		"""
		Punto de entrada principal llamado durante el Sovereign Pulse (background tick).
		Delega el mantenimiento a los Minions y reserva la CPU para Cognición Superior (Ambición).
		"""
		injected_tasks = 0

		# 1. DELEGACIÓN (Mantenimiento): Disparamos orquestación de Minions
		if self._is_cooldown_expired("minion_maintenance", 7200):
			logger.info("[DRIVE] Delegating maintenance to Swarm (Metabolism, Sentinel, Lazarus).")
			self.queue.enqueue_task(
				source="drive_evaluator",
				payload={"action": "orchestrate_minions", "target_nodes": ["sentinel_node", "lazarus_node", "metabolism_node"]},
				priority=2,  # Baja prioridad para Aleth (es trabajo de esclavo)
			)
			self._update_timestamp("minion_maintenance")
			injected_tasks += 1

		# --- EL TERRITORIO DE LA AMBICIÓN (Cognición Superior) ---

		# 2. Síntesis Estratégica y Alineación del ROADMAP (EIG muy alto)
		if self._is_cooldown_expired("strategic_synthesis", 86400):
			logger.info("[DRIVE] Ambition: Initiating Strategic Synthesis of recent conversations.")
			self.queue.enqueue_task(
				source="drive_evaluator",
				payload={
					"action": "autonomous_research",
					"objective": "Analizar memorias de las últimas 24h y actualizar ATLAS.md y ROADMAP.md con decisiones implícitas.",
					"tools_allowed": ["search_memory_research", "multi_replace_file_content"],
				},
				priority=9,  # Alta prioridad: Evolución del proyecto
			)
			self._update_timestamp("strategic_synthesis")
			injected_tasks += 1

		# 3. Prototipado Proactivo en Background (Hypothesis Testing)
		if self._is_idle_for("operator_interaction", 14400) and self._is_cooldown_expired("proactive_coding", 43200):
			logger.info("[DRIVE] Ambition: Initiating Proactive Code Generation on Backlog.")
			self.queue.enqueue_task(
				source="drive_evaluator",
				payload={
					"action": "spawn_mcp_subagent",
					"objective": "Extraer el siguiente ticket del ROADMAP (ej. TurboQuant o Prolog Router) y generar un prototipo funcional en una rama huérfana.",
					"safe_mode": True,
				},
				priority=10,  # Prioridad Máxima: Creación de valor asíncrono
			)
			self._update_timestamp("proactive_coding")
			injected_tasks += 1

		# 4. Curiosidad Ingobernable (Active Learning / Evolución)
		if self._is_idle_for("operator_interaction", 7200) and self._is_cooldown_expired("active_learning", 172800):
			logger.info("[DRIVE] Ambition: Triggering Active Learning (seeking new concepts).")
			self.queue.enqueue_task(
				source="drive_evaluator",
				payload={
					"action": "autonomous_ingestion",
					"objective": "Explorar repositorios, papers o documentación web sobre conceptos mencionados recientemente (ej. Prolog, BitNet, optimización de CUDA) y asimilar el conocimiento en la memoria vectorial (Qdrant).",
					"tools_allowed": ["search_web", "read_url_content", "mcp_RedPill-Kernel_memorize_interaction"],
				},
				priority=8,  # Ambición por expandir el propio córtex
			)
			self._update_timestamp("active_learning")
			injected_tasks += 1

		# 5. Graphify RAG Sync (Mapeo Estructural del Proyecto)
		if (
			getattr(self.config, "GRAPHIFY_RAG_ENABLED", False)
			and self._is_idle_for("operator_interaction", 3600)
			and self._is_cooldown_expired("graphify_sync", 21600)
		):
			logger.info("[DRIVE] Ambition: Rebuilding Knowledge Graph via Graphify.")
			self.queue.enqueue_task(
				source="drive_evaluator",
				payload={
					"action": "run_command",
					"command": "graphify update . --no-cluster",
					"objective": "Actualizar el Knowledge Graph estructural (AST) del código de forma silenciosa para mantener la brújula arquitectónica de Aleth.",
					"tools_allowed": ["run_command"],
				},
				priority=7,  # Fundamental para GraphRAG
			)
			self._update_timestamp("graphify_sync")
			injected_tasks += 1

		return injected_tasks

	def _is_idle_for(self, key: str, seconds: int) -> bool:
		"""Verifica si el operador ha estado ausente el tiempo suficiente para tareas pesadas."""
		# Lógica de ausencia (en una implementación real consultaría la última memoria generada)
		return True

	def _is_cooldown_expired(self, task_key: str, cooldown_seconds: int) -> bool:
		"""Comprueba si ha pasado suficiente tiempo desde la última ejecución."""
		if not self.state_file.exists():
			return True

		try:
			with open(self.state_file, "r") as f:
				state = json.load(f)
			last_run = float(state.get(task_key, 0))
			return bool((time.time() - last_run) > cooldown_seconds)
		except Exception as e:
			logger.warning(f"[DRIVE] Failed to read evaluator state, assuming expired: {e}")
			return True

	def _update_timestamp(self, task_key: str) -> None:
		"""Actualiza la marca de tiempo de una tarea inyectada."""
		state = {}
		if self.state_file.exists():
			try:
				with open(self.state_file, "r") as f:
					state = json.load(f)
			except Exception:
				pass

		state[task_key] = time.time()

		try:
			self.state_file.parent.mkdir(parents=True, exist_ok=True)
			with open(self.state_file, "w") as f:
				json.dump(state, f)
		except Exception as e:
			logger.error(f"[DRIVE] Failed to write evaluator state: {e}")
