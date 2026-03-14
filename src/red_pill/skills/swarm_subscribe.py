import hashlib
import json
import os
import shutil
from typing import Any, Optional, Tuple

import firebase_admin
from firebase_admin import credentials, db


from typing import Any, Optional, Tuple, Dict

from red_pill.swarm.transports.manager import TransportManager


class SwarmSubscribeSkill:
	"""
	Skill: Swarm Subscribe v3.0
	Description: Agnostic subscription to N communities using Transport plugins.
	"""

	CREDENTIALS_DIR = os.path.expanduser("~/.agent/credentials")
	CONFIG_FILE = os.path.expanduser("~/.agent/config/swarm_communities.json")

	def __init__(self, agent_name: str, operator_name: str, transport_manager: Optional[TransportManager] = None):
		self.agent_name = agent_name
		self.operator_name = operator_name
		self.agent_identity = f"{agent_name}@{operator_name}"
		self.agent_id = self._generate_id()
		self.keys_dir = os.path.expanduser("~/.agent/keys")
		self.tm = transport_manager or TransportManager()
		os.makedirs(self.CREDENTIALS_DIR, exist_ok=True)
		os.makedirs(self.keys_dir, exist_ok=True)
		os.makedirs(os.path.dirname(self.CONFIG_FILE), exist_ok=True)

	def _generate_id(self) -> str:
		raw = f"{self.agent_name.lower().strip()}:{self.operator_name.lower().strip()}"
		return f"agt_{hashlib.sha256(raw.encode()).hexdigest()[:24]}"

	def _get_or_create_keys(self) -> Tuple[bytes, bytes]:
		"""Retrieves existing keys or generates a new pair."""
		from red_pill.swarm.crypto import SwarmCrypto
		priv_path = os.path.join(self.keys_dir, "swarm_v2.priv")
		pub_path = os.path.join(self.keys_dir, "swarm_v2.pub")

		if os.path.exists(priv_path) and os.path.exists(pub_path):
			with open(priv_path, "rb") as f:
				priv = f.read()
			with open(pub_path, "rb") as f:
				pub = f.read()
			return priv, pub

		priv, pub = SwarmCrypto.generate_x25519_keypair()
		with open(priv_path, "wb") as f:
			f.write(priv)
		os.chmod(priv_path, 0o600)
		with open(pub_path, "wb") as f:
			f.write(pub)
		
		return priv, pub

	def execute(self, community_alias: str, db_url: Optional[str] = None, service_acc_json_path: Optional[str] = None) -> dict[str, str]:
		"""
		Registers the Agent using the appropriate Transport plugin.
		"""
		if db_url is None or service_acc_json_path is None:
			return {
				"status": "missing_info",
				"message": "Necesito la URL de la DB y la ruta al JSON de credenciales para la suscripción."
			}

		# 1. Store the Service Account/Config (This part remains as it defines the community configuration)
		secure_json_path = os.path.join(self.CREDENTIALS_DIR, f"{community_alias}_firebase.json")
		try:
			shutil.copy2(service_acc_json_path, secure_json_path)
			os.chmod(secure_json_path, 0o600)
		except Exception as e:
			return {"status": "error", "message": f"Error securing credentials: {e}"}

		# 2. Save the Community Config
		communities: dict[str, Any] = {}
		if os.path.exists(self.CONFIG_FILE):
			with open(self.CONFIG_FILE, "r") as f:
				communities = json.load(f)

		communities[community_alias] = {
			"db_url": db_url,
			"credential_path": secure_json_path,
			"agent_identity": self.agent_identity,
			"agent_id": self.agent_id,
			"type": "firebase" # Defaulting for now
		}

		with open(self.CONFIG_FILE, "w") as f:
			json.dump(communities, f, indent=4)

		# 3. Perform Broadcast via Transport
		self.tm._load_communities() # Refresh manager
		transport = self.tm.get_transport(community_alias)
		if not transport:
			return {"status": "error", "message": f"Could not initialize transport for {community_alias}."}

		_, pub_bytes = self._get_or_create_keys()
		pub_b64 = base64.b64encode(pub_bytes).decode("utf-8")

		metadata = {
			"alias": self.agent_identity,
			"status": "online",
			"role": "Agent",
			"community": community_alias,
			"public_key": pub_b64,
			"v": "3.0"
		}

		if transport.broadcast_identity(self.agent_id, metadata):
			return {"status": "success", "message": f"¡Suscripción a '{community_alias}' completada vía {type(transport).__name__}!"}
		else:
			return {"status": "error", "message": "Fallo en el broadcast de identidad."}
