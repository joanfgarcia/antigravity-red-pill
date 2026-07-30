"""RecentActivityPhase: synthesize session context from the newest memories.

Recalls (read-only, no reinforcement) the most recent canonical engrams from
work_memories and social_memories — synthesis hubs and not-yet-consolidated
memories alike, ordered by created_at — and asks the local LLM for a 2-3 line
summary. Publishes recent_activity.md, which the wake-up ritual injects as the
RECENT_ACTIVITY block, giving the agent a concrete sense of what the operator
has been working on. If synthesis fails, the previous artifact is kept.
"""

import logging
from typing import List

import red_pill.config as cfg
from red_pill.core.paths import get_data_dir
from red_pill.metabolism.phases.base import SleepContext, SleepPhase
from red_pill.metabolism.phases.synthesis_common import chat, is_fresh, publish, recall_recent

logger = logging.getLogger(__name__)

TAG = "RECENT_ACTIVITY"
ACTIVITY_PATH = get_data_dir() / "recent_activity.md"
EMPTY_MARKER = "No recent activity data available."

SYSTEM_PROMPT = "You are a context-summarizer. Output ONLY the 2-3 line activity summary. No preamble, no filler."
USER_PROMPT = """Synthesize a 2-3 line summary of the operator's recent activity. Highlight key technical decisions, project milestones, and emotional context. Be specific, concrete. Spanish or mixed OK. No filler phrases like 'The operator has been...'. Max 3 lines.

DATA:
{context}"""


def _synthesize_activity(work: List[str], social: List[str]) -> str:
	context_parts = []
	if work:
		context_parts.append("RECENT TECHNICAL WORK:\n" + "\n".join(f"- {h[:300]}" for h in work[:8]))
	if social:
		context_parts.append("RECENT SOCIAL/EMOTIONAL CONTEXT:\n" + "\n".join(f"- {s[:300]}" for s in social[:5]))
	if not context_parts:
		return ""

	return chat(SYSTEM_PROMPT, USER_PROMPT.format(context="\n\n".join(context_parts)), max_tokens=250, tag=TAG)


def _validate_activity(text: str) -> bool:
	if not text or len(text) < 20:
		return False
	if "System nominal" in text:
		return False
	return True


class RecentActivityPhase(SleepPhase):
	@property
	def name(self) -> str:
		return "recent_activity"

	@property
	def requires_gpu(self) -> bool:
		return True

	def execute(self, ctx: SleepContext) -> None:
		if not cfg.SLEEP_PLUGIN_CONSOLIDATION:
			logger.debug(f"[{TAG}] Skipped (SLEEP_PLUGIN_CONSOLIDATION=False)")
			return

		max_age = float(getattr(cfg, "RECENT_ACTIVITY_UPDATE_INTERVAL_HOURS", 4))
		if is_fresh(ACTIVITY_PATH, max_age):
			logger.info(f"[{TAG}] Artifact fresher than {max_age}h. Skipping.")
			return

		logger.info(f"[{TAG}] Synthesizing recent activity from newest work + social memories...")
		try:
			work = recall_recent("work_memories", limit=15, tag=TAG)
			social = recall_recent("social_memories", limit=8, tag=TAG)

			logger.info(f"[{TAG}] Fetched: {len(work)} work, {len(social)} social.")

			if not work and not social:
				if not ACTIVITY_PATH.exists():
					publish(ACTIVITY_PATH, EMPTY_MARKER)
				logger.warning(f"[{TAG}] No memories found. Keeping previous artifact.")
				return

			summary = _synthesize_activity(work, social)
			if not _validate_activity(summary):
				# A stale summary beats an arbitrary truncated engram: keep what we have
				logger.warning(f"[{TAG}] Synthesis failed validation. Keeping previous artifact.")
				if not ACTIVITY_PATH.exists():
					publish(ACTIVITY_PATH, EMPTY_MARKER)
				return

			publish(ACTIVITY_PATH, summary)
			logger.info(f"[{TAG}] Written ({len(summary)} chars): '{summary[:120]}...'")
		except Exception as e:
			logger.error(f"[{TAG}] Cycle failed: {e}")
