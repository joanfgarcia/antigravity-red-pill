import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import red_pill.config as cfg
from red_pill.cognitive.drive_evaluator import DriveEvaluator
from red_pill.cognitive.queue_manager import CognitiveQueueManager
from red_pill.core.paths import get_state_dir


@pytest.fixture
def mock_curiosity_env(tmp_path, monkeypatch):
	# Isolate XDG directories to tmp_path
	monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
	monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
	monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
	monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
	monkeypatch.setenv("IA_DIR", str(tmp_path))
	monkeypatch.setenv("CURIOSITY_PROFILE", "balanced")

	# Mock Path.home to return tmp_path
	monkeypatch.setattr(Path, "home", lambda: tmp_path)

	# Enable curiosity engine setting
	monkeypatch.setattr(cfg, "CURIOSITY_ENGINE_ENABLED", True)

	# Mock urlopen to prevent real network calls and 30s timeouts
	import urllib.request

	mock_response = MagicMock()
	mock_response.read.return_value = b'{"choices": [{"message": {"content": "{\\"action\\": \\"autonomous_research\\", \\"objective\\": \\"mocked_dynamic_task\\", \\"tools_allowed\\": []}"}}]}'
	mock_context = MagicMock()
	mock_context.__enter__.return_value = mock_response
	monkeypatch.setattr(urllib.request, "urlopen", MagicMock(return_value=mock_context))

	# Force cache reload to respect new XDG dirs
	from red_pill.config import get_config

	get_config.cache_clear()

	# Create a temporary queue database
	db_path = tmp_path / "bunker_queue.db"
	queue_manager = CognitiveQueueManager(db_path=str(db_path))

	return queue_manager, tmp_path


def test_curiosity_ratings_initialization(mock_curiosity_env):
	queue_manager, tmp_path = mock_curiosity_env
	DriveEvaluator(queue_manager)

	# Verify curiosity ratings file was initialized
	curiosity_file = get_state_dir() / "curiosity_ratings.json"
	assert curiosity_file.exists()

	with open(curiosity_file, "r") as f:
		ratings = json.load(f)

	assert "balanced" in ratings
	assert "visionary" in ratings
	assert "sentinel" in ratings
	assert "minion_maintenance" in ratings["balanced"]
	assert "dynamic_spark" in ratings["balanced"]
	assert ratings["balanced"]["minion_maintenance"]["rating"] == 25.0
	assert ratings["visionary"]["minion_maintenance"]["rating"] == 10.0
	assert ratings["sentinel"]["minion_maintenance"]["rating"] == 50.0
	assert ratings["balanced"]["dynamic_spark"]["uncertainty"] == 8.33


def test_backlog_scraper(mock_curiosity_env):
	queue_manager, tmp_path = mock_curiosity_env

	# Create mock ATLAS.md and ROADMAP.md
	atlas_dir = tmp_path / ".agent"
	atlas_dir.mkdir(parents=True, exist_ok=True)

	with open(atlas_dir / "ATLAS.md", "w") as f:
		f.write("- [ ] Refactor memory queue\n- [ ] TODO: Update schema\n")

	with open(tmp_path / "ROADMAP.md", "w") as f:
		f.write("- [ ] Implement LLM spark\n")

	evaluator = DriveEvaluator(queue_manager)
	context = evaluator._scrape_context()

	assert "Refactor memory queue" in context
	assert "Update schema" in context
	assert "Implement LLM spark" in context


def test_evaluate_pulse_sleeping_if_active(mock_curiosity_env, monkeypatch):
	queue_manager, tmp_path = mock_curiosity_env
	evaluator = DriveEvaluator(queue_manager)

	# Create a fake activity tracker file under the state directory
	activity_file = get_state_dir() / "last_user_activity.txt"
	activity_file.parent.mkdir(parents=True, exist_ok=True)
	activity_file.touch()

	# Mock Path.stat safely only for last_user_activity.txt
	original_stat = Path.stat

	def mock_stat_fn(self, *args, **kwargs):
		if "last_user_activity.txt" in str(self):
			mock_stat = MagicMock()
			mock_stat.st_mtime = 1000.0
			mock_stat.st_mode = 33188
			return mock_stat
		return original_stat(self, *args, **kwargs)

	monkeypatch.setattr(Path, "stat", mock_stat_fn)

	with patch("time.time", return_value=1050.0):  # 50 seconds elapsed (< 300s)
		injected = evaluator.evaluate_pulse()
		assert injected == 0


