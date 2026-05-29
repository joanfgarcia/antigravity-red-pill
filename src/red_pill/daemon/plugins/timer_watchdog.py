"""Timer Watchdog Plugin — monitors critical systemd timers."""

import logging

from red_pill.daemon.plugin import DaemonPlugin

logger = logging.getLogger("red_pill.daemon.plugins.timer_watchdog")

CRITICAL_TIMERS = [
	"redpill-worker.timer",
	"redpill-queue.timer",
	"redpill-auditor.timer",
	"redpill-wake.timer",
]


class TimerWatchdogPlugin(DaemonPlugin):
	@property
	def name(self) -> str:
		return "timer_watchdog"

	@property
	def interval_s(self) -> float:
		return 60.0

	@property
	def timeout_s(self) -> float:
		return 5.0

	async def on_start(self) -> None:
		from red_pill.memory import MemoryManager

		self._mm = MemoryManager()

	async def tick(self) -> None:
		import asyncio
		import subprocess

		dead_timers = []
		for timer in CRITICAL_TIMERS:
			result = await asyncio.to_thread(
				subprocess.run,
				["systemctl", "--user", "is-active", timer],
				capture_output=True, text=True, timeout=3,
			)
			if result.stdout.strip() != "active":
				dead_timers.append(timer)

		if dead_timers:
			logger.warning(f"[WATCHDOG] Dead timers: {', '.join(dead_timers)}")
			if not self._mm.has_signal("timers_offline"):
				self._mm.inject_signal(
					"timers_offline", intensity=8.0,
					signal_type="pain", source="TimerWatchdog",
				)
		else:
			self._mm.evaporate_signals("timers_offline")
