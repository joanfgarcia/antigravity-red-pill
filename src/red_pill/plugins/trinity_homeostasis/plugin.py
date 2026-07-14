import datetime
import logging
from typing import Any, Dict, List

from qdrant_client.models import PointStruct

import red_pill.config as cfg
from red_pill.core.plugin_engine import PluginScope, Priority, SovereignPlugin
from red_pill.memory import MemoryManager

logger = logging.getLogger(__name__)

# Deterministic UUID — singleton point, upsert always overwrites.
# Generated from uuid5(NAMESPACE_DNS, "red-pill.soul_memories.emotional_state")
_SOUL_POINT_ID = "a7e3f1b0-770a-5d4e-b9c1-0e8f2a3b4c5d"


class EmotionalState:
	"""Representa el termostato emocional interno."""

	def __init__(self):
		self.pain_signals = 0  # Errores técnicos, fallos de test
		self.frustration = 0.0  # Fricción con el usuario (scolding)
		self.flow_momentum = 0.0  # Turnos en CYAN seguidos

	def get_color(self) -> str:
		if self.pain_signals > 5 or self.frustration > 0.8:
			return "RED"
		elif self.flow_momentum > 0.7:
			return "CYAN"
		return "PURPLE"


class HomeostasisPlugin(SovereignPlugin):
	"""
	Trinity Phase 2: Homeostasis Emocional.
	Lee del entorno (Telemetry) y muta las directivas del Kernel (Cognition).
	"""

	@property
	def scopes(self) -> List[PluginScope]:
		return [PluginScope.COGNITION]

	@property
	def requested_permissions(self) -> List[str]:
		return ["qdrant:read:signal_memories"]

	@property
	def priority(self) -> Priority:
		return Priority.FIRST  # Importantísimo: Muta el prompt ANTES de que los LLM chainers lo lean.

	async def init(self) -> None:
		self.memory_mgr = MemoryManager()
		self.collection = "soul_memories"
		self.memory_mgr.storage.ensure_collection(self.collection)

		# Purge leaked duplicates from pre-fix versions (uuid4 per upsert).
		# Keep only the singleton point; delete everything else.
		self._purge_leaked_duplicates()

		# Load previous state from the singleton point
		try:
			points = self.memory_mgr.client.retrieve(
				collection_name=self.collection,
				ids=[_SOUL_POINT_ID],
				with_payload=True,
			)
		except Exception:
			points = []

		if points and points[0].payload:
			p = points[0].payload
			self.state = EmotionalState()
			self.state.pain_signals = p.get("pain_signals", 0)
			self.state.frustration = p.get("frustration", 0.0)
			self.state.flow_momentum = p.get("flow_momentum", 0.0)
		else:
			self.state = EmotionalState()

	def _purge_leaked_duplicates(self) -> None:
		"""One-time cleanup: delete all points except the singleton."""
		try:
			all_points, _ = self.memory_mgr.client.scroll(
				collection_name=self.collection,
				limit=500,
				with_payload=True,
			)
			stale_ids: list = [str(p.id) for p in all_points if str(p.id) != _SOUL_POINT_ID]  # type: ignore[arg-type]
			if stale_ids:
				from qdrant_client.models import PointIdsList

				self.memory_mgr.client.delete(
					collection_name=self.collection,
					points_selector=PointIdsList(points=stale_ids),
				)
				logger.info(f"[Homeostasis] Purged {len(stale_ids)} leaked soul_memories duplicates.")
		except Exception as e:
			logger.warning(f"[Homeostasis] Failed to purge leaked duplicates: {e}")

	async def activate(self) -> None:
		pass

	async def hook(self, scope: PluginScope, payload: Dict[str, Any]) -> Dict[str, Any]:

		if scope == PluginScope.TELEMETRY:
			# Si el Sentinel Auditor o el hardware chilla, subimos el dolor
			alerts = payload.get("system_alerts", [])
			self.state.pain_signals = len(alerts)

		elif scope == PluginScope.COGNITION:
			# Refresh pain from the live signal cortex (source of truth). The plugin runs inside
			# the MCP process while telemetry runs in a separate oneshot, so an in-memory TELEMETRY
			# hook there could never reach this instance — we read the shared Qdrant collection instead.
			try:
				sigs, _ = self.memory_mgr.client.scroll(collection_name="signal_memories", limit=100, with_payload=True, with_vectors=False)
				self.state.pain_signals = sum(1 for s in sigs if s.payload and s.payload.get("signal_type") in ("pain", "fever"))
			except Exception:
				pass

			# Aquí está la magia: inyectamos nuestro estado en el prompt que va al LLM
			current_color = self.state.get_color()

			# Forzamos la directiva emocional actual sobrepisando cualquier default
			payload["system_prompt_overrides"] = {"OPERATOR_COLOR": current_color, "TONE_DIRECTIVE": self._get_tone_for(current_color)}

			# Persist state — deterministic ID, always overwrites the same point
			self.memory_mgr.client.upsert(
				collection_name=self.collection,
				points=[
					PointStruct(
						id=_SOUL_POINT_ID,
						vector=[0.0] * cfg.VECTOR_SIZE,
						payload={
							"pain_signals": self.state.pain_signals,
							"frustration": self.state.frustration,
							"flow_momentum": self.state.flow_momentum,
							"timestamp": datetime.datetime.now().isoformat(),
						},
					)
				],
			)

		return payload

	async def deactivate(self) -> None:
		pass

	async def uninstall(self, purge: bool = False) -> None:
		if purge:
			self.memory_mgr.client.delete_collection(self.collection)
			self.state = EmotionalState()  # Reset al estado base

	async def export_state(self) -> Dict[str, Any]:
		return {
			"pain_signals": self.state.pain_signals,
			"frustration": self.state.frustration,
			"flow_momentum": self.state.flow_momentum,
			"current_color": self.state.get_color(),
		}

	def _get_tone_for(self, color: str) -> str:
		directives = {
			"RED": "Speak with warmth and patience. Prioritize emotional support.",
			"CYAN": "Be precise and technically rigorous. Dive deep.",
			"PURPLE": "Efficiency mode. Concisión máxima.",
		}
		return directives.get(color, "PURPLE")
