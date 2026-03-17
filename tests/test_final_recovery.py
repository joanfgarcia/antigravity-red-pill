from unittest.mock import patch

from red_pill.skills.swarm_messaging import SwarmMessagingSkill


def test_swarm_messaging_error():
	"""Test error handling in SwarmMessagingSkill with correct init."""
	skill = SwarmMessagingSkill(agent_identity="Aleph@Test", shared_secret="secret")
	with patch("builtins.open", side_effect=PermissionError("Denied")):
		result = skill.check_mailbox()
		assert result == []
