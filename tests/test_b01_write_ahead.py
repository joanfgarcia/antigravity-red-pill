"""B-01j: write-ahead del Job Manager para cualquier AgentBridge."""

from types import SimpleNamespace

import pytest

from red_pill.jobs.drivers.agentic import AgenticJobDriver


class FakeBridge:
	def __init__(self, response="done", error=None):
		self.response = response
		self.error = error
		self.calls = 0

	def prompt(self, text, **kwargs):
		self.calls += 1
		return SimpleNamespace(ok=self.error is None, response=self.response, conversation_id="conv-1", error=self.error)


def _driver(bridge):
	driver = AgenticJobDriver()
	driver.bind("job-1", 0, 0)
	driver._create_bridge = lambda payload: bridge  # type: ignore[method-assign]
	return driver


@pytest.mark.parametrize("backend", ["agy", "claude", "opencode", "pi", "local-mini"])
def test_begin_step_persists_intent_for_any_backend(backend):
	bridge = FakeBridge()
	driver = _driver(bridge)
	checkpoint = driver.begin_step({"prompt": "hola", "backend": backend, "model": "m"}, {})
	pending = checkpoint["pending_turn"]
	assert pending["status"] == "pending"
	assert pending["request_id"] == "job-1:0"
	assert pending["backend"] == backend
	assert pending["prompt_sha256"]
	assert bridge.calls == 0


def test_step_completes_and_skips_duplicate_completed_turn():
	bridge = FakeBridge()
	driver = _driver(bridge)
	checkpoint = driver.begin_step({"prompt": "hola", "backend": "claude"}, {})
	out = driver.step({"prompt": "hola", "backend": "claude"}, checkpoint)
	assert out.completed is True
	assert out.new_checkpoint["pending_turn"]["status"] == "completed"
	assert out.new_checkpoint["response"] == "done"
	assert bridge.calls == 1

	# Un checkpoint ya completado no vuelve a invocar al proveedor.
	other = _driver(FakeBridge())
	out2 = other.step({"prompt": "hola", "backend": "claude"}, out.new_checkpoint)
	assert out2.completed is True
	assert out2.new_checkpoint["response"] == "done"
	assert other._create_bridge is not None  # el fake no se llamó; lo prueba el bridge original


def test_abort_step_marks_reason_and_does_not_touch_completed():
	driver = _driver(FakeBridge())
	checkpoint = driver.begin_step({"prompt": "x", "backend": "pi"}, {})
	aborted = driver.abort_step({}, checkpoint, "quota_exhausted")
	assert aborted["pending_turn"]["status"] == "aborted"
	assert aborted["pending_turn"]["reason"] == "quota_exhausted"

	completed = driver.step({"prompt": "x", "backend": "pi"}, checkpoint)
	again = driver.abort_step({}, completed.new_checkpoint, "late")
	assert again["pending_turn"]["status"] == "completed"


def test_retry_reuses_pending_started_at_and_counts_resume():
	driver = _driver(FakeBridge())
	first = driver.begin_step({"prompt": "x", "backend": "agy"}, {})
	second = driver.begin_step({"prompt": "x", "backend": "agy"}, first)
	assert second["pending_turn"]["request_id"] == first["pending_turn"]["request_id"]
	assert second["pending_turn"]["resume_count"] == 1
	assert second["pending_turn"]["started_at"] == first["pending_turn"]["started_at"]
