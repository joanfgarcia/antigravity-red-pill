import hashlib
import logging
import os
import re
import time
from typing import List

from red_pill.memory import MemoryManager

logger = logging.getLogger("red_pill.shadow_scribe")


class ShadowScribe:
	"""
	Shadow Scribe Ritual
	Monitors artifacts (walkthrough.md) to extract and ingest
	dialogue into the Bünker without extra token costs.
	"""

	def __init__(self, brain_path):
		self.brain_path = brain_path
		self.memory_mgr = MemoryManager()
		self.last_contents = {}  # dict per walkthrough path
		self.processed_hashes = set()

	def _get_block_hash(self, prompt, response):
		"""Generates a unique hash for a dialogue pair."""
		data = f"{prompt}|||{response}".encode("utf-8")
		return hashlib.md5(data).hexdigest()

	def _discover_walkthroughs(self):
		"""Scans subdirectories for walkthrough.md files."""
		walkthroughs: List[str] = []
		if not os.path.exists(self.brain_path):
			return walkthroughs

		for entry in os.scandir(self.brain_path):
			if entry.is_dir():
				wt_path = os.path.join(entry.path, "walkthrough.md")
				if os.path.exists(wt_path):
					walkthroughs.append(wt_path)
		return walkthroughs

	def _process_walkthrough(self, walkthrough_path):
		"""Processes an individual walkthrough file."""
		try:
			with open(walkthrough_path, "r") as f:
				content = f.read()

			if content == self.last_contents.get(walkthrough_path):
				return

			self.last_contents[walkthrough_path] = content

			# Structural Extract: Find ### 🗨️ Diálogo Reciente section
			matches = re.finditer(r"### 🗨️ Diálogo Reciente\n(.*?)(?=\n###|\Z)", content, re.DOTALL)

			for match in matches:
				block = match.group(1).strip()
				dialogue_lines = [line.strip() for line in block.split("\n") if line.strip().startswith(">")]

				if len(dialogue_lines) >= 2:

					def clean_line(line):
						clean = re.sub(r"^>\s*", "", line)
						clean = re.sub(r"^[^:]+:\s*", "", clean)
						return clean.strip()

					prompt = clean_line(dialogue_lines[0])
					response = "\n".join([clean_line(line) for line in dialogue_lines[1:]]).strip()

					if prompt and response:
						block_hash = self._get_block_hash(prompt, response)
						if block_hash in self.processed_hashes:
							continue

						try:
							self.memory_mgr.record_interaction_pair(prompt, response, role="assistant")
							self.processed_hashes.add(block_hash)
							logger.info(f"Shadow Scribe: Ingested dialogue from {os.path.basename(os.path.dirname(walkthrough_path))}")
						except Exception as e:
							logger.error(f"Scribe: Sync failed for {walkthrough_path}: {e}")

		except Exception as e:
			logger.error(f"Shadow Scribe failed processing {walkthrough_path}: {e}")

	def execute_ritual(self):
		"""Discovers and processes all available walkthroughs."""
		for wt_path in self._discover_walkthroughs():
			self._process_walkthrough(wt_path)


def run_scribe_service(brain_path):
	scribe = ShadowScribe(brain_path)
	logger.info(f"Shadow Scribe active. Monitoring: {brain_path}")
	while True:
		scribe.execute_ritual()
		time.sleep(30)  # Check every 30 seconds
