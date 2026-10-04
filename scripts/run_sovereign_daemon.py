import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from red_pill.core.agent_worker import IDEWorker

# NOTA (v7.10.0): el antiguo bloque SovereignDaemon v1 (swarm/daemon.py, escaneo de
# entropía sobre cognitive_queue.db del brain de Antigravity) fue retirado junto a su
# módulo — su sucesor vivo es DriveEvaluator sobre la cola central, que ya se invoca
# desde IDEWorker.run_once() cuando la cola cognitiva está vacía.

if __name__ == "__main__":
	import logging

	logging.basicConfig(level=logging.INFO)

	print("[Daemon] Processing IDE Worker Telemetry/Telegram routing...")
	worker = IDEWorker()
	worker.run_once()
	# Drain-wait del carril Samantha: el pulse es oneshot — sin esta espera el
	# hilo daemon muere con el proceso a mitad de compactación (PROCESSING huérfano).
	worker.wait_for_samantha()
