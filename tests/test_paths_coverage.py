"""Coverage boost for red_pill.core.paths — path resolvers and migration branches."""

from pathlib import Path
from unittest.mock import patch

from red_pill.core import paths


class TestGetBunkerRoot:
	def test_env_override(self, tmp_path, monkeypatch):
		monkeypatch.setenv("IA_DIR", str(tmp_path))
		assert paths.get_bunker_root() == tmp_path

	def test_creates_if_missing(self, tmp_path, monkeypatch):
		target = tmp_path / "new_bunker"
		monkeypatch.setenv("IA_DIR", str(target))
		result = paths.get_bunker_root()
		assert result.exists()

	@patch("red_pill.core.paths.sys.exit")
	@patch("red_pill.core.paths.os.access", return_value=False)
	def test_no_access_exits(self, mock_access, mock_exit, tmp_path, monkeypatch):
		monkeypatch.setenv("IA_DIR", str(tmp_path))
		paths.get_bunker_root()
		mock_exit.assert_called_once_with(1)


class TestGetBunkerRootStr:
	def test_returns_string(self, tmp_path, monkeypatch):
		monkeypatch.setenv("IA_DIR", str(tmp_path))
		assert isinstance(paths.get_bunker_root_str(), str)


class TestGetAlethCoreRoot:
	def test_env_override(self, tmp_path, monkeypatch):
		monkeypatch.setenv("ALETH_CORE_DIR", str(tmp_path))
		assert paths.get_aleth_core_root() == tmp_path

	def test_default_relative_to_bunker(self, tmp_path, monkeypatch):
		monkeypatch.delenv("ALETH_CORE_DIR", raising=False)
		monkeypatch.setenv("IA_DIR", str(tmp_path))
		result = paths.get_aleth_core_root()
		assert result == tmp_path.parent / "Aleth_Core"


class TestGetDataDir:
	def test_creates_directory(self):
		result = paths.get_data_dir()
		assert result.exists()
		assert result.is_dir()


class TestGetDbDir:
	def test_creates_subdirectory(self):
		result = paths.get_db_dir()
		assert result.exists()
		assert result.name == "db"


class TestGetModelsDir:
	def test_creates_subdirectory(self):
		result = paths.get_models_dir()
		assert result.exists()
		assert result.name == "models"


class TestGetQueueDir:
	def test_creates_subdirectory(self):
		result = paths.get_queue_dir()
		assert result.exists()
		assert result.name == "queue"


class TestGetStateDir:
	def test_creates_subdirectory(self):
		result = paths.get_state_dir()
		assert result.exists()
		assert result.name == "state"


class TestGetLogDir:
	def test_creates_subdirectory(self):
		result = paths.get_log_dir()
		assert result.exists()
		assert result.name == "logs"


class TestGetKeysDir:
	def test_creates_subdirectory(self):
		result = paths.get_keys_dir()
		assert result.exists()
		assert result.name == "keys"


class TestGetUnencryptedConversationsDir:
	def test_creates_subdirectory(self):
		result = paths.get_unencrypted_conversations_dir()
		assert result.exists()
		assert result.name == "unencrypted_conversations"


class TestGetBackupsDir:
	def test_env_override(self, tmp_path, monkeypatch):
		monkeypatch.setenv("RED_PILL_BACKUP_DIR", str(tmp_path))
		assert paths.get_backups_dir() == tmp_path

	def test_default_relative_to_bunker(self, tmp_path, monkeypatch):
		monkeypatch.delenv("RED_PILL_BACKUP_DIR", raising=False)
		monkeypatch.setenv("IA_DIR", str(tmp_path))
		result = paths.get_backups_dir()
		assert result.name == "red-pill"


class TestGetConfigDir:
	def test_returns_path(self):
		result = paths.get_config_dir()
		assert isinstance(result, Path)


class TestGetNeonLinkConfigDir:
	def test_returns_path(self):
		result = paths.get_neon_link_config_dir()
		assert isinstance(result, Path)


class TestGetNeonLinkDataDir:
	def test_returns_path(self):
		result = paths.get_neon_link_data_dir()
		assert isinstance(result, Path)


class TestGetNeonLinkDbPath:
	def test_returns_events_db(self):
		result = paths.get_neon_link_db_path()
		assert result.name == "events.db"


class TestResolveModelPath:
	def test_joins_with_models_dir(self):
		result = paths.resolve_model_path("test.gguf")
		assert result.name == "test.gguf"
		assert "models" in str(result)


