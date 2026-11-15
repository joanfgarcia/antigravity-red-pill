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

	from red_pill.core import prompts as core
	from red_pill.core.identity import identity_bio_with_source

	# El ancla va DELANTE del prompt y viene de la config, no del LLM: las
	# memorias de entrada las escribe el propio agente y heredan su perspectiva,
	# así que sin ancla el resumen acaba invirtiendo Operador y agente
	# (incidente 2026-11-13). El perfil es advisory; el ancla manda.
	anchor, anchor_source = identity_bio_with_source()
	system = f"{anchor}\n\n{core.resolve('metabolism', 'operator_profile_system').text}"
	logger.debug(f"[{TAG}] Anchor source: {anchor_source}")
	user = core.render("metabolism", "operator_profile_user", context=context)
	return chat(system, user, max_tokens=250, tag=TAG)


def _compose_profile(focus: str) -> str:
	"""Cabecera determinista (config) + cola sintetizada (sueño).

	El reparto es estructural, no una súplica al prompt: quién es el Operador se
	escribe desde `OPERATOR_DISPLAY_NAME`, y al LLM solo le queda "en qué anda".
	Así el modelo no puede reescribir nombre, rol ni género ni en 24h ni en 240.
	"""
	operator = str(getattr(cfg, "OPERATOR_DISPLAY_NAME", "") or "Operador")
	return (
		f"OPERADOR: {operator}\n"
		"FOCO ACTUAL (sintetizado del sueño — la identidad vive en OPERATOR_ANCHOR):\n"
		f"{focus.strip()}"
	)


def _validate_profile(profile: str, agent_name: str = "", operator_name: str = "") -> bool:
	if len(profile) < 10:
		return False
	if profile == "INSUFFICIENT_DATA":
		return False
	if "System nominal" in profile:
		return False

	# Guard de inversión (2026-11-13): el perfil nombra al agente como Operador y
	# no menciona al Operador real en su cabecera → se descarta y se conserva el
	# anterior. Cazar esto a la entrada es más barato que leer un perfil mentiroso
	# durante 24h en cada despertar.
	agent = (agent_name or "").strip().lower()
	operator = (operator_name or "").strip().lower()
	if agent and operator and agent != operator:
		head = profile[:200].lower()
		if agent in head and operator not in head:
			logger.warning(f"[{TAG}] Perfil descartado: nombra al agente ('{agent_name}') como Operador.")
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
			if not _validate_profile(
				profile,
				agent_name=str(getattr(cfg, "AGENT_NAME", "")),
				operator_name=str(getattr(cfg, "OPERATOR_DISPLAY_NAME", "")),
			):
				logger.warning(f"[{TAG}] Profile failed validation: '{profile}'. Keeping existing.")
				return

			publish(PROFILE_PATH, _compose_profile(profile))
			logger.info(f"[{TAG}] Written focus: '{profile[:120]}'")
			ctx.record(self.name, 1, published=1)
		except Exception as e:
			logger.error(f"[{TAG}] Cycle failed: {e}")
