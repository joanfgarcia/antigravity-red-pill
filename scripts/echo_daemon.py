import asyncio
import logging
import os
import signal
import sys
import time
from pathlib import Path

# Fix path for local imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from red_pill import config as cfg
from red_pill.swarm.factory import MinionFactory

logger = logging.getLogger("red_pill.echo_daemon")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class EchoDaemon:
	"""
	Long-running background process for the Echo Mirror Minion.
	Maintains context integrity and proactive briefings while the IDE is offline.
	"""
	def __init__(self):
		self.running = True
		self.echo = MinionFactory.create("echo_mirror")
		if not self.echo:
			raise RuntimeError("Failed to instantiate EchoMinion via Factory.")

	async def run(self):
		logger.info("Initializing Project Echo Mirror Daemon...")
		
		# Register signal handlers for graceful shutdown
		loop = asyncio.get_running_loop()
		for sig in (signal.SIGINT, signal.SIGTERM):
			loop.add_signal_handler(sig, lambda: self.stop())

		while self.running:
			try:
				# 1. Heartbeat - notify system we are alive
				logger.debug("Echo Heartbeat: Monitoring The Blackwall...")
				
				# 2. Monitor Pulse: Check for recent interactions
				await self.echo.execute("monitor_pulse")
				
				# 4. Sleep interval (configurable)
				await asyncio.sleep(60) # Default: check every minute
			except Exception as e:
				logger.error(f"Echo Daemon Loop Error: {e}")
				await asyncio.sleep(10)

	def stop(self):
		logger.info("Echo Daemon: Shutdown signal received. Hibernating context...")
		self.running = False

if __name__ == "__main__":
	daemon = EchoDaemon()
	asyncio.run(daemon.run())
