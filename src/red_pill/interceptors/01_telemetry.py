import json
import time
from pathlib import Path

import red_pill.config as cfg
from red_pill.interceptors.base import BaseInterceptorPlugin


class TelemetryPlugin(BaseInterceptorPlugin):
	@property
	def name(self) -> str:
		return "Telemetry & Context OS-Agnostic File Reader"

	@property
	def timeout(self) -> float:
		return 0.5  # Should take ~0.001s since it's just reading a file

	def _notes_line(self) -> str:
		"""A-1 (AWAKEN-002): decisiones pendientes que los despertares dejaron al
		Operador (`para: <Operador>` sin `## Leída` del Operador en el desk)."""
		try:
			from red_pill.core import awakening_channel as ch

			operator = ch.operator_name()
			n = ch.count_for_operator(operator=operator)
		except Exception:
			return ""
		if n <= 0:
			return ""
		return f"- Tienes {n} decisión(es) pendiente(s) de despertares (notas `para: {operator}`). (Lee `${{AGENT_CORE_DIR}}/awakening/notes/`)"

	async def execute(self, prompt: str) -> str:
		notes_line = self._notes_line()
		runtime_dir = Path(cfg.get_config().RUNTIME_DIR)
		bunker_state = runtime_dir / "bunker_state.json"
		if not bunker_state.exists():
			return notes_line

		try:
			with open(bunker_state, "r") as f:
				state = json.load(f)

			age = time.time() - state.get("timestamp", 0)
			if age > 300:
				alert = "[SYSTEM ALERT: Bünker Daemon is STALE/OFFLINE. Telemetry age > 5 mins]"
				return f"{alert}\n{notes_line}" if notes_line else alert

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

			if notes_line:
				lines.append(notes_line)

			if len(lines) > 1:
				return "\n".join(lines)
			return ""
		except Exception:
			return notes_line
