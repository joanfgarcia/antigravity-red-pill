from typing import Any, Dict, List
from pathlib import Path

from red_pill.core.plugin_engine import SovereignPlugin, PluginScope, Priority

import datetime
import math

class BayesianAxonEngine:
    """Motor matemático (B-1.2 y B-1.4)"""
    def __init__(self, decay_rate: float = 0.05, epsilon: float = 0.1, delta: float = 0.2):
        self.decay_rate = decay_rate # λ para el enfriamiento homeostático
        self.epsilon = epsilon       # +Ɛ Recompensa por éxito
        self.delta = delta           # -Δ Castigo por fricción

    def apply_temporal_decay(self, weight: float, last_accessed: datetime.datetime) -> float:
        """B-1.4: Enfriamiento temporal para que las heurísticas no se osifiquen."""
        days_passed = (datetime.datetime.now() - last_accessed).days
        if days_passed <= 0:
            return weight
        return weight * math.exp(-self.decay_rate * days_passed)

    def update_weight(self, current_weight: float, success: bool) -> float:
        """B-1.2: Ajuste de ponderación en base a éxito o fricción."""
        if success:
            # Límite asintótico de 1.0
            return min(1.0, current_weight + self.epsilon * (1.0 - current_weight))
        else:
            # Castigo directo (más severo por default)
            return max(0.0, current_weight - self.delta)


class BayesianLearningPlugin(SovereignPlugin):
    """
    Trinity Phase 1: Motor Bayesiano. 
    Interviene en la memoria para calibrar pesos de engramas basados en fricción/éxito.
    """

    @property
    def scopes(self) -> List[PluginScope]:
        return [PluginScope.MEMORY]

    @property
    def requested_permissions(self) -> List[str]:
        return ["qdrant:read:work_memories", "qdrant:write:work_memories"]

    @property
    def priority(self) -> Priority:
        return Priority.HIGH

    async def init(self) -> None:
        self.engine = BayesianAxonEngine()
        # TODO: Cargar conexión a Qdrant (procedural_memories)

    async def activate(self) -> None:
        pass

    async def hook(self, scope: PluginScope, payload: Dict[str, Any]) -> Dict[str, Any]:
        
        if scope == PluginScope.MEMORY:
            # Verificamos si hay engramas procedimentales recuperados (RAG output)
            engrams = payload.get("retrieved_engrams", [])
            for engram in engrams:
                # 1. Enfriamiento (si el engrama es muy viejo, pierde peso)
                last_used = engram.get("last_accessed", datetime.datetime.now())
                engram["weight"] = self.engine.apply_temporal_decay(engram.get("weight", 0.5), last_used)
                
            payload["retrieved_engrams"] = engrams
            
        elif scope == PluginScope.COGNITION:
            # Durante la inyección cognitiva, parseamos si hubo scolding/fricción en el turno (B-1.3)
            # Ej: payload["operator_friction"] = True si el Operador tuvo que corregirme.
            friction_detected = payload.get("operator_friction", False)
            active_axon = payload.get("active_engram_id") # El engrama que originó la acción
            
            if active_axon:
                # Aquí despacharíamos asíncronamente el update a Qdrant para ajustarlo
                # new_weight = self.engine.update_weight(old_weight, not friction_detected)
                pass
            
        return payload

    async def deactivate(self) -> None:
        pass

    async def uninstall(self, purge: bool = False) -> None:
        if purge:
            # Aquí dropearíamos la colección `procedural_memories` en Qdrant
            pass

    async def export_state(self) -> Dict[str, Any]:
        # Aquí exportaríamos las matrices de pesos bayesianos o el snapshot de engramas activos
        return {
            "decay_rate": self.engine.decay_rate,
            "epsilon": self.engine.epsilon,
            "delta": self.engine.delta
        }
