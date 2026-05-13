import logging

import requests
import urllib3

from red_pill.utils.antigravity_history.discovery import discover_language_servers, find_all_endpoints

# Suppress insecure request warnings for localhost https
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class AntigravityIDEClient:
	def __init__(self):
		self.port = None
		self.csrf = None
		self.connected = False
		self._discover_endpoint()

	def _discover_endpoint(self):
		servers = discover_language_servers()
		if not servers:
			logger.warning("No IDE LanguageServers found.")
			return

		endpoints = find_all_endpoints(servers)
		if endpoints:
			ep = endpoints[0]
			self.port = ep["port"]
			self.csrf = ep["csrf"]
			self.connected = True
			logger.info(f"Connected to IDE gRPC-Web on port {self.port}")
		else:
			logger.error("Could not find a valid IDE endpoint.")

	def _get_headers(self):
		if not self.connected:
			self._discover_endpoint()

		return {
			"Content-Type": "application/json",
			"Connect-Protocol-Version": "1",
			"X-Codeium-Csrf-Token": self.csrf,
		}

	def _url(self, method: str) -> str:
		return f"https://localhost:{self.port}/exa.language_server_pb.LanguageServerService/{method}"

	def get_trajectory_status(self, cascade_id: str) -> str:
		"""Returns the status of a specific cascade: CASCADE_RUN_STATUS_IDLE or CASCADE_RUN_STATUS_RUNNING"""
		if not self.connected:
			return "ERROR_DISCONNECTED"

		resp = requests.post(self._url("GetAllCascadeTrajectories"), headers=self._get_headers(), json={}, verify=False)
		if resp.status_code == 200:
			data = resp.json()
			traj = data.get("trajectorySummaries", {}).get(cascade_id, {})
			return str(traj.get("status", "UNKNOWN"))
		return f"ERROR_{resp.status_code}"

	def start_cascade(self) -> str:
		"""Starts a new cascade and returns the cascade_id"""
		if not self.connected:
			self._discover_endpoint()

		payload = {
			"trajectoryType": 4  # CORTEX_TRAJECTORY_TYPE_CASCADE
		}
		resp = requests.post(self._url("StartCascade"), headers=self._get_headers(), json=payload, verify=False)
		if resp.status_code == 200:
			return str(resp.json().get("cascadeId"))
		raise RuntimeError(f"Failed to StartCascade: {resp.status_code} {resp.text}")

	def send_user_message(self, cascade_id: str, text: str, model_id: str = "MODEL_PLACEHOLDER_M37") -> bool:
		"""Injects a user message and triggers generation using the cascadeConfig."""
		payload = {
			"cascadeId": cascade_id,
			"items": [{"text": text}],
			"cascadeConfig": {
				"plannerConfig": {
					"requestedModel": {
						"model": model_id  # Usa el placeholder nativo para respetar la selección del usuario en el IDE
					},
					"conversational": {"plannerMode": "CONVERSATIONAL_PLANNER_MODE_DEFAULT", "agenticMode": True},
				}
			},
		}
		resp = requests.post(self._url("SendUserCascadeMessage"), headers=self._get_headers(), json=payload, verify=False)
		if resp.status_code == 200:
			return True
		elif resp.status_code == 500:
			logger.warning(f"IDE returned 500 on injection. IDE is likely locked (RUNNING). Body: {resp.text}")
			return False
		else:
			logger.error(f"Failed to inject: {resp.status_code} {resp.text}")
			return False

	def get_cascade_trajectory(self, cascade_id: str) -> dict:
		"""Fetches the full trajectory to read the generated steps (Strategy B Polling)."""
		payload = {"cascadeId": cascade_id}
		resp = requests.post(self._url("GetCascadeTrajectory"), headers=self._get_headers(), json=payload, verify=False)
		if resp.status_code == 200:
			data: dict = resp.json()
			return data
		logger.error(f"Failed to get trajectory: {resp.status_code} {resp.text}")
		return {}

	def get_cascade_trajectory_steps(self, cascade_id: str, start_index: int = 0, end_index: int = 1000) -> list:
		"""Fetches the exact steps with pagination to avoid truncation limits."""
		payload = {
			"cascadeId": cascade_id,
			"startIndex": start_index,
			"endIndex": end_index
		}
		resp = requests.post(self._url("GetCascadeTrajectorySteps"), headers=self._get_headers(), json=payload, verify=False)
		if resp.status_code == 200:
			data: dict = resp.json()
			return list(data.get("steps", data.get("messages", [])))
		logger.error(f"Failed to get trajectory steps: {resp.status_code} {resp.text}")
		return []