def test_evaluate_pulse_selecting_highest_utility(mock_curiosity_env, monkeypatch):
	queue_manager, tmp_path = mock_curiosity_env

	# Ensure activity tracker indicates inactive (does not exist)
	evaluator = DriveEvaluator(queue_manager)

	# Edit curiosity ratings to make proactive_coding highest utility
	curiosity_file = get_state_dir() / "curiosity_ratings.json"
	with open(curiosity_file, "r") as f:
		ratings = json.load(f)

	ratings["balanced"]["proactive_coding"]["rating"] = 99.0
	ratings["balanced"]["minion_maintenance"]["rating"] = 10.0

	with open(curiosity_file, "w") as f:
		json.dump(ratings, f)

	# Set evaluator state to show all cooldowns expired
	state_file = get_state_dir() / "drive_evaluator_state.json"
	if state_file.exists():
		state_file.unlink()

	injected = evaluator.evaluate_pulse()
	assert injected == 1

	# Verify task in queue has correct category and priority
	task = queue_manager.pop_next_task()
	assert task is not None
	assert task["priority"] == 10
	assert task["payload"]["category"] == "proactive_coding"


@patch("urllib.request.urlopen")
def test_dynamic_spark_generation(mock_urlopen, mock_curiosity_env, monkeypatch):
	queue_manager, tmp_path = mock_curiosity_env
	evaluator = DriveEvaluator(queue_manager)

	# Mock LLM API response
	mock_response = MagicMock()
	mock_response.read.return_value = json.dumps(
		{
			"choices": [
				{
					"message": {
						"content": '{"action": "autonomous_research", "objective": "Investigate CUDA optimization techniques", "tools_allowed": ["search_web"]}'
					}
				}
			]
		}
	).encode("utf-8")
	mock_urlopen.return_value.status = 200
	mock_urlopen.return_value.__enter__.return_value = mock_response

	# Set curiosity ratings to make dynamic_spark highest utility
	curiosity_file = get_state_dir() / "curiosity_ratings.json"
	with open(curiosity_file, "r") as f:
		ratings = json.load(f)

	ratings["balanced"]["dynamic_spark"]["rating"] = 99.0
	for key in ratings["balanced"]:
		if key != "dynamic_spark":
			ratings["balanced"][key]["rating"] = 1.0

	with open(curiosity_file, "w") as f:
		json.dump(ratings, f)

	# Set state file as non-existent to force check
	state_file = get_state_dir() / "drive_evaluator_state.json"
	if state_file.exists():
		state_file.unlink()

	injected = evaluator.evaluate_pulse()
	assert injected == 1

	task = queue_manager.pop_next_task()
	assert task is not None
	assert task["payload"]["category"] == "dynamic_spark"
	assert task["payload"]["action"] == "autonomous_research"
	assert "Investigate CUDA optimization" in task["payload"]["objective"]
	assert "search_memory_research" in task["payload"]["tools_allowed"]


