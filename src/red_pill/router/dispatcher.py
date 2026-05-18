from dataclasses import dataclass


@dataclass
class CognitiveTask:
	"""Representa una tarea atómica dentro del enjambre soberano."""
	domain: str	   # Dominio de especialidad: "logic", "code", "general"
	payload: str	  # El texto en bruto o instrucciones de la tarea

class SwarmRouter:
	"""
	Capa de triaje determinista. 
	Inspecciona la tarea y decide a qué modelo/experto delegarla.
	"""

	async def dispatch(self, task: CognitiveTask) -> str:
		"""Enruta la tarea al experto adecuado usando pattern matching estructural."""

		match task.domain:
			case "logic" | "prolog":
				# Futuro: await self._call_prolog_expert(task.payload)
				return f"[ROUTER -> PROLOG EXPERT]: Tarea interceptada y desviada. Payload: {task.payload[:20]}..."

			case "code" | "python":
				# Futuro: await self._call_python_expert(task.payload)
				return f"[ROUTER -> PYTHON EXPERT]: Tarea interceptada y desviada. Payload: {task.payload[:20]}..."

			case _:
				# Fallback de seguridad al LLM Monolítico
				# Futuro: await self._call_general_monolith(task.payload)
				return f"[ROUTER -> MONOLITH]: Dominio desconocido. Fallback a IA general. Payload: {task.payload[:20]}..."