class TestResolveLlamaBinary:
	@patch("red_pill.core.paths.get_bunker_root")
	def test_fallback_to_system(self, mock_bunker, tmp_path):
		mock_bunker.return_value = tmp_path
		with patch("shutil.which", return_value="/usr/bin/llama-server"):
			result = paths.resolve_llama_binary()
			assert result == Path("/usr/bin/llama-server")

	@patch("red_pill.core.paths.get_bunker_root")
	def test_returns_cuda_path_when_no_system(self, mock_bunker, tmp_path):
		mock_bunker.return_value = tmp_path
		with patch("shutil.which", return_value=None):
			result = paths.resolve_llama_binary()
			assert "build_cuda" in str(result)


class TestGetDaemonDir:
	def test_creates_directory(self):
		result = paths.get_daemon_dir()
		assert result.exists()
		assert result.name == "red-pill"


class TestGetDaemonPersistentDir:
	def test_creates_subdirectory(self):
		result = paths.get_daemon_persistent_dir()
		assert result.exists()
		assert result.name == "daemon"


class TestGetModelProfilesPath:
	def test_returns_yaml_file(self):
		result = paths.get_model_profiles_path()
		assert result.name == "model_profiles.yaml"


class TestGetAgentDir:
	def test_returns_home_agent(self):
		result = paths.get_agent_dir()
		assert result == Path.home() / ".agent"


class TestGetThreadStatePath:
	def test_returns_json_file(self):
		result = paths.get_thread_state_path()
		assert result.name == "thread_state.json"


class TestGetStagingDir:
	def test_creates_subdirectory(self):
		result = paths.get_staging_dir()
		assert result.exists()
		assert result.name == "staging"


class TestGetIngestionDir:
	def test_creates_subdirectory(self):
		result = paths.get_ingestion_dir()
		assert result.exists()
		assert result.name == "ingestion"


class TestGetAntigravityRoot:
	def test_env_override(self, tmp_path, monkeypatch):
		monkeypatch.setenv("ANTIGRAVITY_ROOT", str(tmp_path))
		assert paths.get_antigravity_root() == tmp_path

	def test_default(self, monkeypatch):
		monkeypatch.delenv("ANTIGRAVITY_ROOT", raising=False)
		result = paths.get_antigravity_root()
		assert result == Path.home() / ".gemini" / "antigravity"


class TestGetAntigravityBrainDir:
	def test_env_override(self, tmp_path, monkeypatch):
		monkeypatch.setenv("ANTIGRAVITY_BRAIN_PATH", str(tmp_path))
		assert paths.get_antigravity_brain_dir() == tmp_path

	def test_default(self, monkeypatch):
		monkeypatch.delenv("ANTIGRAVITY_BRAIN_PATH", raising=False)
		result = paths.get_antigravity_brain_dir()
		assert result.name == "brain"


class TestGetAntigravityRulesDir:
	def test_returns_rules_subdir(self):
		result = paths.get_antigravity_rules_dir()
		assert result.name == "rules"


class TestGetAntigravityConversationsDir:
	def test_returns_conversations_subdir(self):
		result = paths.get_antigravity_conversations_dir()
		assert result.name == "conversations"


class TestGetSwarmConfigPath:
	def test_returns_json_file(self):
		result = paths.get_swarm_config_path()
		assert result.name == "swarm_communities.json"


class TestMigrateLegacyAgentDirs:
	def test_no_legacy_dir(self, tmp_path, monkeypatch):
		monkeypatch.setattr(Path, "home", lambda: tmp_path / "nonexistent")
		# Should not raise
		paths.migrate_legacy_agent_dirs()

	def test_migrates_file(self, tmp_path, monkeypatch):
		fake_home = tmp_path / "home"
		fake_home.mkdir()
		monkeypatch.setattr(Path, "home", lambda: fake_home)

		legacy = fake_home / ".agent"
		legacy.mkdir()
		thread_state = legacy / "thread_state.json"
		thread_state.write_text('{"state": "test"}', encoding="utf-8")

		# Ensure target parent doesn't have data yet
		target = paths.get_thread_state_path()
		if target.exists():
			target.unlink()

		paths.migrate_legacy_agent_dirs()
		assert target.exists()

	def test_skips_when_dst_has_data(self, tmp_path, monkeypatch):
		fake_home = tmp_path / "home"
		fake_home.mkdir()
		monkeypatch.setattr(Path, "home", lambda: fake_home)

		legacy = fake_home / ".agent"
		legacy.mkdir()
		src_file = legacy / "thread_state.json"
		src_file.write_text('{"new": "data"}', encoding="utf-8")

		# Pre-populate target with data
		dst = paths.get_thread_state_path()
		dst.parent.mkdir(parents=True, exist_ok=True)
		dst.write_text('{"existing": "data"}', encoding="utf-8")

		paths.migrate_legacy_agent_dirs()
		# Source should be deleted since dst has data
		assert not src_file.exists()
		# Target should still have original data
		assert dst.read_text(encoding="utf-8") == '{"existing": "data"}'