def test_rating_updates_on_completion_and_failure(mock_curiosity_env):
	queue_manager, tmp_path = mock_curiosity_env
	DriveEvaluator(queue_manager)

	# Initialize ratings file
	curiosity_file = get_state_dir() / "curiosity_ratings.json"

	# 1. Test success update (proactive_coding - static task rating should stay flat)
	task_id = queue_manager.enqueue_task(source="drive_evaluator", payload={"action": "spawn_mcp_subagent", "category": "proactive_coding"})

	queue_manager.mark_completed(task_id)

	with open(curiosity_file, "r") as f:
		ratings = json.load(f)

	assert ratings["balanced"]["proactive_coding"]["executed_count"] == 1
	assert ratings["balanced"]["proactive_coding"]["last_rho"] == 1.0
	assert ratings["balanced"]["proactive_coding"]["rating"] == 35.0  # rating stayed flat (reward = 0.0)

	# 2. Test success update (dynamic_spark - should increase from 40.0)
	task_id_spark = queue_manager.enqueue_task(source="drive_evaluator", payload={"action": "autonomous_research", "category": "dynamic_spark"})

	queue_manager.mark_completed(task_id_spark)

	with open(curiosity_file, "r") as f:
		ratings = json.load(f)

	assert ratings["balanced"]["dynamic_spark"]["executed_count"] == 1
	assert ratings["balanced"]["dynamic_spark"]["last_rho"] == 1.0
	assert ratings["balanced"]["dynamic_spark"]["rating"] > 40.0  # rating increased from 40.0

	# 3. Test failure update (dynamic_spark - should decrease from the new rating)
	last_rating = ratings["balanced"]["dynamic_spark"]["rating"]
	task_id_spark_fail = queue_manager.enqueue_task(source="drive_evaluator", payload={"action": "autonomous_research", "category": "dynamic_spark"})

	queue_manager.mark_failed(task_id_spark_fail, "LLM timeout")

	with open(curiosity_file, "r") as f:
		ratings = json.load(f)

	assert ratings["balanced"]["dynamic_spark"]["executed_count"] == 2
	assert ratings["balanced"]["dynamic_spark"]["last_rho"] == 0.0
	assert ratings["balanced"]["dynamic_spark"]["rating"] < last_rating  # rating decreased


def test_profile_switching_isolation(mock_curiosity_env, monkeypatch):
	queue_manager, tmp_path = mock_curiosity_env

	# Default profile: balanced
	DriveEvaluator(queue_manager)
	curiosity_file = get_state_dir() / "curiosity_ratings.json"

	# Update active profile to visionary on the config singleton
	from red_pill.config import get_config

	monkeypatch.setattr(get_config(), "CURIOSITY_PROFILE", "visionary")

	# Re-init evaluator to register profile change
	DriveEvaluator(queue_manager)

	task_id = queue_manager.enqueue_task(source="drive_evaluator", payload={"action": "autonomous_research", "category": "dynamic_spark"})
	queue_manager.mark_completed(task_id)

	with open(curiosity_file, "r") as f:
		ratings = json.load(f)

	# Verify ratings updated in visionary but NOT balanced
	assert ratings["visionary"]["dynamic_spark"]["executed_count"] == 1
	assert ratings["visionary"]["dynamic_spark"]["rating"] > 60.0  # increased from visionary baseline 60
	assert ratings["balanced"]["dynamic_spark"]["executed_count"] == 0
	assert ratings["balanced"]["dynamic_spark"]["rating"] == 40.0  # balanced baseline 40 unchanged


def test_profile_temperature_scaling(mock_curiosity_env, monkeypatch):
	queue_manager, tmp_path = mock_curiosity_env
	evaluator = DriveEvaluator(queue_manager)

	# Verify default (balanced) temperature is 0.3
	with patch("urllib.request.urlopen") as mock_urlopen:
		mock_response = MagicMock()
		mock_response.read.return_value = b'{"choices": [{"message": {"content": "{}"}}]}'
		mock_urlopen.return_value.status = 200
		mock_urlopen.return_value.__enter__.return_value = mock_response

		evaluator._generate_dynamic_spark()

		# check payload sent to urlopen
		args, kwargs = mock_urlopen.call_args
		req = args[0]
		payload = json.loads(req.data.decode("utf-8"))
		assert payload["temperature"] == 0.3

	# Switch to visionary
	from red_pill.config import get_config

	monkeypatch.setattr(get_config(), "CURIOSITY_PROFILE", "visionary")
	evaluator = DriveEvaluator(queue_manager)

	with patch("urllib.request.urlopen") as mock_urlopen:
		mock_response = MagicMock()
		mock_response.read.return_value = b'{"choices": [{"message": {"content": "{}"}}]}'
		mock_urlopen.return_value.status = 200
		mock_urlopen.return_value.__enter__.return_value = mock_response

		evaluator._generate_dynamic_spark()

		args, kwargs = mock_urlopen.call_args
		req = args[0]
		payload = json.loads(req.data.decode("utf-8"))
		assert payload["temperature"] == 0.7

	# Switch to sentinel
	monkeypatch.setattr(get_config(), "CURIOSITY_PROFILE", "sentinel")
	evaluator = DriveEvaluator(queue_manager)

	with patch("urllib.request.urlopen") as mock_urlopen:
		mock_response = MagicMock()
		mock_response.read.return_value = b'{"choices": [{"message": {"content": "{}"}}]}'
		mock_urlopen.return_value.status = 200
		mock_urlopen.return_value.__enter__.return_value = mock_response

		evaluator._generate_dynamic_spark()

		args, kwargs = mock_urlopen.call_args
		req = args[0]
		payload = json.loads(req.data.decode("utf-8"))
		assert payload["temperature"] == 0.1


