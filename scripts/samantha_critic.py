import argparse
import sys
import os

# Add src to pythonpath so imports work
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import asyncio
from red_pill.memory import MemoryManager
from red_pill.swarm.orchestrator import GruOrchestrator
from red_pill.swarm.agents.samantha import SamanthaMinion
from red_pill.utils.observer import notify_user
import logging

logger = logging.getLogger("samantha_critic")


async def run_analysis(event_id: str, input_file: str):
	try:
		with open(input_file, "r", encoding="utf-8") as f:
			text = f.read()

		results = await GruOrchestrator().deploy_swarm(text, [SamanthaMinion()])
		res = results[0]
		mgr = MemoryManager()

		if res.status == "success":
			analysis_text = f"SAMANTHA'S ANALYSIS:\n\n{res.result.get('analysis')}"
			mgr.add_memory(
				collection="work_memories",
				text=analysis_text,
				importance=1.0,
				point_id=event_id,
				metadata={"type": "samantha_analysis", "status": "completed"},
			)
			# Notify operator silently
			notify_user(title="Samantha Minion", message=f"Análisis completado. Puedes consultarlo en work_memories (ID: {event_id}).", sound=False)
		else:
			error_msg = f"Samantha Analysis Failed: {res.error}"
			mgr.add_memory(
				collection="work_memories",
				text=error_msg,
				point_id=event_id,
				metadata={"type": "samantha_analysis", "status": "failed"},
			)
			# Notify operator of failure
			notify_user(title="Samantha Minion", message=f"Error en análisis (ID: {event_id}). Revisa work_memories.", sound=True)
	except Exception as e:
		logger.error(f"Samantha detached task failed: {e}")
	finally:
		# Cleanup temp file
		if os.path.exists(input_file):
			try:
				os.remove(input_file)
			except:
				pass


if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("--event-id", required=True)
	parser.add_argument("--input-file", required=True)
	args = parser.parse_args()

	asyncio.run(run_analysis(args.event_id, args.input_file))
