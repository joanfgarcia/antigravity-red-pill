import asyncio
import logging

from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.core.queue_worker import run_queue_worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_dag")


def run_test():
	logger.info("1. Initializing Cognitive Queue...")
	queue = CognitiveQueueManager()

	logger.info("2. Inyectando Tarea A (Padre): Echo monitor_pulse")
	task_a_id = queue.enqueue_task(source="echo_mirror", payload={"task": "monitor_pulse"})
	logger.info(f" -> Tarea A creada con ID: {task_a_id}")

	logger.info("3. Inyectando Tarea B (Hija): Echo generate_briefing (depende de A)")
	task_b_id = queue.enqueue_task(source="echo_mirror", payload={"task": "generate_briefing"}, parent_task_id=task_a_id)
	logger.info(f" -> Tarea B creada con ID: {task_b_id} (Debería estar BLOCKED)")

	logger.info("4. Ejecutando Queue Worker (Oneshot)...")
	logger.info("==========================================")
	# Ejecutamos el worker. En su primera pasada procesará la Tarea A.
	# Al completarla, la propia base de datos desbloqueará la Tarea B.
	# Como el worker hace un bucle sobre pop_next_task(), cogerá la B a continuación.
	run_queue_worker(poll_interval=1, oneshot=True)
	logger.info("==========================================")

	logger.info("5. Comprobando el estado final de las tareas en la BD...")
	conn = queue._get_conn()
	cursor = conn.cursor()

	cursor.execute("SELECT id, status FROM cognitive_tasks WHERE id IN (?, ?)", (task_a_id, task_b_id))
	results = cursor.fetchall()

	for row in results:
		logger.info(f"Tarea {row[0]} estado final: {row[1]}")

	conn.close()


if __name__ == "__main__":
	run_test()
