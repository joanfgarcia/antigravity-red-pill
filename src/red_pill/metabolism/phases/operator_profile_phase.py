"""OperatorProfilePhase: synthesize the operator profile from work + social + directive.

Replaces the old operator_profile_ritual. Recalls (read-only, no reinforcement)
the newest canonical work memories, immune social memories, and immune directives;
asks the local LLM for a short profile of the OPERATOR (name, role, current focus);
publishes operator_profile.md for the wake-up ritual to inject. Skips the cycle
entirely while the artifact is fresher than OPERATOR_PROFILE_UPDATE_INTERVAL_HOURS.
"""

import logging
from typing import List

import red_pill.config as cfg
from red_pill.core.paths import get_data_dir
from red_pill.metabolism.phases.base import SleepContext, SleepPhase
from red_pill.metabolism.phases.synthesis_common import NON_CANONICAL_FILTER, chat, is_fresh, publish, recall_recent, scroll_contents

logger = logging.getLogger(__name__)

TAG = "OPERATOR_PROFILE"
PROFILE_PATH = get_data_dir() / "operator_profile.md"

SYSTEM_PROMPT = "You are a context-summarizer. Output ONLY the operator profile. No preamble, no filler."
USER_PROMPT = """Generate a short profile of the OPERATOR (the human), 2-4 lines: their name, role, key traits, and current focus areas. Be concrete — name real projects and decisions from the data. Spanish or mixed OK.
If no meaningful data about the operator, respond: INSUFFICIENT_DATA

DATA:
{context}"""


def _fetch_social_immune(limit: int = 5) -> List[str]:
	flt = {"must": [{"key": "immune", "match": {"value": True}}], **NON_CANONICAL_FILTER}
	return scroll_contents("social_memories", limit, flt=flt, tag=TAG)


def _fetch_directive_immune(limit: int = 3) -> List[str]:
	flt = {"must": [{"key": "immune", "match": {"value": True}}], **NON_CANONICAL_FILTER}
	return scroll_contents("directive_memories", limit, flt=flt, tag=TAG)


def _synthesize_profile(work: List[str], social: List[str], directives: List[str]) -> str:
	context_parts = []
	if work:
		context_parts.append("RECENT WORK:\n" + "\n".join(f"- {h[:200]}" for h in work[:5]))
	if social:
		context_parts.append("SOCIAL:\n" + "\n".join(f"- {s}" for s in social))
	if directives:
		context_parts.append("DIRECTIVES:\n" + "\n".join(f"- {d}" for d in directives))
	context = "\n\n".join(context_parts) if context_parts else "No data."

	return chat(SYSTEM_PROMPT, USER_PROMPT.format(context=context), max_tokens=250, tag=TAG)


def _validate_profile(profile: str) -> bool:
	if len(profile) < 10:
		return False
	if profile == "INSUFFICIENT_DATA":
		return False
	if "System nominal" in profile:
		return False
	return True


class OperatorProfilePhase(SleepPhase):
	@property
	def name(self) -> str:
		return "operator_profile"

	@property
	def requires_gpu(self) -> bool:
		return True

	def execute(self, ctx: SleepContext) -> None:
		if not cfg.SLEEP_PLUGIN_USP:
			logger.debug(f"[{TAG}] Skipped (SLEEP_PLUGIN_USP=False)")
			return

		max_age = float(getattr(cfg, "OPERATOR_PROFILE_UPDATE_INTERVAL_HOURS", 24))
		if is_fresh(PROFILE_PATH, max_age):
			logger.info(f"[{TAG}] Artifact fresher than {max_age}h. Skipping.")
			return

		logger.info(f"[{TAG}] Synthesizing operator profile (work + social + directive)...")
		try:
			work = recall_recent("work_memories", limit=10, tag=TAG)
			social = _fetch_social_immune(limit=5)
			directives = _fetch_directive_immune(limit=3)

			if not work and not social and not directives:
				logger.warning(f"[{TAG}] No data from any collection. Skipping.")
				return

			logger.info(f"[{TAG}] Fetched: {len(work)} work, {len(social)} social, {len(directives)} directives.")

			profile = _synthesize_profile(work, social, directives)
			if not _validate_profile(profile):
				logger.warning(f"[{TAG}] Profile failed validation: '{profile}'. Keeping existing.")
				return

			publish(PROFILE_PATH, profile)
			logger.info(f"[{TAG}] Written: '{profile[:120]}'")
		except Exception as e:
			logger.error(f"[{TAG}] Cycle failed: {e}")
