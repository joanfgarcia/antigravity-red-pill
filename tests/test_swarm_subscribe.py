import json
import os
from unittest.mock import MagicMock, patch

from red_pill.skills.swarm_subscribe import SwarmSubscribeSkill


def test_generate_id():
	skill = SwarmSubscribeSkill(agent_name="Aleth", operator_name="Joan")
	id1 = skill._generate_id()
	assert id1.startswith("agt_")
	assert len(id1) == 28


def test_execute_missing_info():
	skill = SwarmSubscribeSkill(agent_name="Aleth", operator_name="Joan")
	result = skill.execute("Global")
	assert result["status"] == "missing_info"
	assert "URL" in result["message"]


def test_execute_invalid_json(tmp_path):
	bad_json = tmp_path / "bad.json"
	bad_json.write_text("invalid json")
	skill = SwarmSubscribeSkill(agent_name="Aleth", operator_name="Joan")
	result = skill.execute("Global", db_url="http://fake.db", service_acc_json_path=str(bad_json))
	assert result["status"] == "error"
	assert "Could not" in result["message"]


def test_execute_success(tmp_path):
	sa_data = {"project_id": "test-project-123", "type": "service_account"}
	sa_path = tmp_path / "sa.json"
	sa_path.write_text(json.dumps(sa_data))
	with patch("red_pill.swarm.transports.manager.TransportManager._load_communities"):
		with patch("firebase_admin.initialize_app"):
			with patch("firebase_admin._apps", []):
				with patch("firebase_admin.db.reference"):
					with patch("firebase_admin.credentials.Certificate"):
						skill = SwarmSubscribeSkill(agent_name="Aleth", operator_name="Joan")
						mock_transport = MagicMock()
						with patch.object(skill.tm, "get_transport", return_value=mock_transport):
							mock_transport.broadcast_identity.return_value = True
							result = skill.execute(
								community_alias="TestComm", db_url="https://test.firebaseio.com", service_acc_json_path=str(sa_path)
							)
							assert result["status"] == "success"
							assert "suscripción" in result["message"].lower()
							secure_path = os.path.join(skill.CREDENTIALS_DIR, "TestComm_firebase.json")
							assert os.path.exists(secure_path)


def test_execute_permission_error(tmp_path):
	sa_data = {"project_id": "test-project-123"}
	sa_path = tmp_path / "sa.json"
	sa_path.write_text(json.dumps(sa_data))
	skill = SwarmSubscribeSkill(agent_name="Aleth", operator_name="Joan")
	with patch("shutil.copy2", side_effect=PermissionError("Denied")):
		result = skill.execute("Global", db_url="http://fake.db", service_acc_json_path=str(sa_path))
		assert result["status"] == "error"
		assert "Error securing credentials" in result["message"]


def test_execute_firebase_error(tmp_path):
	sa_data = {"project_id": "test-project-123"}
	sa_path = tmp_path / "sa.json"
	sa_path.write_text(json.dumps(sa_data))
	with patch("red_pill.swarm.transports.manager.TransportManager._load_communities"):
		skill = SwarmSubscribeSkill(agent_name="Aleth", operator_name="Joan")
		with patch("firebase_admin._apps", []):
			with patch("firebase_admin.credentials.Certificate", side_effect=Exception("Connection failed")):
				result = skill.execute("Global", db_url="http://fake.db", service_acc_json_path=str(sa_path))
				assert result["status"] == "error"
				assert "Could not" in result["message"]
