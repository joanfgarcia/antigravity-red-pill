"""Echo Plugin — monitors context integrity via Echo Mirror minion."""

import logging

from red_pill.daemon.plugin import DaemonPlugin

logger = logging.getLogger("red_pill.daemon.plugins.echo")


class EchoPlugin(DaemonPlugin):
	@property
	def name(self) -> str:
		return "echo"

	@property
	def interval_s(self) -> float:
		return 60.0

	@property
	def timeout_s(self) -> float:
		return 15.0

	async def on_start(self) -> None:
		from red_pill.swarm.factory import MinionFactory

		self._echo = MinionFactory.create("echo_mirror")
		if not self._echo:
			logger.warning("[ECHO] Failed to create echo_mirror minion. Plugin will skip ticks.")

	async def tick(self) -> None:
		if not self._echo:
			return
		try:
			await self._echo.execute("monitor_pulse")
		except Exception as e:
			logger.error(f"[ECHO] monitor_pulse failed: {e}")
