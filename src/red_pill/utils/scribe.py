import hashlib
import logging
import os
import re
import time

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
		self.walkthrough_path = os.path.join(brain_path, "walkthrough.md")
		self.memory_mgr = MemoryManager()
		self.last_content = ""
		self.processed_hashes = set()

	def _get_block_hash(self, prompt, response):
		"""Generates a unique hash for a dialogue pair."""
		data = f"{prompt}|||{response}".encode("utf-8")
		return hashlib.md5(data).hexdigest()

	def execute_ritual(self):
		"""Extracts dialogue from walkthrough.md and commits to Bünker."""
		if not os.path.exists(self.walkthrough_path):
			return

		try:
			with open(self.walkthrough_path, "r") as f:
				content = f.read()

			if content == self.last_content:
				return

			self.last_content = content

			# Structural Extract: Find ### 🗨️ Diálogo Reciente section
			# Then look for ANY pair of lines starting with '> '
			matches = re.finditer(r"### 🗨️ Diálogo Reciente\n(.*?)(?=\n###|\Z)", content, re.DOTALL)

			for match in matches:
				block = match.group(1).strip()
				dialogue_lines = [line.strip() for line in block.split("\n") if line.strip().startswith(">")]

				if len(dialogue_lines) >= 2:
					# Symmetrical Agnostic Extraction:
					# Line 0: PROMPT / Line 1+: RESPONSE

					# Strip any label like '> NAME:' or just '>'
					def clean_line(line):
						# Remove leading '> ' and any 'Label: '
						clean = re.sub(r"^>\s*", "", line)
						clean = re.sub(r"^[^:]+:\s*", "", clean)  # Remove 'USER:', 'AGENT:', etc.
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
							logger.info("Shadow Scribe: Ingested unique label-agnostic dialogue.")
						except Exception as e:
							logger.error(f"Scribe: Sync failed: {e}")

		except Exception as e:
			logger.error(f"Shadow Scribe Ritual Failure: {e}")


def run_scribe_service(brain_path):
	scribe = ShadowScribe(brain_path)
	logger.info(f"Shadow Scribe active. Monitoring: {brain_path}")
	while True:
		scribe.execute_ritual()
		time.sleep(30)  # Check every 30 seconds
