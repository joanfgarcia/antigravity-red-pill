"""CommandMinion — scope cgroup por-job (SHARD-15) y saneo de `memory_max`.

Regresión del fix que da a cada comando de un dag_job su propio scope systemd
`redpill-job-<short>-*` (para que `job kill` abata el ÁRBOL completo), y del
endurecimiento que rechaza `MemoryMax=infinity` (SHARD-PSEC-01). Se captura el
argv real sin depender de un systemd de usuario vivo.
"""

from __future__ import annotations

import asyncio
import shutil

import pytest

from red_pill.swarm.agents.command import CommandMinion


class _FakeProc:
	returncode = 0
	pid = 4242

	async def communicate(self):
		return (b"ok", b"")


def _capture(monkeypatch) -> list:
	captured: list = []

	async def fake(*argv, **kwargs):
		captured.append(list(argv))
		return _FakeProc()

	monkeypatch.setattr(asyncio, "create_subprocess_exec", fake)
	monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/systemd-run" if name == "systemd-run" else None)
	return captured


def test_scope_prefix_and_memory(monkeypatch):
	"""Con job_id, el argv va envuelto en `systemd-run --scope --unit=redpill-job-<short>-*`."""
	captured = _capture(monkeypatch)
	job_id = "abcdef1234567890"
	result = asyncio.run(CommandMinion().execute(["true"], job_id=job_id, memory_max="8G"))
	assert result["status"] == "success"
	argv = captured[0]
	assert argv[:4] == ["systemd-run", "--user", "--scope", "--quiet"]
	assert argv[4].startswith(f"--unit=redpill-job-{job_id[:8]}-")
	assert "-p" in argv and "MemoryMax=8G" in argv
	assert argv[-2:] == ["--", "true"]


def test_no_job_id_no_scope(monkeypatch):
	"""Sin job_id no se envuelve (uso genérico del minion)."""
	captured = _capture(monkeypatch)
	asyncio.run(CommandMinion().execute(["true"]))
	assert captured[0][0] != "systemd-run"


def test_memory_max_infinity_rejected(monkeypatch):
	"""`params.memory_max=infinity` no puede ensanchar el confín del cgroup."""
	_capture(monkeypatch)
	with pytest.raises(ValueError):
		asyncio.run(CommandMinion().execute(["true"], job_id="deadbeef", memory_max="infinity"))
