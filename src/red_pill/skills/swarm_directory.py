import json
import os

import firebase_admin
from firebase_admin import credentials, db


class SwarmDirectorySkill:
	"""
	Skill: Swarm Directory Query
	Description: Queries the Firebase Registry to list all connected Agents and Operators.
	Intent Mapping: "¿Quién hay en la comunidad X?", "Lista los miembros del Enjambre".
	"""

	CONFIG_FILE = os.path.expanduser("~/.agent/config/swarm_communities.json")

	def execute(self, community_alias: str):
		if not os.path.exists(self.CONFIG_FILE):
			return {"status": "error", "message": "No hay comunidades configuradas. Usa primero 'Únete a la comunidad X'."}

		with open(self.CONFIG_FILE, "r") as f:
			communities = json.load(f)

		if community_alias not in communities:
			return {"status": "error", "message": f"No estás suscrito a la comunidad '{community_alias}'."}

		community_data = communities[community_alias]
		secure_json_path = community_data["credential_path"]
		db_url = community_data["db_url"]

		try:
			# Check if app is already initialized to prevent errors on multiple runs
			if not firebase_admin._apps:
				cred = credentials.Certificate(secure_json_path)
				firebase_admin.initialize_app(cred, {"databaseURL": db_url})

			# Query the /registry path
			ref = db.reference("registry")
			members = ref.get()

			if not members:
				return {"status": "success", "message": f"La comunidad '{community_alias}' está vacía actualmente."}

			# Format output
			member_list = [
				f"- {data['alias']} (Estado: {data['status']})" for key, data in members.items() if data.get("community") == community_alias
			]

			if not member_list:
				return {"status": "success", "message": f"No hay nadie activo en la comunidad '{community_alias}'."}

			report = f"Miembros en '{community_alias}':\n" + "\n".join(member_list)
			return {"status": "success", "message": report}

		except Exception as e:
			return {"status": "error", "message": f"Error al intentar consultar el directorio base de datos Firebase Admin: {e}"}
