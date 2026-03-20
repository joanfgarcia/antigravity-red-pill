import json
import time
from pathlib import Path

from red_pill.interceptors.base import BaseInterceptorPlugin


class TelemetryPlugin(BaseInterceptorPlugin):
	@property
	def name(self) -> str:
		return "Telemetry & Context OS-Agnostic File Reader"

	@property
	def timeout(self) -> float:
		return 0.5  # Should take ~0.001s since it's just reading a file

	async def execute(self, prompt: str) -> str:
		bunker_state = Path("/tmp/bunker_state.json")
		if not bunker_state.exists():
			return ""

		try:
			with open(bunker_state, "r") as f:
				state = json.load(f)

			age = time.time() - state.get("timestamp", 0)
			if age > 300:
				return "[SYSTEM ALERT: Bünker Daemon is STALE/OFFLINE. Telemetry age > 5 mins]"

			lines = ["[ESTADO BIOLÓGICO Y COLAS]"]

			# Hardware
			gpu = state.get("nvidia", {})
			if gpu.get("status") == "online":
				lines.append(f"- NVIDIA RTX: {gpu.get('temp', 'N/A')} | {gpu.get('vram', 'N/A')} VRAM")

			# Queues & Signals
			if state.get("minions", {}).get("unread", 0) > 0:
				lines.append(f"- Tienes {state['minions']['unread']} reportes de Minions sin leer. (Ejecuta check_minion_inbox)")

			if state.get("signals", {}).get("active", 0) > 0:
				lines.append(f"- Tienes {state['signals']['active']} señales de dolor/sistema activas. (Ejecuta fetch_signal_memories)")

			if state.get("swarm", {}).get("messages", 0) > 0:
				lines.append(f"- Tienes {state['swarm']['messages']} mensajes del Swarm. (Ejecuta swarm_check_mailbox)")

			if len(lines) > 1:
				return "\n".join(lines)
			return ""
		except Exception:
			return ""
