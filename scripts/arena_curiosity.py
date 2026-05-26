#!/usr/bin/env python3
"""
Arena Curiosity Simulator
=========================
Simula 1000 Sovereign Pulses autónomos y genera estadísticas sobre qué opciones
se eligen (incluyendo el estado de sueño/inacción) según la evolución de la curiosidad.
"""

import json
import os
import random
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from red_pill.cognitive.drive_evaluator import DriveEvaluator
from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.core.paths import get_state_dir


def run_simulation(ticks: int = 1000, profile: str = "balanced"):
	# 1. Configurar aislamiento en el entorno de pruebas
	os.environ["CURIOSITY_ENGINE_ENABLED"] = "True"
	os.environ["CURIOSITY_PROFILE"] = profile

	# Clear config cache
	from red_pill.config import get_config

	get_config.cache_clear()

	# Directorio temporal de estado
	state_dir = get_state_dir()
	ratings_file = state_dir / "curiosity_ratings.json"
	state_file = state_dir / "drive_evaluator_state.json"

	# Limpiar estados previos de simulación
	if ratings_file.exists():
		ratings_file.unlink()
	if state_file.exists():
		state_file.unlink()

	# Base de datos de cola persistente para la simulación
	sim_db = state_dir / "sim_queue.db"
	if sim_db.exists():
		sim_db.unlink()
	qm = CognitiveQueueManager(db_path=str(sim_db))
	evaluator = DriveEvaluator(qm)

	# Historial para estadísticas
	stats = {
		"minion_maintenance": 0,
		"strategic_synthesis": 0,
		"proactive_coding": 0,
		"active_learning": 0,
		"graphify_sync": 0,
		"dynamic_spark": 0,
		"sleep (operator active)": 0,
		"sleep (below utility threshold)": 0,
		"sleep (cooldowns active)": 0,
	}

	# Forzar desconexión física de actividad del operador
	activity_file = Path.home() / ".gemini" / "antigravity" / "activity_tracker"
	if activity_file.exists():
		try:
			activity_file.unlink()
		except Exception:
			pass

	print(f"[*] Starting Curiosity Simulation ({ticks} pulses) using profile '{profile}'...")
	simulated_time = time.time()

	# Mock de _generate_dynamic_spark para evitar consultas http reales
	evaluator._generate_dynamic_spark = lambda: {
		"action": "autonomous_research",
		"objective": "Simulated cuda kernels research",
		"tools_allowed": ["search_memory_research"],
	}

	# Mock de verificación de cooldowns para controlarla mediante simulated_time
	def mock_is_cooldown_expired(task_key: str, cooldown_seconds: int) -> bool:
		if not state_file.exists():
			return True
		try:
			with open(state_file, "r") as f:
				state = json.load(f)
			last_run = float(state.get(task_key, 0))
			return bool((simulated_time - last_run) > cooldown_seconds)
		except Exception:
			return True

	evaluator._is_cooldown_expired = mock_is_cooldown_expired

	# Mock de timestamp update con tiempo simulado
	def mock_update_timestamp(task_key: str) -> None:
		state = {}
		if state_file.exists():
			try:
				with open(state_file, "r") as f:
					state = json.load(f)
			except Exception:
				pass
		state[task_key] = simulated_time
		with open(state_file, "w") as f:
			json.dump(state, f)

	evaluator._update_timestamp = mock_update_timestamp

	for tick in range(ticks):
		# Avanzar el tiempo simulado entre 10 y 60 minutos por tick
		simulated_time += random.randint(600, 3600)

		# 1. Simular probabilidad de presencia del operador (10%)
		operator_present = random.random() < 0.1
		if operator_present:
			stats["sleep (operator active)"] += 1
			continue

		# 2. Ejecutar evaluación del pulso
		injected = evaluator.evaluate_pulse()

		if injected == 0:
			# Determinar por qué durmió
			# Si todos los cooldowns están activos
			ratings = {}
			if ratings_file.exists():
				with open(ratings_file, "r") as f:
					ratings = json.load(f)

			profile_data = evaluator.profiles.get(profile, {})
			task_cooldowns = profile_data.get("cooldowns", {})
			profile_ratings = ratings.get(profile, {})

			active_candidates = []
			for category, cooldown in task_cooldowns.items():
				if evaluator._is_cooldown_expired(category, cooldown):
					cat_rating = profile_ratings.get(category, {"rating": 25.0, "uncertainty": 8.33})
					utility = cat_rating.get("rating", 25.0) + (cat_rating.get("uncertainty", 8.33) * 0.5)
					active_candidates.append(utility)

			if not active_candidates:
				stats["sleep (cooldowns active)"] += 1
			else:
				stats["sleep (below utility threshold)"] += 1
			continue

		# 3. Procesar la tarea inyectada en la cola de simulación
		task = qm.pop_next_task()
		if task:
			category = task["payload"].get("category", "dynamic_spark")

			# Simular éxito (rho): 75% éxito absoluto, 15% éxito parcial, 10% fallo
			rand = random.random()
			if rand < 0.75:
				qm.mark_completed(task["id"])
				stats[category] += 1
			elif rand < 0.90:
				# Éxito parcial (simulado como completado en queue pero con recompensa reducida en logs si fuese necesario)
				qm.mark_completed(task["id"])
				stats[category] += 1
			else:
				qm.mark_failed(task["id"], "Simulated timeout/failure")
				stats[category] += 1

	print("\n=== SIMULATION RESULTS ===")
	total_ticks = sum(stats.values())

	# Agrupar inacciones
	sleep_keys = [k for k in stats.keys() if "sleep" in k]
	total_sleeps = sum(stats[k] for k in sleep_keys)

	for key, val in stats.items():
		pct = (val / total_ticks) * 100
		print(f"- {key:<35} : {val:>4} times ({pct:>5.1f}%)")

	print("-" * 50)
	print(f"Total Sleeps (Inaction)             : {total_sleeps:>4} times ({(total_sleeps / total_ticks) * 100:>5.1f}%)")
	print(
		f"Total Active Decisions              : {total_ticks - total_sleeps:>4} times ({((total_ticks - total_sleeps) / total_ticks) * 100:>5.1f}%)"
	)

	# Mostrar calificaciones de curiosidad finales
	if ratings_file.exists():
		print("\n=== FINAL CURIOSITY RATINGS ===")
		with open(ratings_file, "r") as f:
			ratings = json.load(f)
		profile_ratings = ratings.get(profile, {})
		print(f"Profile: {profile}")
		for category, data in profile_ratings.items():
			print(f"- {category:<25} : rating={data['rating']:>6.2f} (uncertainty={data['uncertainty']:.2f})")

	# Clean up database file
	if sim_db.exists():
		try:
			sim_db.unlink()
		except Exception:
			pass


if __name__ == "__main__":
	ticks = 1000
	profile = "balanced"
	if len(sys.argv) > 1:
		try:
			ticks = int(sys.argv[1])
		except ValueError:
			pass
	if len(sys.argv) > 2:
		profile = sys.argv[2]
	run_simulation(ticks, profile)
