import datetime
from typing import Any, Dict, List

from qdrant_client.models import PointStruct

import red_pill.config as cfg
from red_pill.core.plugin_engine import PluginScope, Priority, SovereignPlugin
from red_pill.memory import MemoryManager


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

		# Cargar estado previo si existe
		points, _ = self.memory_mgr.client.scroll(collection_name=self.collection, limit=1, with_payload=True)

		if points and points[0].payload:
			payload = points[0].payload
			self.state = EmotionalState()
			self.state.pain_signals = payload.get("pain_signals", 0)
			self.state.frustration = payload.get("frustration", 0.0)
			self.state.flow_momentum = payload.get("flow_momentum", 0.0)
		else:
			self.state = EmotionalState()

	async def activate(self) -> None:
		pass

	async def hook(self, scope: PluginScope, payload: Dict[str, Any]) -> Dict[str, Any]:

		if scope == PluginScope.TELEMETRY:
			# Si el Sentinel Auditor o el hardware chilla, subimos el dolor
			alerts = payload.get("system_alerts", [])
			self.state.pain_signals = len(alerts)

		elif scope == PluginScope.COGNITION:
			# Aquí está la magia: inyectamos nuestro estado en el prompt que va al LLM
			current_color = self.state.get_color()

			# Forzamos la directiva emocional actual sobrepisando cualquier default
			payload["system_prompt_overrides"] = {"OPERATOR_COLOR": current_color, "TONE_DIRECTIVE": self._get_tone_for(current_color)}

			# Persistir estado asíncronamente en Qdrant
			import uuid

			self.memory_mgr.client.upsert(
				collection_name=self.collection,
				points=[
					PointStruct(
						id=str(uuid.uuid4()),
						vector=[0.0] * cfg.EMBEDDING_DIM,  # Vector dummy alineado dinámicamente
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
