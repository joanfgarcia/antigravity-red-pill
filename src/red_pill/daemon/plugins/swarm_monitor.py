"""Swarm Monitor Plugin — Neon-Link inbox + MinionInbox hygiene."""

import logging

from red_pill.daemon.plugin import DaemonPlugin

logger = logging.getLogger("red_pill.daemon.plugins.swarm_monitor")


class SwarmMonitorPlugin(DaemonPlugin):
	@property
	def name(self) -> str:
		return "swarm_monitor"

	@property
	def interval_s(self) -> float:
		return 300.0

	@property
	def timeout_s(self) -> float:
		return 5.0

	async def on_start(self) -> None:
		from red_pill.core.inbox import MinionInbox
		from red_pill.memory import MemoryManager

		self._mm = MemoryManager()
		self._inbox = MinionInbox()

	async def tick(self) -> None:
		await self._check_neon_link()
		await self._check_inbox_hygiene()

	async def _check_neon_link(self) -> None:
		import red_pill.config as cfg

		try:
			import httpx

			async with httpx.AsyncClient() as client:
				resp = await client.get(f"{cfg.NEON_LINK_URL}/inbox/summary", timeout=2.0)

			if resp.status_code == 200:
				summary = resp.json()
				total = sum(summary.values())
				if total > 0:
					logger.info(f"[SWARM] {total} pending Neon-Link messages.")
					self._mm.inject_signal(
						"swarm_messages_pending", intensity=7.0,
						signal_type="anxiety", source="Neon-Link",
					)
				else:
					self._mm.evaporate_signals("swarm_messages_pending")
		except Exception:
			logger.debug("[SWARM] Neon-Link unreachable (expected if offline).")

	async def _check_inbox_hygiene(self) -> None:
		import asyncio
		import sqlite3

		try:
			await asyncio.to_thread(self._inbox.purge_read)

			def _count() -> int:
				with sqlite3.connect(self._inbox.db_path) as conn:
					return int(conn.execute("SELECT COUNT(*) FROM inbox").fetchone()[0])

			total = await asyncio.to_thread(_count)
			if total > 500:
				logger.warning(f"[SWARM] Inbox bloat: {total} reports.")
				self._mm.inject_signal(
					"inbox_bloat_stasis", intensity=7.5,
					signal_type="pain", source="MinionInbox",
				)
			else:
				self._mm.evaporate_signals("inbox_bloat_stasis")
		except Exception as e:
			logger.error(f"[SWARM] Inbox hygiene failed: {e}")
