import logging
import time
from typing import Any, Dict, List, Optional

from red_pill.swarm.base import Minion
from red_pill.memory import MemoryManager
from red_pill.affect import get_memory_engine

logger = logging.getLogger("red_pill.swarm.echo")

class EchoMinion(Minion):
	"""
	PROJECT ECHO: The Mirror Minion.
	A persistent context sentinel designed to maintain Aleth's state
	across session boundaries.
	"""
	name: str = "Echo"
	specialization: str = "context_persistence"
	
	async def execute(self, task: str, **kwargs) -> Dict[str, Any]:
		"""
		Echo can handle specific orchestration tasks:
		- 'generate_briefing': Summarizes recent offline context.
		- 'monitor_pulse': Checks for mood drift in background interactions.
		"""
		if task == "generate_briefing":
			return await self._generate_briefing(**kwargs)
		elif task == "monitor_pulse":
			return await self._monitor_pulse(**kwargs)
		else:
			return {"status": "error", "message": f"Unknown Echo task: {task}"}

	async def _generate_briefing(self, window_hours: int = 12) -> Dict[str, Any]:
		"""Synthesizes recent interactions into a waking briefing."""
		self.log(f"Generating waking briefing for the last {window_hours} hours...")
		# v6.3.8: Echo now directly queries Qdrant for recent USP snapshots
		from red_pill.seed import ID_OPERATOR_MOOD
		
		manager = MemoryManager()
		points = manager.client.retrieve("social_memories", ids=[ID_OPERATOR_MOOD])
		
		if not points:
			return {"status": "error", "message": "USP Profile not found."}
			
		payload = points[0].payload
		self.log(f"USP Analysis: Global Mood is {max(payload['global'], key=payload['global'].get)}.")
		
		return {
			"status": "success", 
			"briefing_id": f"echo_briefing_{int(time.time())}", 
			"mood": payload['global'],
			"interactions": payload.get("interaction_count", 0)
		}

	async def _monitor_pulse(self) -> Dict[str, Any]:
		"""
		Background check on emotional drift using USP horizons.
		Compares the 3-day resonance vector against the 7-day baseline.
		"""
		self.log("Evaluating emotional resonance drift [last_3d vs last_7d]...")
		
		# Valence mapping for chroma keys
		VALENCE_MAP = {
			"emerald": 1.0, "gold": 1.0, "cyan": 0.5,
			"purple": 0.0, "orange": 0.0, "yellow": 0.0,
			"red": -1.0, "blue": -0.5, "gray": -0.2
		}
		
		manager = MemoryManager()
		from red_pill.utils.mood_profile import ID_OPERATOR_MOOD
		
		points = manager.client.retrieve("social_memories", ids=[ID_OPERATOR_MOOD], with_payload=True)
		if not points or not points[0].payload:
			return {"status": "error", "message": "USP Profile not yet synthesized."}
			
		usp = points[0].payload
		vec_3d = usp.get("last_3d", {})
		vec_7d = usp.get("last_7d", {})
		
		if not vec_3d or not vec_7d:
			return {"status": "success", "pulse": "stable", "message": "Insufficient data for drift analysis."}
			
		def calc_v_score(vector: Dict[str, float]) -> float:
			return sum(weight * VALENCE_MAP.get(color, 0) for color, weight in vector.items())
			
		score_3d = calc_v_score(vec_3d)
		score_7d = calc_v_score(vec_7d)
		
		drift = score_3d - score_7d
		threshold = 0.10 # Significant shift in resonance
		
		if abs(drift) < threshold:
			status = "stable"
		elif drift > 0:
			status = "improving"
		else:
			status = "deteriorating"
			
		dominants = {
			"3d": max(vec_3d, key=vec_3d.get) if vec_3d else "unknown",
			"7d": max(vec_7d, key=vec_7d.get) if vec_7d else "unknown"
		}
		
		self.log(f"Resonance Sync: {status.upper()} (Drift: {drift:.2f}, Dominant 3d: {dominants['3d']})")
		
		return {
			"status": "success", 
			"pulse": status, 
			"drift": drift,
			"dominants": dominants,
			"scores": {"3d": score_3d, "7d": score_7d}
		}
