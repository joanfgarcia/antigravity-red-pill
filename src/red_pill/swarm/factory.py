from typing import Dict, Optional, Type

from red_pill.swarm.agents.agent import AgentMinion
from red_pill.swarm.agents.command import CommandMinion
from red_pill.swarm.agents.echo import EchoMinion
from red_pill.swarm.agents.healer import HealerMinion
from red_pill.swarm.agents.janitor import JanitorMinion
from red_pill.swarm.agents.samantha import SamanthaMinion
from red_pill.swarm.agents.sleep_minions import SleepFinalizeMinion, SleepPhaseMinion, SleepRitualMinion
from red_pill.swarm.agents.smith import SmithMinion
from red_pill.swarm.base import Minion


class MinionFactory:
	"""
	Factory to instantiate Minions from registry IDs.
	"""

	MAPPING: Dict[str, Type[Minion]] = {
		"smith_security": SmithMinion,
		"samantha_analysis": SamanthaMinion,
		"command_runner": CommandMinion,
		"healer": HealerMinion,
		"echo_mirror": EchoMinion,
		"janitor_cleanup": JanitorMinion,
		"agent": AgentMinion,
		# Minions de sleep (RFC_JOB_DAG §4.2 fleco 2): el ciclo de sueño como
		# receta del dag_job en vez de un driver con mecánica propia.
		"sleep_ritual": SleepRitualMinion,
		"sleep_phase": SleepPhaseMinion,
		"sleep_finalize": SleepFinalizeMinion,
	}

	# Specialized Command Aliases
	COMMAND_ALIASES = {
		"ruff_linter": ("command_runner", {"command": "ruff check ."}),
		"pytest_runner": ("command_runner", {"command": "pytest"}),
		"changelog_generator": ("command_runner", {"command": "git log --oneline -n 10"}),  # Placeholder
	}

	@classmethod
	def create(cls, minion_id: str, **kwargs) -> Optional[Minion]:
		"""
		Creates a minion based on ID.
		Supports direct mapping and command aliases.
		"""
		# 1. Check direct mapping
		minion_class = cls.MAPPING.get(minion_id)
		if minion_class:
			return minion_class(**kwargs)

		# 2. Check command aliases
		alias = cls.COMMAND_ALIASES.get(minion_id)
		if alias:
			base_id, base_kwargs = alias
			merged_kwargs = {**base_kwargs, **kwargs}
			return cls.create(base_id, **merged_kwargs)

		return None
