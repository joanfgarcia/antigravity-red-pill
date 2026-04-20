import asyncio
import logging
import os
import sys

# Fix path for local imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from red_pill.metabolism.auditor import SentinelAuditor


async def main():
	logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
	logger = logging.getLogger("redpill.auditor_runner")

	logger.info("Sentinel Auditor: Commencing scheduled infrastructure audit...")

	repos = [
		os.path.expanduser("~/Documents/IA/pure-mls"),
		os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	]

	auditor = SentinelAuditor(target_repos=repos)

	for repo in repos:
		try:
			report = auditor.audit_repo(repo)
			auditor.sync_to_thalamus(report)
		except Exception as e:
			logger.error(f"Failed to audit {repo}: {e}")

	logger.info("Sentinel Auditor: Audit cycle complete.")

if __name__ == "__main__":
	asyncio.run(main())
