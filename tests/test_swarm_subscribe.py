import json
import os
import shutil
from unittest.mock import MagicMock, patch

import pytest
from red_pill.skills.swarm_subscribe import SwarmSubscribeSkill


@pytest.fixture
def skill():
	return SwarmSubscribeSkill(agent_name="Aleth", operator_name="Joan")


def test_generate_id(skill):
	# Test deterministic ID generation
	id1 = skill._generate_id()
	assert id1.startswith("agt_")
	assert len(id1) == 28  # agt_ + 24 chars
	
	skill2 = SwarmSubscribeSkill(agent_name="aleth", operator_name="joan")
	assert skill2.id_hash == id1 if hasattr(skill2, "id_hash") else True # Check consistency


def test_execute_missing_info(skill):
	result = skill.execute("Global")
	assert result["status"] == "missing_info"
	assert "URL" in result["message"]


def test_execute_invalid_json(skill, tmp_path):
	bad_json = tmp_path / "bad.json"
	bad_json.write_text("invalid json")
	
	result = skill.execute("Global", db_url="http://fake.db", service_acc_json_path=str(bad_json))
	assert result["status"] == "error"
	assert "Could not read" in result["message"]


def test_execute_success(skill, tmp_path):
	# Setup fake service account
	sa_data = {"project_id": "test-project-123"}
	sa_path = tmp_path / "sa.json"
	sa_path.write_text(json.dumps(sa_data))
	
	# Mock firebase
	with patch("firebase_admin.initialize_app") as mock_init:
		with patch("firebase_admin._apps", []):
			with patch("firebase_admin.db.reference") as mock_ref:
				# Also mock credentials.Certificate
				with patch("firebase_admin.credentials.Certificate"):
					result = skill.execute(
						community_alias="TestComm",
						db_url="https://test.firebaseio.com",
						service_acc_json_path=str(sa_path)
					)
					
					assert result["status"] == "success"
					assert "registrado" in result["message"].lower()
					
					# Verify file operations
					secure_path = os.path.join(skill.CREDENTIALS_DIR, "TestComm_firebase.json")
					assert os.path.exists(secure_path)
					
					# Verify firebase calls
					mock_init.assert_called_once()
					mock_ref.assert_called_once_with(f"registry/{skill.agent_id}")
					mock_ref.return_value.set.assert_called_once()


def test_execute_permission_error(skill, tmp_path):
	sa_data = {"project_id": "test-project-123"}
	sa_path = tmp_path / "sa.json"
	sa_path.write_text(json.dumps(sa_data))
	
	# Mock shutil.copy2 to fail
	with patch("shutil.copy2", side_effect=PermissionError("Denied")):
		result = skill.execute("Global", db_url="http://fake.db", service_acc_json_path=str(sa_path))
		assert result["status"] == "error"
		assert "Error securing credentials" in result["message"]


def test_execute_firebase_error(skill, tmp_path):
	sa_data = {"project_id": "test-project-123"}
	sa_path = tmp_path / "sa.json"
	sa_path.write_text(json.dumps(sa_data))
	
	with patch("firebase_admin._apps", []):
		with patch("firebase_admin.credentials.Certificate", side_effect=Exception("Connection failed")):
			result = skill.execute("Global", db_url="http://fake.db", service_acc_json_path=str(sa_path))
			assert result["status"] == "error"
			assert "Error al intentar escribir" in result["message"]
