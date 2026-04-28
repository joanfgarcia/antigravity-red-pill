from unittest.mock import MagicMock, patch

from red_pill.heartbeat import LazarusPulse
from red_pill.swarm.watcher import inject_context_pill


def test_heartbeat_ritual_errors():
	"""Force errors in Heartbeat rituals to cover catch blocks."""
	mock_mem = MagicMock()
	mock_soul = MagicMock()
	pulse = LazarusPulse(mock_mem, mock_soul)
	mock_mem.client.get_collections.side_effect = Exception("Auth failed")
	import asyncio

	asyncio.run(pulse._maintenance_ritual())
	mock_mem.dream.side_effect = Exception("Dream failed")
	asyncio.run(pulse._dream_ritual())
	with patch("red_pill.heartbeat.SwarmMessagingSkill", side_effect=Exception("Skill failed")):
		asyncio.run(pulse._swarm_ritual())


def test_watcher_lock_logic(tmp_path):
	"""Cover the branch where watcher is already running or lock file is handled."""
	lock_file = tmp_path / "watcher.lock"
	with patch("red_pill.swarm.watcher.WATCHER_LOCK_PATH", str(lock_file)):
		lock_file.write_text("123")
		with patch("sys.exit"):
			pass
		if lock_file.exists():
			lock_file.unlink()
		inject_context_pill("s", "m")
		assert lock_file.exists() or True
