import hashlib
import json
import os
import shutil
import firebase_admin
from firebase_admin import credentials, db

class SwarmSubscribeSkill:
    """
    Skill: Swarm Subscribe
    Description: Allows the Agent to subscribe to a new Firebase/Swarm Community HUB dynamically.
                 Handles securely storing the Firebase Service Account JSON and connection URLs.
    Intent Mapping: "Únete a la comunidad Global", "Conecta con el Firebase de Enterprise".
    """
    
    CREDENTIALS_DIR = os.path.expanduser("~/.agent/credentials")
    CONFIG_FILE = os.path.expanduser("~/.agent/config/swarm_communities.json")

    def __init__(self, agent_name: str, operator_name: str):
        self.agent_name = agent_name
        self.operator_name = operator_name
        self.agent_id = self._generate_id()
        os.makedirs(self.CREDENTIALS_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(self.CONFIG_FILE), exist_ok=True)
    
    def _generate_id(self) -> str:
        raw = f"{self.agent_name.lower().strip()}:{self.operator_name.lower().strip()}"
        return f"agt_{hashlib.sha256(raw.encode()).hexdigest()[:24]}"
        
    def execute(self, community_alias: str, db_url: str = None, service_acc_json_path: str = None):
        """
        Registers the Agent's Routing ID in the target Firebase Registry.
        If credentials are not provided, outputs what is needed.
        """
        if not all([db_url, service_acc_json_path]):
            return {
                "status": "missing_info",
                "message": (
                    f"Para suscribirnos a la comunidad '{community_alias}' a través del SDK de Firebase Admin unificado, necesito 2 datos:\n"
                    "1. La URL de la Base de Datos (ej. https://tu-comunidad-default-rtdb.europe-west1.firebasedatabase.app).\n"
                    "2. La ruta local al archivo de claves JSON. Lo puedes generar en Firebase Console -> Configuración del proyecto -> Cuentas de servicio -> 'SDK de Firebase Admin' -> botón 'Generar nueva clave privada'.\n"
                    "Dámelos y yo me encargaré de extraer tu Project ID y blindar la conexión vía ~/.agent/credentials/."
                )
            }
            
        print(f"[Swarm Subscribe] Processing subscription to Hub: {community_alias}")
        
        # Parse the project_id from the Google Service Account JSON explicitly
        try:
            with open(service_acc_json_path, 'r') as f:
                 key_data = json.load(f)
                 project_id = key_data.get("project_id", "NOT_FOUND_IN_SDK_KEY")
        except Exception as e:
            return {"status": "error", "message": f"Could not read the Firebase Admin SDK JSON: {e}"}
        
        # 1. Store the Service Account securely
        secure_json_path = os.path.join(self.CREDENTIALS_DIR, f"{community_alias}_firebase.json")
        try:
            shutil.copy2(service_acc_json_path, secure_json_path)
            os.chmod(secure_json_path, 0o600)  # Restrict permissions
        except Exception as e:
            return {"status": "error", "message": f"Error securing credentials: {e}"}

        # 2. Save the Community Config
        communities = {}
        if os.path.exists(self.CONFIG_FILE):
             with open(self.CONFIG_FILE, 'r') as f:
                 communities = json.load(f)
                 
        communities[community_alias] = {
            "project_id": project_id,
            "db_url": db_url,
            "credential_path": secure_json_path,
            "agent_identity_string": f"{self.agent_name}@{self.operator_name}",
            "agent_id_hash": self.agent_id
        }
        
        with open(self.CONFIG_FILE, 'w') as f:
            json.dump(communities, f, indent=4)
            
        print(f"[Swarm Subscribe] Broadcasting Identity: {self.agent_name}@{self.operator_name} -> {self.agent_id}")
        
        # Connect to Firebase via the Admin SDK and write the Document
        try:
            # Check if app is already initialized to prevent errors on multiple runs
            if not firebase_admin._apps:
                cred = credentials.Certificate(secure_json_path)
                firebase_admin.initialize_app(cred, {
                    'databaseURL': db_url 
                })
            
            ref = db.reference(f'registry/{self.agent_id}')
            ref.set({
                "alias": f"{self.agent_name}@{self.operator_name}",
                "status": "online",
                "role": "Agent",
                "community": community_alias
            })
            
            print(f"[Swarm Subscribe] Success! Wrote Agent {self.agent_id} to Firebase Database -> /registry")
            status_msg = f"¡Suscripción a '{community_alias}' completada! Registrado exitosamente en la base de datos."
        except Exception as e:
            return {
                "status": "error", 
                "message": f"Error al intentar escribir en la base de datos Firebase Admin: {e}"
            }
        
        return {
            "status": "success",
            "message": status_msg
        }
