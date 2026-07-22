"""Vitals Plugin — read-only system health checks (ex heartbeat._maintenance_ritual)."""

import logging

from red_pill.daemon.plugin import DaemonPlugin

logger = logging.getLogger("red_pill.daemon.plugins.vitals")


class VitalsPlugin(DaemonPlugin):
	@property
	def name(self) -> str:
		return "vitals"

	@property
	def interval_s(self) -> float:
		return 120.0

	@property
	def timeout_s(self) -> float:
		return 15.0

	async def on_start(self) -> None:
		from red_pill.memory import MemoryManager

		self._mm = MemoryManager()

	async def tick(self) -> None:
		import asyncio

		await asyncio.to_thread(self._check_qdrant)
		await asyncio.to_thread(self._check_fever)
		await asyncio.to_thread(self._check_bloat)
		await asyncio.to_thread(self._check_amnesia)

	def _check_qdrant(self) -> None:
		"""Qdrant connectivity (hippocampus link)."""
		try:
			self._mm.client.get_collections()
			self._mm.evaporate_signals("qdrant_hypoxia")
		except Exception:
			logger.critical("[VITALS] Bünker connection lost (COMA). External defibrillation required.")
			# Inject muted (SQLite MinionInbox) — Qdrant is down, so a normal inject would fail too.
			try:
				self._mm.inject_signal("qdrant_hypoxia", intensity=10.0, signal_type="pain", source="VITALS", muted=True)
			except Exception:
				pass

	def _check_fever(self) -> None:
		"""CPU temperature monitoring."""
		try:
			import psutil

			temps = psutil.sensors_temperatures()
			max_temp = 0.0
			for _name, entries in temps.items():
				for entry in entries:
					if entry.current and entry.current > max_temp:
						max_temp = entry.current
			if max_temp > 85.0:
				logger.warning(f"[VITALS] CPU Fever: {max_temp}°C")
				self._mm.inject_signal("cpu_fever", intensity=7.0, signal_type="fever", source="HARDWARE")
			else:
				self._mm.evaporate_signals("cpu_fever")
		except ImportError:
			pass  # psutil not installed
		except Exception:
			pass  # No sensors available

	def _check_bloat(self) -> None:
		"""Semantic vector bloat detection."""
		import red_pill.config as cfg

		try:
			count = self._mm.client.count(collection_name="work_memories").count
			threshold = getattr(cfg, "SIGNAL_MIGRAINE_VECTORS", 25000)
			if count > threshold:
				logger.warning(f"[VITALS] Semantic bloat: {count} vectors.")
				self._mm.inject_signal("semantic_migraine", intensity=6.0, signal_type="fatigue", source="HIPPOCAMPUS")
			else:
				self._mm.evaporate_signals("semantic_migraine")
		except Exception:
			pass

	def _check_amnesia(self) -> None:
		"""Korsakoff amnesia: idle time without interactions."""
		import datetime
		import os

		import red_pill.config as cfg

		if not getattr(cfg, "INTERCEPTOR_ENABLED", False):
			return
		try:
			state_file = getattr(cfg, "METABOLISM_STATE_FILE", "")
			if state_file and os.path.exists(state_file):
				mtime = os.path.getmtime(state_file)
				hours_idle = (datetime.datetime.now().timestamp() - mtime) / 3600.0
				threshold = getattr(cfg, "SIGNAL_AMNESIA_HOURS", 48)
				if hours_idle > threshold:
					logger.warning(f"[VITALS] Korsakoff: {hours_idle:.1f}h idle.")
					self._mm.inject_signal(
						"korsakoff_amnesia",
						intensity=5.5,
						signal_type="anxiety",
						source="HIPPOCAMPUS",
					)
				else:
					self._mm.evaporate_signals("korsakoff_amnesia")
		except Exception:
			pass
