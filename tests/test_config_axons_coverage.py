"""Coverage boost for config.py validators/branches and axons.py pure functions."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from red_pill.config import RedPillConfig
from red_pill.metabolism.axons import (
	_append_axon,
	_prune_cross,
	_split_associations,
	compute_axon_weight,
	load_axon_state,
	save_axon_state,
)
from red_pill.schemas import Axon, normalize_associations


# ── Axons pure functions ──────────────────────────────────────────────────

class TestComputeAxonWeight:
	def test_zero_delta(self):
		w = compute_axon_weight(similarity=0.9, delta_seconds=0.0)
		assert w > 0.5

	def test_large_delta(self):
		w = compute_axon_weight(similarity=0.5, delta_seconds=999999)
		assert w < 0.5

	def test_zero_similarity(self):
		w = compute_axon_weight(similarity=0.0, delta_seconds=0.0)
		assert w >= 0.0


class TestSplitAssociations:
	def test_empty_payload(self):
		local, cross = _split_associations({}, "social_memories")
		assert local == []
		assert cross == []

	def test_none_payload(self):
		local, cross = _split_associations(None, "social_memories")
		assert local == []
		assert cross == []

	def test_non_list_associations_becomes_empty(self):
		local, cross = _split_associations({"associations": "bad"}, "social_memories")
		assert local == []
		assert cross == []

	def test_local_links_kept(self):
		entry = {"id": "abc", "target_collection": "social_memories", "weight": 0.5, "association_type": "temporal_semantic"}
		local, cross = _split_associations({"associations": [entry]}, "social_memories")
		assert len(local) == 1

	def test_cross_links_parsed(self):
		entry = {"id": "abc", "target_collection": "work_memories", "weight": 0.5, "association_type": "temporal_semantic"}
		local, cross = _split_associations({"associations": [entry]}, "social_memories")
		assert len(cross) == 1
		assert len(local) == 0


class TestPruneCross:
	def test_under_cap(self):
		axons = [Axon(id="a", target_collection="work_memories", weight=0.5, association_type="temporal_semantic")]
		kept, pruned = _prune_cross(axons, cap=5)
		assert len(kept) == 1
		assert pruned == 0

	def test_over_cap_keeps_heaviest(self):
		axons = [
			Axon(id="a", target_collection="work_memories", weight=0.9, association_type="temporal_semantic"),
			Axon(id="b", target_collection="work_memories", weight=0.3, association_type="temporal_semantic"),
			Axon(id="c", target_collection="work_memories", weight=0.7, association_type="temporal_semantic"),
		]
		kept, pruned = _prune_cross(axons, cap=2)
		assert len(kept) == 2
		assert pruned == 1
		assert kept[0].weight >= kept[1].weight

	def test_empty(self):
		kept, pruned = _prune_cross([], cap=3)
		assert kept == []
		assert pruned == 0


class TestLoadSaveAxonState:
	def test_save_and_load(self, tmp_path):
		with patch("red_pill.metabolism.axons._axon_state_path", return_value=tmp_path / "state.json"):
			save_axon_state({"completed_runs": 5})
			state = load_axon_state()
			assert state["completed_runs"] == 5

	def test_load_missing_returns_default(self, tmp_path):
		with patch("red_pill.metabolism.axons._axon_state_path", return_value=tmp_path / "nonexistent.json"):
			state = load_axon_state()
			assert state == {"completed_runs": 0}


class TestAppendAxon:
	def test_appends_new_axon(self):
		client = MagicMock()
		stats = {"hard_ceiling_hits": 0}
		axon = Axon(id="target1", target_collection="work_memories", weight=0.8, association_type="temporal_semantic")
		result = _append_axon(client, "social_memories", "src1", {"associations": []}, axon, stats)
		assert result is True
		client.set_payload.assert_called_once()

	def test_duplicate_axon_rejected(self):
		client = MagicMock()
		stats = {"hard_ceiling_hits": 0}
		existing = {"id": "target1", "target_collection": "work_memories", "weight": 0.5, "association_type": "temporal_semantic"}
		axon = Axon(id="target1", target_collection="work_memories", weight=0.8, association_type="temporal_semantic")
		result = _append_axon(client, "social_memories", "src1", {"associations": [existing]}, axon, stats)
		assert result is False
		client.set_payload.assert_not_called()

	def test_hard_ceiling_hit(self):
		client = MagicMock()
		stats = {"hard_ceiling_hits": 0}
		# Create max cross axons (AXON_MAX_CROSS * 2)
		from red_pill import config as cfg
		existing = [{"id": f"t{i}", "target_collection": "work_memories", "weight": 0.5, "association_type": "temporal_semantic"} for i in range(cfg.AXON_MAX_CROSS * 2)]
		axon = Axon(id="new_target", target_collection="work_memories", weight=0.8, association_type="temporal_semantic")
		result = _append_axon(client, "social_memories", "src1", {"associations": existing}, axon, stats)
		assert result is False
		assert stats["hard_ceiling_hits"] == 1


# ── Config validators & branches ──────────────────────────────────────────

class TestDetectContainerEngine:
	@patch("red_pill.config.shutil.which")
	def test_podman_found(self, mock_which):
		mock_which.side_effect=lambda cmd: "/usr/bin/podman" if cmd == "podman" else None
		from red_pill.config import _detect_container_engine
		assert _detect_container_engine() == "podman"

	@patch("red_pill.config.shutil.which")
	def test_docker_fallback(self, mock_which):
		mock_which.side_effect=lambda cmd: "/usr/bin/docker" if cmd == "docker" else None
		from red_pill.config import _detect_container_engine
		assert _detect_container_engine() == "docker"

	@patch("red_pill.config.shutil.which", return_value=None)
	def test_default_podman(self, mock_which):
		from red_pill.config import _detect_container_engine
		assert _detect_container_engine() == "podman"


class TestConfigValidators:
	def test_normalize_hydration_depth(self):
		from red_pill.config import RedPillConfig
		assert RedPillConfig._normalize_hydration_depth("  high  ") == "HIGH"

	def test_normalize_hydration_depth_non_string(self):
		from red_pill.config import RedPillConfig
		assert RedPillConfig._normalize_hydration_depth(123) == "HIGH"

	def test_normalize_identity_depth_valid(self):
		from red_pill.config import RedPillConfig
		assert RedPillConfig._normalize_identity_depth("LOW") == "low"

	def test_normalize_identity_depth_invalid(self):
		from red_pill.config import RedPillConfig
		assert RedPillConfig._normalize_identity_depth("INVALID") == "medium"

	def test_normalize_identity_depth_non_string(self):
		from red_pill.config import RedPillConfig
		assert RedPillConfig._normalize_identity_depth(None) == "medium"

	def test_qdrant_url_memory(self):
		cfg = RedPillConfig(QDRANT_HOST=":memory:")
		assert cfg.QDRANT_URL == ":memory:"

	def test_qdrant_url_normal(self):
		cfg = RedPillConfig(QDRANT_HOST="localhost", QDRANT_PORT=6333)
		assert cfg.QDRANT_URL == "http://localhost:6333"

	def test_ide_backend_valid(self):
		from red_pill.config import RedPillConfig
		assert RedPillConfig._validate_ide_backend("CLAUDE") == "claude"

	def test_ide_backend_invalid(self):
		from red_pill.config import RedPillConfig
		with pytest.raises(ValueError):
			RedPillConfig._validate_ide_backend("invalid")

	def test_parse_bridge_cascades_string(self):
		from red_pill.config import RedPillConfig
		result = RedPillConfig._parse_bridge_cascades('[{"backend": "local"}]')
		assert isinstance(result, list)

	def test_parse_bridge_cascades_invalid_json(self):
		from red_pill.config import RedPillConfig
		with pytest.raises(ValueError):
			RedPillConfig._parse_bridge_cascades("not-json")

	def test_parse_bridge_cascades_passthrough(self):
		from red_pill.config import RedPillConfig
		assert RedPillConfig._parse_bridge_cascades([{"backend": "local"}]) == [{"backend": "local"}]

	def test_parse_deep_recall_triggers_string(self):
		from red_pill.config import RedPillConfig
		result = RedPillConfig._parse_deep_recall_triggers("wake up,despierta")
		assert result == ["wake up", "despierta"]

	def test_parse_deep_recall_triggers_passthrough(self):
		from red_pill.config import RedPillConfig
		assert RedPillConfig._parse_deep_recall_triggers(["a"]) == ["a"]

	def test_parse_chronicle_plugins_json_string(self):
		from red_pill.config import RedPillConfig
		result = RedPillConfig._parse_chronicle_plugins('["antigravity"]')
		assert result == ["antigravity"]

	def test_parse_chronicle_plugins_csv_string(self):
		from red_pill.config import RedPillConfig
		result = RedPillConfig._parse_chronicle_plugins("antigravity, claude_code")
		assert result == ["antigravity", "claude_code"]

	def test_parse_chronicle_plugins_passthrough(self):
		from red_pill.config import RedPillConfig
		assert RedPillConfig._parse_chronicle_plugins(["x"]) == ["x"]

	def test_parse_collections_string(self):
		from red_pill.config import RedPillConfig
		result = RedPillConfig._parse_collections("work, social")
		assert result == ["work", "social"]

	def test_parse_collections_passthrough(self):
		from red_pill.config import RedPillConfig
		assert RedPillConfig._parse_collections(["a"]) == ["a"]

	def test_parse_colors_string(self):
		from red_pill.config import RedPillConfig
		result = RedPillConfig._parse_colors("purple, blue")
		assert result == ["purple", "blue"]

	def test_parse_colors_passthrough(self):
		from red_pill.config import RedPillConfig
		assert RedPillConfig._parse_colors(["red"]) == ["red"]

	def test_semantic_intent_threshold_high(self):
		cfg = RedPillConfig(SEMANTIC_INTENT_THRESHOLD_STR="HIGH")
		assert cfg.SEMANTIC_INTENT_THRESHOLD == 0.75

	def test_semantic_intent_threshold_low(self):
		cfg = RedPillConfig(SEMANTIC_INTENT_THRESHOLD_STR="LOW")
		assert cfg.SEMANTIC_INTENT_THRESHOLD == 0.5

	def test_be_water_user_override(self):
		cfg = RedPillConfig(MAX_PAYLOAD_CHARS=9999)
		assert cfg.MAX_PAYLOAD_CHARS == 9999

	def test_be_water_no_torch(self):
		with patch.dict("sys.modules", {"torch": None}):
			cfg = RedPillConfig()
			# Should not crash; MAX_PAYLOAD_CHARS stays None
			assert cfg.MAX_PAYLOAD_CHARS is None

	def test_build_deep_recall_triggers_with_custom(self):
		cfg = RedPillConfig(DEEP_RECALL_TRIGGERS=["custom_trigger"])
		assert "custom_trigger" in cfg.DEEP_RECALL_TRIGGERS

	def test_runtime_dir_xdg(self, monkeypatch, tmp_path):
		monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
		cfg = RedPillConfig()
		assert cfg.RUNTIME_DIR == str(tmp_path)

	def test_runtime_dir_posix_fallback(self, monkeypatch):
		monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
		uid_dir = "/run/user/999"
		with patch("red_pill.config.os.path.exists", side_effect=lambda p: p == uid_dir):
			with patch("red_pill.config.os.getuid", return_value=999):
				with patch("red_pill.config.os.name", "posix"):
					cfg = RedPillConfig()
					assert cfg.RUNTIME_DIR == uid_dir

	def test_runtime_dir_tempdir_fallback(self, monkeypatch, tmp_path):
		monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
		with patch("red_pill.config.os.path.exists", return_value=False):
			with patch("red_pill.config.os.name", "posix"):
				cfg = RedPillConfig()
				assert cfg.RUNTIME_DIR == tempfile.gettempdir()

	def test_be_water_torch_low_vram(self):
		fake_torch = MagicMock()
		fake_props = MagicMock()
		fake_props.total_memory = 3e9  # 3 GB
		fake_torch.cuda.get_device_properties.return_value = fake_props
		with patch.dict("sys.modules", {"torch": fake_torch}):
			cfg = RedPillConfig()
			assert cfg.MAX_PAYLOAD_CHARS == 1_000

	def test_be_water_torch_medium_vram(self):
		fake_torch = MagicMock()
		fake_props = MagicMock()
		fake_props.total_memory = 6e9  # 6 GB
		fake_torch.cuda.get_device_properties.return_value = fake_props
		with patch.dict("sys.modules", {"torch": fake_torch}):
			cfg = RedPillConfig()
			assert cfg.MAX_PAYLOAD_CHARS == 5_000

	def test_be_water_torch_high_vram(self):
		fake_torch = MagicMock()
		fake_props = MagicMock()
		fake_props.total_memory = 16e9  # 16 GB
		fake_torch.cuda.get_device_properties.return_value = fake_props
		with patch.dict("sys.modules", {"torch": fake_torch}):
			cfg = RedPillConfig()
			assert cfg.MAX_PAYLOAD_CHARS is None


class TestModuleLevelAliases:
	def test_semantic_intent_threshold_alias(self):
		import red_pill.config as cfg
		val = cfg.SEMANTIC_INTENT_THRESHOLD
		assert isinstance(val, float)

	def test_bayesian_collections_alias(self):
		import red_pill.config as cfg
		val = cfg.BAYESIAN_COLLECTIONS
		assert isinstance(val, (list, tuple, set))

	def test_permanent_collections_alias(self):
		import red_pill.config as cfg
		val = cfg.PERMANENT_COLLECTIONS
		assert isinstance(val, (list, tuple, set))

	def test_memory_engines_alias(self):
		import red_pill.config as cfg
		val = cfg.MEMORY_ENGINES
		assert isinstance(val, (list, tuple, set, dict))

	def test_chroma_tone_mapping_alias(self):
		import red_pill.config as cfg
		val = cfg.CHROMA_TONE_MAPPING
		assert isinstance(val, dict)

	def test_current_schema_version_alias(self):
		import red_pill.config as cfg
		val = cfg.CURRENT_SCHEMA_VERSION
		assert val is not None

	def test_emotional_decay_multipliers_alias(self):
		import red_pill.config as cfg
		val = cfg.EMOTIONAL_DECAY_MULTIPLIERS
		assert isinstance(val, dict)


class TestLoadAffectMultipliers:
	def test_missing_model_falls_back_to_pioneer(self):
		from red_pill.config import _load_affect_multipliers
		result = _load_affect_multipliers("NONEXISTENT_MODEL_999")
		assert "orange" in result

	def test_error_path_returns_defaults(self):
		from red_pill.config import _load_affect_multipliers
		with patch("builtins.open", side_effect=OSError("disk full")):
			result = _load_affect_multipliers("PIONEER")
		assert "orange" in result


class TestContainerDetection:
	def test_detect_container_when_empty(self):
		cfg = RedPillConfig(CONTAINER_ENGINE="")
		assert cfg.CONTAINER_ENGINE in ("podman", "docker")


class TestModuleLevelGetattr:
	def test_cfg_function(self):
		from red_pill.config import _cfg
		result = _cfg()
		assert result is not None

	def test_get_config_cached_no_env(self):
		from red_pill.config import get_config_cached
		result = get_config_cached(None)
		assert result is not None

	def test_set_enterprise_overrides_when_singleton_not_ready(self, monkeypatch):
		import red_pill.config as cfg_mod
		monkeypatch.setattr(cfg_mod, "_enterprise_overrides_store", {})
		# Force cache clear to simulate "singleton not yet created"
		cfg_mod.get_config.cache_clear()
		# This should hit the exception path and clear cache
		cfg_mod.set_enterprise_overrides({"key": "value"})
		assert cfg_mod._enterprise_overrides_store == {"key": "value"}


class TestHiveConnectionFailure:
	def test_connection_failure_sets_connected_false(self, monkeypatch):
		fake_connections = MagicMock()
		fake_connections.connect.side_effect = ConnectionError("refused")
		monkeypatch.setattr("red_pill.hive.connections", fake_connections)
		monkeypatch.setattr("red_pill.hive.cfg", type("C", (), {
			"MILVUS_ENABLED": True, "MILVUS_HOST": "localhost", "MILVUS_PORT": 19530,
			"MILVUS_SECURE": False, "MILVUS_TIMEOUT": 5, "MILVUS_LITE_ENABLED": False,
			"MILVUS_USER": "", "MILVUS_PASSWORD": "", "MILVUS_DB": "default",
		})())
		from red_pill.hive import HiveMind
		hive = HiveMind()
		assert hive.connected is False


class TestNormalizeAssociationsAxon:
	def test_axon_object_kept(self):
		axon = Axon(id="a", target_collection="work_memories", weight=0.5, association_type="temporal_semantic")
		result = normalize_associations([axon])
		assert len(result) == 1
		assert result[0].id == "a"