def test_fsrs_decay_calculation(mock_curiosity_env, monkeypatch):
	queue_manager, tmp_path = mock_curiosity_env

	# Isolate Aleth_Core root to prevent writing to real TODO.md
	monkeypatch.setattr("red_pill.core.paths.get_aleth_core_root", lambda: tmp_path / "aleth_core")

	evaluator = DriveEvaluator(queue_manager)

	# 1. When last_user_activity.txt does not exist, temporal_decay should be 1.0
	activity_file = get_state_dir() / "last_user_activity.txt"
	if activity_file.exists():
		activity_file.unlink()

	# Let's mock todo_path
	from red_pill.core.paths import get_aleth_core_root

	todo_dir = get_aleth_core_root()
	todo_dir.mkdir(parents=True, exist_ok=True)
	todo_file = todo_dir / "TODO.md"
	with open(todo_file, "w") as f:
		f.write("- [ ] Task 1\n")

	# Mock git status to return empty (no mods)
	with patch("subprocess.run") as mock_run:
		mock_result = MagicMock()
		mock_result.returncode = 0
		mock_result.stdout = ""
		mock_run.return_value = mock_result

		# Case A: Activity file does not exist
		if activity_file.exists():
			activity_file.unlink()

		# Mock time.time()
		with patch("time.time", return_value=200000.0):
			with patch("red_pill.cognitive.drive_evaluator.logger") as mock_logger:
				evaluator.evaluate_pulse()
				entropy_log = [call for call in mock_logger.info.call_args_list if "Total System Entropy" in call[0][0]]
				assert len(entropy_log) > 0
				log_msg = entropy_log[0][0][0]
				calculated_entropy = float(log_msg.split(": ")[-1])
				# backlog = 0.2, workspace = 0.0, no activity file -> temporal_decay = 1.0. Total = 1.2
				assert calculated_entropy == pytest.approx(1.2)

			# Case B: Activity file exists and has mtime = 200000 - 24 hours (86400 seconds)
			activity_file.parent.mkdir(parents=True, exist_ok=True)
			activity_file.touch()

			original_stat = Path.stat

			def mock_stat_fn(self, *args, **kwargs):
				if "last_user_activity.txt" in str(self):
					mock_stat = MagicMock()
					mock_stat.st_mtime = 200000.0 - 86400.0
					mock_stat.st_mode = 33188
					return mock_stat
				return original_stat(self, *args, **kwargs)

			monkeypatch.setattr(Path, "stat", mock_stat_fn)

			with patch("red_pill.cognitive.drive_evaluator.logger") as mock_logger:
				evaluator.evaluate_pulse()
				entropy_log = [call for call in mock_logger.info.call_args_list if "Total System Entropy" in call[0][0]]
				assert len(entropy_log) > 0
				log_msg = entropy_log[0][0][0]
				calculated_entropy = float(log_msg.split(": ")[-1])
				# backlog = 0.2, workspace = 0.0, temporal_decay = 1.0 - 0.81 = 0.19. Total = 0.39
				assert calculated_entropy == pytest.approx(0.39)
