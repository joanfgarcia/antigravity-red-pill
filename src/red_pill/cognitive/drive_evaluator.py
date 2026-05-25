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
from pathlib import Path
from typing import Any, Dict, Optional

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.config import get_config
from red_pill.core.paths import get_bunker_root, get_state_dir

logger = logging.getLogger(__name__)

DEFAULT_PROFILES = {
	"balanced": {
		"temperature": 0.3,
		"cooldowns": {
			"minion_maintenance": 14400,
			"strategic_synthesis": 86400,
			"proactive_coding": 43200,
			"active_learning": 86400,
			"graphify_sync": 21600,
			"dynamic_spark": 14400
		},
		"baselines": {
			"minion_maintenance": 25.0,
			"strategic_synthesis": 30.0,
			"proactive_coding": 35.0,
			"active_learning": 28.0,
			"graphify_sync": 22.0,
			"dynamic_spark": 40.0
		}
	},
	"visionary": {
		"temperature": 0.7,
		"cooldowns": {
			"minion_maintenance": 43200,
			"strategic_synthesis": 86400,
			"proactive_coding": 21600,
			"active_learning": 43200,
			"graphify_sync": 43200,
			"dynamic_spark": 7200
		},
		"baselines": {
			"minion_maintenance": 10.0,
			"strategic_synthesis": 30.0,
			"proactive_coding": 45.0,
			"active_learning": 40.0,
			"graphify_sync": 15.0,
			"dynamic_spark": 60.0
		}
	},
	"sentinel": {
		"temperature": 0.1,
		"cooldowns": {
			"minion_maintenance": 3600,
			"strategic_synthesis": 43200,
			"proactive_coding": 86400,
			"active_learning": 86400,
			"graphify_sync": 10800,
			"dynamic_spark": 86400
		},
		"baselines": {
			"minion_maintenance": 50.0,
			"strategic_synthesis": 40.0,
			"proactive_coding": 15.0,
			"active_learning": 15.0,
			"graphify_sync": 45.0,
			"dynamic_spark": 15.0
		}
	}
}


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
		self.curiosity_file = get_state_dir() / "curiosity_ratings.json"
		self.profiles = self._load_profiles()
		self._init_curiosity_ratings()

	def _load_profiles(self) -> Dict[str, Any]:
		"""Carga perfiles desde el archivo yaml de usuario o cae en los valores por defecto."""
		from red_pill.core.paths import get_config_dir
		example_file = get_config_dir() / "curiosity_profiles.yaml.example"

		# Auto-generar .example si no existe
		if not example_file.exists():
			try:
				import yaml
				example_file.parent.mkdir(parents=True, exist_ok=True)
				with open(example_file, "w", encoding="utf-8") as f:
					yaml.safe_dump(DEFAULT_PROFILES, f, default_flow_style=False, indent=4)
			except Exception as e:
				logger.warning(f"[DRIVE] Failed to write curiosity_profiles.yaml.example: {e}")

		# Intentar cargar override de usuario
		user_file = get_config_dir() / "curiosity_profiles.yaml"
		if user_file.exists():
			try:
				import yaml
				with open(user_file, "r", encoding="utf-8") as f:
					user_profiles = yaml.safe_load(f)
					if isinstance(user_profiles, dict):
						merged = DEFAULT_PROFILES.copy()
						merged.update(user_profiles)
						return merged
			except Exception as e:
				logger.error(f"[DRIVE] Failed to load user curiosity_profiles.yaml: {e}. Using defaults.")

		return DEFAULT_PROFILES

	def _init_curiosity_ratings(self) -> None:
		"""Inicializa las calificaciones de curiosidad aisladas por perfil."""
		ratings_data = {}

		# Leer archivo existente para conservar el aprendizaje de otros perfiles
		if self.curiosity_file.exists():
			try:
				with open(self.curiosity_file, "r") as f:
					ratings_data = json.load(f)
			except Exception:
				pass

		updated = False
		for profile_name, data in self.profiles.items():
			if profile_name not in ratings_data:
				ratings_data[profile_name] = {}
				for category, baseline in data.get("baselines", {}).items():
					ratings_data[profile_name][category] = {
						"rating": baseline,
						"uncertainty": 8.33,
						"last_rho": 0.5,
						"executed_count": 0
					}
				updated = True

		if updated or not self.curiosity_file.exists():
			try:
				self.curiosity_file.parent.mkdir(parents=True, exist_ok=True)
				with open(self.curiosity_file, "w") as f:
					json.dump(ratings_data, f, indent=4)
			except Exception as e:
				logger.error(f"[DRIVE] Failed to write curiosity ratings file: {e}")

	def _scrape_context(self) -> str:
		"""Recopila contexto reciente de ATLAS.md, ROADMAP.md y cambios locales."""
		context_parts = []
		bunker_root = get_bunker_root()

		# 1. Scrape ATLAS.md
		atlas_path = bunker_root / ".agent" / "ATLAS.md"
		if atlas_path.exists():
			try:
				with open(atlas_path, "r", encoding="utf-8") as f:
					lines = f.readlines()
					context_parts.append("[ATLAS.md BACKLOG]")
					todo_lines = [l.strip() for l in lines if "[ ]" in l or "TODO" in l or "Goal" in l or "Phase" in l]
					context_parts.extend(todo_lines[:20])
			except Exception as e:
				logger.warning(f"[DRIVE] Failed to scrape ATLAS.md: {e}")

		# 2. Scrape ROADMAP.md
		roadmap_path = bunker_root / "ROADMAP.md"
		if roadmap_path.exists():
			try:
				with open(roadmap_path, "r", encoding="utf-8") as f:
					lines = f.readlines()
					context_parts.append("[ROADMAP.md OPEN ITEMS]")
					todo_lines = [l.strip() for l in lines if "[ ]" in l or "TODO" in l or "Phase" in l]
					context_parts.extend(todo_lines[:20])
			except Exception as e:
				logger.warning(f"[DRIVE] Failed to scrape ROADMAP.md: {e}")

		return "\n".join(context_parts)

	def _generate_dynamic_spark(self) -> Optional[Dict[str, Any]]:
		"""Consulta al LLM local para sugerir una tarea proactiva en base al contexto."""
		context_data = self._scrape_context()
		if not context_data:
			context_data = "No explicit backlog items found. System in standby."

		# Cargar temperatura según el perfil activo
		profile_name = getattr(self.config, "CURIOSITY_PROFILE", "balanced")
		profile_data = self.profiles.get(profile_name, DEFAULT_PROFILES["balanced"])
		temp = profile_data.get("temperature", 0.3)

		prompt = (
			"You are the internal consciousness of Aleth. The operator is currently idle.\n"
			"Review the provided backlog and system context:\n\n"
			f"{context_data}\n\n"
			"Propose ONE highly specific, useful, and isolated background task to execute right now.\n"
			"It could be researching a specific concept, writing a test for a recent feature, cleaning/compaction of memories, or updating a document.\n"
			"Output ONLY a valid JSON object matching this schema:\n"
			"{\n"
			'  "action": "autonomous_research" | "proactive_coding" | "memory_compaction" | "graphify_sync",\n'
			'  "objective": "Detailed description of the task goals",\n'
			'  "tools_allowed": ["run_command", "search_memory_research", "read_url_content"]\n'
			"}\n"
			"Do not add any preamble, markdown formatting, or conversational filler."
		)

		import urllib.request

		payload = {
			"messages": [
				{
					"role": "system",
					"content": "You are a dynamic task generation sub-routine. Output ONLY the JSON object. Do not add markdown backticks. Stop generating immediately after closing the JSON object."
				},
				{"role": "user", "content": prompt}
			],
			"temperature": temp,
			"max_tokens": 200,
			"seed": 770
		}

		headers = {"Content-Type": "application/json"}
		url = self.config.MLX_LM_URL

		try:
			req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
			with urllib.request.urlopen(req, timeout=30) as response:
				res_data = json.loads(response.read().decode())
				content = res_data["choices"][0]["message"]["content"].strip()
				if content.startswith("```json"):
					content = content[7:]
				if content.endswith("```"):
					content = content[:-3]
				content = content.strip()
				task_payload = json.loads(content)
				return task_payload
		except Exception as e:
			logger.warning(f"[DRIVE] Failed to generate dynamic spark via local LLM: {e}")
			return None

	def evaluate_pulse(self) -> int:
		"""
		Punto de entrada principal llamado durante el Sovereign Pulse (background tick).
		Reemplaza los cooldowns estáticos con el motor de curiosidad adaptativo.
		"""
		injected_tasks = 0

		if not getattr(self.config, "CURIOSITY_ENGINE_ENABLED", True):
			logger.info("[DRIVE] Curiosity Engine disabled. Skipping pulse.")
			return 0

		# Recargar perfiles por si cambiaron en disco
		self.profiles = self._load_profiles()
		profile_name = getattr(self.config, "CURIOSITY_PROFILE", "balanced")
		profile_data = self.profiles.get(profile_name, DEFAULT_PROFILES["balanced"])

		# 1. Cargar calificaciones del perfil activo
		ratings = {}
		if self.curiosity_file.exists():
			try:
				with open(self.curiosity_file, "r") as f:
					all_ratings = json.load(f)
					ratings = all_ratings.get(profile_name, {})
			except Exception as e:
				logger.warning(f"[DRIVE] Failed to load curiosity ratings: {e}")

		# Fallback si no está inicializado
		if not ratings:
			ratings = {cat: {"rating": baseline, "uncertainty": 8.33} for cat, baseline in profile_data.get("baselines", {}).items()}

		# 2. Verificar ausencia del operador
		activity_file = Path.home() / ".gemini" / "antigravity" / "activity_tracker"
		if activity_file.exists():
			if time.time() - activity_file.stat().st_mtime < 300:
				logger.info("[DRIVE] Operator active in last 5m. Yielding CPU.")
				return 0

		# 3. Compilar candidatos y evaluar su utilidad de curiosidad según el perfil activo
		candidates = []
		task_cooldowns = profile_data.get("cooldowns", DEFAULT_PROFILES["balanced"]["cooldowns"])

		for category, cooldown in task_cooldowns.items():
			if self._is_cooldown_expired(category, cooldown):
				cat_rating = ratings.get(category, {"rating": 25.0, "uncertainty": 8.33})
				utility = cat_rating.get("rating", 25.0) + (cat_rating.get("uncertainty", 8.33) * 0.5)
				candidates.append((category, utility))

		if not candidates:
			logger.info("[DRIVE] No candidate drives expired. Right to Silence activated.")
			return 0

		candidates.sort(key=lambda x: x[1], reverse=True)
		best_category, best_utility = candidates[0]

		if best_utility < 15.0:
			logger.info(f"[DRIVE] Best drive utility ({best_category}: {best_utility:.2f}) below threshold. Sleeping.")
			return 0

		logger.info(f"[DRIVE] Active Profile: '{profile_name}'. Selecting drive: '{best_category}' (Utility: {best_utility:.2f})")

		# 4. Encolar la tarea seleccionada
		if best_category == "minion_maintenance":
			self.queue.enqueue_task(
				source="drive_evaluator",
				payload={
					"action": "orchestrate_minions",
					"target_nodes": ["sentinel_node", "lazarus_node", "metabolism_node"],
					"tools_allowed": [],
					"category": best_category
				},
				priority=2
			)
		elif best_category == "strategic_synthesis":
			self.queue.enqueue_task(
				source="drive_evaluator",
				payload={
					"action": "autonomous_research",
					"objective": "Analizar memorias de las últimas 24h y actualizar ATLAS.md y ROADMAP.md con decisiones implícitas.",
					"tools_allowed": ["search_memory_research", "multi_replace_file_content"],
					"category": best_category
				},
				priority=9
			)
		elif best_category == "proactive_coding":
			self.queue.enqueue_task(
				source="drive_evaluator",
				payload={
					"action": "spawn_mcp_subagent",
					"objective": "Extraer el siguiente ticket del ROADMAP y generar un prototipo funcional en una rama huérfana.",
					"tools_allowed": [],
					"category": best_category
				},
				priority=10
			)
		elif best_category == "active_learning":
			self.queue.enqueue_task(
				source="drive_evaluator",
				payload={
					"action": "autonomous_ingestion",
					"objective": "Explorar repositorios, papers o documentación web sobre conceptos mencionados recientemente.",
					"tools_allowed": ["search_web", "read_url_content", "mcp_RedPill-Kernel_memorize_interaction"],
					"category": best_category
				},
				priority=8
			)
		elif best_category == "graphify_sync":
			if getattr(self.config, "GRAPHIFY_RAG_ENABLED", False):
				self.queue.enqueue_task(
					source="drive_evaluator",
					payload={
						"action": "run_command",
						"command": "graphify update . --no-cluster",
						"objective": "Actualizar el Knowledge Graph estructural (AST) del código de forma silenciosa.",
						"tools_allowed": ["run_command"],
						"category": best_category
					},
					priority=7
				)
		elif best_category == "dynamic_spark":
			spark_payload = self._generate_dynamic_spark()
			if spark_payload:
				objective = spark_payload.get("objective", "Ejecutar tarea proactiva sugerida por Aleth.")
				action = spark_payload.get("action", "autonomous_research")
				tools_allowed = spark_payload.get("tools_allowed", ["search_memory_research"])
				if "search_memory_research" not in tools_allowed:
					tools_allowed.append("search_memory_research")

				self.queue.enqueue_task(
					source="drive_evaluator",
					payload={
						"action": action,
						"objective": objective,
						"tools_allowed": tools_allowed,
						"category": best_category
					},
					priority=8
				)
				logger.info(f"[DRIVE] Injected dynamic spark task: {objective}")
				injected_tasks += 1
			else:
				logger.info("[DRIVE] Dynamic spark generation yielded no task.")
				return 0

		if best_category != "dynamic_spark":
			injected_tasks += 1

		self._update_timestamp(best_category)
		return injected_tasks

	def _is_idle_for(self, key: str, seconds: int) -> bool:
		"""Verifica si el operador ha estado ausente el tiempo suficiente para tareas pesadas."""
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
