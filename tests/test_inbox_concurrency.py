import asyncio
import os
import tempfile

import pytest

from red_pill.core.inbox import MinionInbox


@pytest.mark.asyncio
async def test_inbox_mass_concurrency():
	"""
	Stress test mimicking a massive swarm dropping reports simultaneously.
	If WAL is not enabled or thread handling is poor, this will throw
	sqlite3.OperationalError: database is locked.
	"""
	with tempfile.TemporaryDirectory() as tmpdir:
		db_path = os.path.join(tmpdir, "stress_inbox.db")
		# Initialize to create schema and enable WAL
		_ = MinionInbox(db_path=db_path)

		# Simulating an aggressive 150-container swarm
		num_minions = 150

		async def mock_minion_drop(m_id):
			def _drop():
				# Create a distinct connection/instance as it would happen in real concurrent requests
				local_inbox = MinionInbox(db_path=db_path)
				local_inbox.drop_report(event_id=f"evt_{m_id}", source=f"Minion-{m_id}", status="success", content=f"Report {m_id} payload")

			await asyncio.to_thread(_drop)

		# Fire all tasks as concurrently as asyncio allows
		tasks = [asyncio.create_task(mock_minion_drop(i)) for i in range(num_minions)]
		await asyncio.gather(*tasks)

		# Validation
		check_inbox = MinionInbox(db_path=db_path)
		unread = check_inbox.get_unread(limit=500)

		assert len(unread) == num_minions, f"Expected {num_minions} reports, got {len(unread)}"
